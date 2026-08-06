import re
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

JOBICY_SOURCE_NAME = "jobicy"
JOBICY_API_URL = "https://jobicy.com/api/v2/remote-jobs"
JOBICY_JOB_COUNT = 100
MAX_SOURCE_RESPONSE_BYTES = 20 * 1024 * 1024

_REQUEST_TIMEOUT = httpx.Timeout(
    connect=10.0,
    read=30.0,
    write=10.0,
    pool=10.0,
)

_SALARY_MULTIPLIERS = {
    "hourly": Decimal("2080"),
    "daily": Decimal("260"),
    "weekly": Decimal("52"),
    "monthly": Decimal("12"),
    "yearly": Decimal("1"),
    "annual": Decimal("1"),
}

_EMPLOYMENT_TYPE_MAP = {
    "full time": "full_time",
    "part time": "part_time",
    "contract": "contract",
    "contractor": "contract",
    "freelance": "freelance",
    "temporary": "temporary",
    "intern": "internship",
    "internship": "internship",
    "volunteer": "volunteer",
}


class JobicySourceError(JobSourceError):
    """Raised when Jobicy cannot be fetched or parsed."""


class _JobicyJob(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int = Field(ge=1)
    url: HttpUrl
    job_title: str = Field(
        alias="jobTitle",
        min_length=1,
        max_length=255,
    )
    company_name: str = Field(
        alias="companyName",
        min_length=1,
        max_length=255,
    )
    job_industry: list[str] = Field(
        default_factory=list,
        alias="jobIndustry",
        max_length=100,
    )
    job_type: list[str] = Field(
        default_factory=list,
        alias="jobType",
        max_length=20,
    )
    job_geo: str = Field(
        default="Anywhere",
        alias="jobGeo",
        max_length=500,
    )
    job_level: str | None = Field(
        default=None,
        alias="jobLevel",
        max_length=100,
    )
    job_excerpt: str = Field(
        default="",
        alias="jobExcerpt",
        max_length=100_000,
    )
    job_description: str = Field(
        alias="jobDescription",
        min_length=1,
        max_length=1_000_000,
    )
    published_at: datetime = Field(
        alias="pubDate",
    )
    salary_min: Decimal | None = Field(
        default=None,
        alias="salaryMin",
        ge=0,
    )
    salary_max: Decimal | None = Field(
        default=None,
        alias="salaryMax",
        ge=0,
    )
    salary_currency: str | None = Field(
        default=None,
        alias="salaryCurrency",
        min_length=3,
        max_length=3,
    )
    salary_period: str | None = Field(
        default=None,
        alias="salaryPeriod",
        max_length=30,
    )


class _JobicyPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    api_version: str = Field(
        alias="apiVersion",
        min_length=1,
        max_length=50,
    )
    job_count: int = Field(
        alias="jobCount",
        ge=0,
        le=JOBICY_JOB_COUNT,
    )
    jobs: list[dict[str, object]] = Field(
        max_length=JOBICY_JOB_COUNT,
    )


def _normalize_category(
    value: str,
) -> str:
    return re.sub(
        r"[\s_-]+",
        " ",
        value.strip().casefold(),
    )


def _normalize_employment_type(
    values: list[str],
) -> str | None:
    for value in values:
        normalized_value = _normalize_category(value)

        employment_type = _EMPLOYMENT_TYPE_MAP.get(normalized_value)

        if employment_type is not None:
            return employment_type

    return None


def _normalize_experience_level(
    value: str | None,
) -> str | None:
    if value is None:
        return None

    normalized_value = _normalize_category(value)

    mappings = (
        (
            (
                "executive",
                "director",
                "manager",
                "lead",
                "senior",
            ),
            "senior",
        ),
        (
            (
                "midweight",
                "mid level",
                "intermediate",
            ),
            "mid_level",
        ),
        (
            ("junior",),
            "junior",
        ),
        (
            ("entry",),
            "entry_level",
        ),
        (
            ("intern",),
            "internship",
        ),
        (
            ("no experience",),
            "no_experience",
        ),
    )

    for keywords, result in mappings:
        if any(keyword in normalized_value for keyword in keywords):
            return result

    return None


def _normalize_locations(
    value: str,
) -> tuple[str, list[str]]:
    cleaned_value = html_to_plain_text(value)

    if cleaned_value.casefold() in {
        "",
        "anywhere",
        "worldwide",
        "global",
    }:
        return "Worldwide", ["Worldwide"]

    regions: list[str] = []
    seen_regions: set[str] = set()

    for raw_region in cleaned_value.split(","):
        region = " ".join(raw_region.split())

        if not region:
            continue

        comparison_region = region.casefold()

        if comparison_region in seen_regions:
            continue

        if len(region) > 100:
            continue

        seen_regions.add(comparison_region)
        regions.append(region)

        if len(regions) == 20:
            break

    if not regions:
        return "Worldwide", ["Worldwide"]

    location = ", ".join(regions)

    if len(location) > 255:
        location = "Multiple remote regions"

    return location, regions


def _normalize_salary(
    minimum: Decimal | None,
    maximum: Decimal | None,
    currency: str | None,
    period: str | None,
) -> tuple[
    Decimal | None,
    Decimal | None,
    str | None,
]:
    if minimum is None and maximum is None:
        return None, None, None

    if currency is None or period is None:
        return None, None, None

    multiplier = _SALARY_MULTIPLIERS.get(period.strip().casefold())

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


def _normalize_published_at(
    value: datetime,
) -> datetime:
    if value.utcoffset() is None:
        return value.replace(tzinfo=UTC)

    return value.astimezone(UTC)


class JobicyJobSource:
    name = JOBICY_SOURCE_NAME
    max_pages = 1

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.client = client

    async def fetch_page(
        self,
        page: int = 1,
    ) -> JobSourceFetchResult:
        if page != 1:
            raise ValueError("Jobicy provides only page 1")

        if self.client is not None:
            content = await self._fetch_content(self.client)
        else:
            async with httpx.AsyncClient(
                follow_redirects=False,
            ) as client:
                content = await self._fetch_content(client)

        try:
            payload = _JobicyPayload.model_validate_json(content)
        except ValidationError as error:
            raise JobicySourceError("Jobicy returned an invalid response.") from error

        records: list[JobIngestionRecord] = []
        rejected_count = 0

        for raw_job in payload.jobs:
            try:
                job = _JobicyJob.model_validate(raw_job)
                record = self._to_ingestion_record(job)
            except (
                ValidationError,
                ValueError,
            ):
                rejected_count += 1
                continue

            records.append(record)

        return JobSourceFetchResult(
            records=tuple(records),
            page=1,
            has_next_page=False,
            rejected_count=rejected_count,
            skipped_non_remote_count=0,
        )

    async def _fetch_content(
        self,
        client: httpx.AsyncClient,
    ) -> bytes:
        async def attempt() -> bytes:
            async with client.stream(
                "GET",
                JOBICY_API_URL,
                params={
                    "count": JOBICY_JOB_COUNT,
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
                        raise JobicySourceError("Jobicy response exceeded the allowed size.")

                    chunks.append(chunk)

                return b"".join(chunks)

        try:
            return await retry_async(attempt, is_retryable=is_retryable_httpx_error)
        except httpx.HTTPError as error:
            raise JobicySourceError("Unable to fetch jobs from Jobicy.") from error

    @staticmethod
    def _to_ingestion_record(
        job: _JobicyJob,
    ) -> JobIngestionRecord:
        title = html_to_plain_text(job.job_title)
        company_name = html_to_plain_text(job.company_name)
        description = html_to_plain_text(job.job_description)

        if not description:
            description = html_to_plain_text(job.job_excerpt)

        location, remote_regions = _normalize_locations(job.job_geo)

        (
            salary_minimum,
            salary_maximum,
            salary_currency,
        ) = _normalize_salary(
            job.salary_min,
            job.salary_max,
            job.salary_currency,
            job.salary_period,
        )

        skill_text = " ".join(
            (
                title,
                *job.job_industry,
            )
        )

        return JobIngestionRecord(
            source_name=JOBICY_SOURCE_NAME,
            source_job_id=str(job.id),
            source_url=job.url,
            application_url=job.url,
            title=title,
            company_name=company_name,
            description=description,
            requirements=None,
            location=location,
            remote_regions=remote_regions,
            employment_type=(_normalize_employment_type(job.job_type)),
            experience_level=(_normalize_experience_level(job.job_level)),
            salary_min=salary_minimum,
            salary_max=salary_maximum,
            salary_currency=salary_currency,
            skills=extract_skills(skill_text),
            is_remote=True,
            published_at=(_normalize_published_at(job.published_at)),
            expires_at=None,
        )
