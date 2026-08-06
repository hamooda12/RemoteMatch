import hashlib
from datetime import UTC, datetime
from decimal import Decimal

import httpx
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    ValidationError,
)

from app.integrations.job_sources.arbeitnow import (
    html_to_plain_text,
)
from app.integrations.job_sources.base import (
    JobSourceError,
    JobSourceFetchResult,
)
from app.integrations.job_sources.retry import (
    is_retryable_httpx_error,
    retry_async,
)
from app.schemas.job_ingestion import JobIngestionRecord
from app.services.cv_skill_extractor import (
    extract_skills,
)

HIMALAYAS_SOURCE_NAME = "himalayas"
HIMALAYAS_API_URL = "https://himalayas.app/jobs/api"
HIMALAYAS_PAGE_SIZE = 20
MAX_SOURCE_RESPONSE_BYTES = 20 * 1024 * 1024

_REQUEST_TIMEOUT = httpx.Timeout(
    connect=10.0,
    read=30.0,
    write=10.0,
    pool=10.0,
)

_ANNUAL_SALARY_MULTIPLIERS = {
    "hourly": Decimal("2080"),
    "weekly": Decimal("52"),
    "fortnightly": Decimal("26"),
    "monthly": Decimal("12"),
    "annual": Decimal("1"),
}

_EMPLOYMENT_TYPE_MAP = {
    "full time": "full_time",
    "part time": "part_time",
    "contractor": "contract",
    "temporary": "temporary",
    "intern": "internship",
    "volunteer": "volunteer",
    "other": "other",
}

_EXPERIENCE_LEVEL_PRIORITY = (
    ("Executive", "senior"),
    ("Director", "senior"),
    ("Manager", "senior"),
    ("Senior", "senior"),
    ("Mid-level", "mid_level"),
    ("Entry-level", "entry_level"),
)


class HimalayasSourceError(JobSourceError):
    """Raised when Himalayas cannot be fetched or parsed."""


class _HimalayasLocation(BaseModel):
    model_config = ConfigDict(extra="ignore")

    alpha2: str = Field(
        min_length=2,
        max_length=2,
    )
    name: str = Field(
        min_length=1,
        max_length=100,
    )
    slug: str = Field(
        min_length=1,
        max_length=100,
    )


class _HimalayasJob(BaseModel):
    model_config = ConfigDict(extra="ignore")

    title: str = Field(
        min_length=1,
        max_length=255,
    )
    excerpt: str = Field(
        default="",
        max_length=100_000,
    )
    company_name: str = Field(
        alias="companyName",
        min_length=1,
        max_length=255,
    )
    employment_type: str = Field(
        alias="employmentType",
        min_length=1,
        max_length=50,
    )
    min_salary: Decimal | None = Field(
        default=None,
        alias="minSalary",
        ge=0,
    )
    max_salary: Decimal | None = Field(
        default=None,
        alias="maxSalary",
        ge=0,
    )
    salary_period: str = Field(
        default="annual",
        alias="salaryPeriod",
        max_length=30,
    )
    seniority: list[str] = Field(
        default_factory=list,
        max_length=10,
    )
    currency: str = Field(
        min_length=3,
        max_length=3,
    )
    location_restrictions: list[str | _HimalayasLocation] = Field(
        default_factory=list,
        alias="locationRestrictions",
        max_length=100,
    )
    timezone_restrictions: list[str | int | float] = Field(
        default_factory=list,
        alias="timezoneRestrictions",
        max_length=100,
    )
    categories: list[str] = Field(
        default_factory=list,
        max_length=100,
    )
    parent_categories: list[str] = Field(
        default_factory=list,
        alias="parentCategories",
        max_length=100,
    )
    description: str = Field(
        min_length=1,
        max_length=500_000,
    )
    published_timestamp: int = Field(
        alias="pubDate",
        ge=0,
        le=4_102_444_800_000,
    )
    expiry_timestamp: int | None = Field(
        default=None,
        alias="expiryDate",
        ge=0,
        le=4_102_444_800_000,
    )
    application_link: HttpUrl = Field(
        alias="applicationLink",
    )
    guid: str = Field(
        min_length=1,
        max_length=2048,
    )


class _HimalayasPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    updated_at: int = Field(
        alias="updatedAt",
        ge=0,
    )
    offset: int = Field(ge=0)
    limit: int = Field(
        ge=1,
        le=HIMALAYAS_PAGE_SIZE,
    )
    total_count: int = Field(
        alias="totalCount",
        ge=0,
    )
    jobs: list[dict[str, object]]


def _timestamp_to_datetime(
    value: int,
) -> datetime:
    timestamp = value / 1000 if value > 10_000_000_000 else value

    return datetime.fromtimestamp(
        timestamp,
        tz=UTC,
    )


def _build_source_job_id(
    guid: str,
) -> str:
    normalized_guid = guid.strip()

    if len(normalized_guid) <= 255:
        return normalized_guid

    return hashlib.sha256(normalized_guid.encode("utf-8")).hexdigest()


def _normalize_locations(
    locations: list[str | _HimalayasLocation],
) -> tuple[str, list[str]]:
    normalized_locations: list[str] = []
    seen_locations: set[str] = set()

    for location in locations:
        location_name = (
            location.name
            if isinstance(
                location,
                _HimalayasLocation,
            )
            else location
        )
        cleaned_name = " ".join(location_name.split())

        if not cleaned_name:
            continue

        comparison_name = cleaned_name.casefold()

        if comparison_name in seen_locations:
            continue

        seen_locations.add(comparison_name)
        normalized_locations.append(cleaned_name)

        if len(normalized_locations) == 20:
            break

    if not normalized_locations:
        return "Worldwide", ["Worldwide"]

    combined_location = ", ".join(normalized_locations)

    if len(combined_location) > 255:
        combined_location = "Multiple remote regions"

    return (
        combined_location,
        normalized_locations,
    )


def _normalize_employment_type(
    value: str,
) -> str | None:
    return _EMPLOYMENT_TYPE_MAP.get(" ".join(value.split()).casefold())


def _normalize_experience_level(
    seniority: list[str],
    employment_type: str,
) -> str | None:
    if employment_type.casefold() == "intern":
        return "internship"

    normalized_values = {" ".join(value.split()).casefold() for value in seniority}

    for (
        source_value,
        normalized_value,
    ) in _EXPERIENCE_LEVEL_PRIORITY:
        if source_value.casefold() in normalized_values:
            return normalized_value

    return None


def _normalize_salary(
    minimum: Decimal | None,
    maximum: Decimal | None,
    period: str,
    currency: str,
) -> tuple[
    Decimal | None,
    Decimal | None,
    str | None,
]:
    if minimum is None and maximum is None:
        return None, None, None

    multiplier = _ANNUAL_SALARY_MULTIPLIERS.get(period.casefold())

    if multiplier is None:
        return None, None, None

    normalized_minimum = (
        (minimum * multiplier).quantize(Decimal("0.01")) if minimum is not None else None
    )
    normalized_maximum = (
        (maximum * multiplier).quantize(Decimal("0.01")) if maximum is not None else None
    )

    return (
        normalized_minimum,
        normalized_maximum,
        currency.upper(),
    )


class HimalayasJobSource:
    name = HIMALAYAS_SOURCE_NAME
    max_pages = 5

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.client = client

    async def fetch_page(
        self,
        page: int = 1,
    ) -> JobSourceFetchResult:
        if page < 1 or page > 10_000:
            raise ValueError("page must be between 1 and 10000")

        if self.client is not None:
            content = await self._fetch_content(
                self.client,
                page,
            )
        else:
            async with httpx.AsyncClient(
                follow_redirects=False,
            ) as client:
                content = await self._fetch_content(
                    client,
                    page,
                )

        try:
            payload = _HimalayasPayload.model_validate_json(content)
        except ValidationError as error:
            raise HimalayasSourceError("Himalayas returned an invalid response.") from error

        records: list[JobIngestionRecord] = []
        rejected_count = 0

        for raw_job in payload.jobs:
            try:
                job = _HimalayasJob.model_validate(raw_job)
                record = self._to_ingestion_record(job)
            except (
                ValidationError,
                OverflowError,
                ValueError,
            ):
                rejected_count += 1
                continue

            records.append(record)

        next_offset = payload.offset + len(payload.jobs)
        has_next_page = bool(payload.jobs) and next_offset < payload.total_count

        return JobSourceFetchResult(
            records=tuple(records),
            page=page,
            has_next_page=has_next_page,
            rejected_count=rejected_count,
            skipped_non_remote_count=0,
        )

    async def _fetch_content(
        self,
        client: httpx.AsyncClient,
        page: int,
    ) -> bytes:
        offset = (page - 1) * HIMALAYAS_PAGE_SIZE

        async def attempt() -> bytes:
            async with client.stream(
                "GET",
                HIMALAYAS_API_URL,
                params={
                    "limit": HIMALAYAS_PAGE_SIZE,
                    "offset": offset,
                },
                headers={
                    "Accept": "application/json",
                    "User-Agent": "RemoteMatch/0.1",
                },
                timeout=_REQUEST_TIMEOUT,
            ) as response:
                response.raise_for_status()

                chunks: list[bytes] = []
                total_size = 0

                async for chunk in response.aiter_bytes():
                    total_size += len(chunk)

                    if total_size > MAX_SOURCE_RESPONSE_BYTES:
                        raise HimalayasSourceError("Himalayas response exceeded the allowed size.")

                    chunks.append(chunk)

                return b"".join(chunks)

        try:
            return await retry_async(attempt, is_retryable=is_retryable_httpx_error)
        except httpx.HTTPError as error:
            raise HimalayasSourceError("Unable to fetch jobs from Himalayas.") from error

    @staticmethod
    def _to_ingestion_record(
        job: _HimalayasJob,
    ) -> JobIngestionRecord:
        description = html_to_plain_text(job.description)

        if not description:
            description = " ".join(job.excerpt.split())[:100_000]

        (
            location,
            remote_regions,
        ) = _normalize_locations(job.location_restrictions)

        (
            salary_minimum,
            salary_maximum,
            salary_currency,
        ) = _normalize_salary(
            job.min_salary,
            job.max_salary,
            job.salary_period,
            job.currency,
        )

        published_at = _timestamp_to_datetime(job.published_timestamp)

        expires_at = (
            _timestamp_to_datetime(job.expiry_timestamp)
            if job.expiry_timestamp is not None
            else None
        )

        if expires_at is not None and expires_at < published_at:
            expires_at = None

        skill_text = " ".join(
            (
                job.title,
                *job.categories,
                *job.parent_categories,
            )
        )

        return JobIngestionRecord(
            source_name=HIMALAYAS_SOURCE_NAME,
            source_job_id=(_build_source_job_id(job.guid)),
            source_url=job.application_link,
            application_url=(job.application_link),
            title=job.title,
            company_name=job.company_name,
            description=description,
            requirements=None,
            location=location,
            remote_regions=remote_regions,
            employment_type=(_normalize_employment_type(job.employment_type)),
            experience_level=(
                _normalize_experience_level(
                    job.seniority,
                    job.employment_type,
                )
            ),
            salary_min=salary_minimum,
            salary_max=salary_maximum,
            salary_currency=salary_currency,
            skills=extract_skills(skill_text),
            is_remote=True,
            published_at=published_at,
            expires_at=expires_at,
        )
