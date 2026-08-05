import json
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
from app.schemas.job_ingestion import JobIngestionRecord
from app.services.cv_skill_extractor import extract_skills

REMOTEOK_SOURCE_NAME = "remoteok"
REMOTEOK_API_URL = "https://remoteok.com/api"
MAX_SOURCE_RESPONSE_BYTES = 25 * 1024 * 1024

_REQUEST_TIMEOUT = httpx.Timeout(
    connect=10.0,
    read=40.0,
    write=10.0,
    pool=10.0,
)


class RemoteOKSourceError(JobSourceError):
    """Raised when Remote OK cannot be fetched or parsed."""


class _RemoteOKJob(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int | str
    epoch: int | None = Field(
        default=None,
        ge=0,
        le=4_102_444_800,
    )
    date: datetime | None = None

    company: str = Field(
        min_length=1,
        max_length=255,
    )
    position: str = Field(
        min_length=1,
        max_length=255,
    )
    description: str = Field(
        min_length=1,
        max_length=500_000,
    )

    location: str | None = Field(
        default=None,
        max_length=500,
    )
    tags: list[str] = Field(default_factory=list)

    url: HttpUrl

    salary_min: Decimal | None = Field(
        default=None,
        ge=0,
    )
    salary_max: Decimal | None = Field(
        default=None,
        ge=0,
    )


def _classification_text(
    title: str,
    tags: list[str],
) -> str:
    value = " ".join(
        (
            title,
            *tags,
        )
    ).casefold()

    return re.sub(
        r"[_-]+",
        " ",
        value,
    )


def _normalize_employment_type(
    title: str,
    tags: list[str],
) -> str | None:
    value = _classification_text(title, tags)

    mappings = (
        ("internship", "internship"),
        ("intern", "internship"),
        ("freelance", "freelance"),
        ("contractor", "contract"),
        ("contract", "contract"),
        ("part time", "part_time"),
        ("parttime", "part_time"),
        ("full time", "full_time"),
        ("fulltime", "full_time"),
        ("permanent", "full_time"),
    )

    for source_value, normalized_value in mappings:
        if source_value in value:
            return normalized_value

    return None


def _normalize_experience_level(
    title: str,
    tags: list[str],
) -> str | None:
    value = _classification_text(title, tags)

    mappings = (
        ("internship", "internship"),
        ("intern", "internship"),
        ("entry level", "entry_level"),
        ("entrylevel", "entry_level"),
        ("graduate", "entry_level"),
        ("junior", "junior"),
        ("mid level", "mid_level"),
        ("midlevel", "mid_level"),
        ("midweight", "mid_level"),
        ("senior", "senior"),
        ("staff", "senior"),
        ("principal", "senior"),
        ("lead", "senior"),
    )

    for source_value, normalized_value in mappings:
        if source_value in value:
            return normalized_value

    return None


def _normalize_location(
    value: str | None,
) -> tuple[str | None, list[str]]:
    if value is None:
        return None, []

    location = " ".join(value.split())

    if not location:
        return None, []

    if location.casefold() in {
        "anywhere",
        "global",
        "remote",
        "worldwide",
    }:
        return "Worldwide", ["Worldwide"]

    regions = [" ".join(region.split()) for region in location.split(",") if region.strip()]

    return location, regions[:20]


def _normalize_salary(
    minimum: Decimal | None,
    maximum: Decimal | None,
) -> tuple[
    Decimal | None,
    Decimal | None,
    str | None,
]:
    normalized_minimum = minimum if minimum is not None and minimum > 0 else None
    normalized_maximum = maximum if maximum is not None and maximum > 0 else None

    if (
        normalized_minimum is not None
        and normalized_maximum is not None
        and normalized_minimum > normalized_maximum
    ):
        normalized_minimum, normalized_maximum = (
            normalized_maximum,
            normalized_minimum,
        )

    currency = "USD" if normalized_minimum is not None or normalized_maximum is not None else None

    return (
        normalized_minimum,
        normalized_maximum,
        currency,
    )


def _published_at(
    job: _RemoteOKJob,
) -> datetime | None:
    if job.date is not None:
        if job.date.utcoffset() is None:
            return job.date.replace(tzinfo=UTC)

        return job.date.astimezone(UTC)

    if job.epoch is not None:
        return datetime.fromtimestamp(
            job.epoch,
            tz=UTC,
        )

    return None


class RemoteOKJobSource:
    name = REMOTEOK_SOURCE_NAME
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
            raise ValueError("Remote OK supports only page 1")

        if self.client is not None:
            content = await self._fetch_content(
                self.client,
            )
        else:
            async with httpx.AsyncClient(
                follow_redirects=False,
            ) as client:
                content = await self._fetch_content(client)

        try:
            payload = json.loads(content)
        except (
            json.JSONDecodeError,
            UnicodeDecodeError,
        ) as error:
            raise RemoteOKSourceError("Remote OK returned invalid JSON.") from error

        if not isinstance(payload, list):
            raise RemoteOKSourceError("Remote OK returned an invalid response.")

        records: list[JobIngestionRecord] = []
        rejected_count = 0

        for raw_job in payload:
            if isinstance(raw_job, dict) and "legal" in raw_job and "id" not in raw_job:
                continue

            if not isinstance(raw_job, dict):
                rejected_count += 1
                continue

            try:
                job = _RemoteOKJob.model_validate(raw_job)
                record = self._to_ingestion_record(job)
            except ValidationError:
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
        try:
            async with client.stream(
                "GET",
                REMOTEOK_API_URL,
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
                        raise RemoteOKSourceError("Remote OK response exceeded the allowed size.")

                    chunks.append(chunk)

                return b"".join(chunks)
        except httpx.HTTPError as error:
            raise RemoteOKSourceError("Unable to fetch jobs from Remote OK.") from error

    @staticmethod
    def _to_ingestion_record(
        job: _RemoteOKJob,
    ) -> JobIngestionRecord:
        description = html_to_plain_text(job.description)
        location, remote_regions = _normalize_location(job.location)
        salary_min, salary_max, salary_currency = _normalize_salary(
            job.salary_min,
            job.salary_max,
        )

        source_url = job.url

        return JobIngestionRecord(
            source_name=REMOTEOK_SOURCE_NAME,
            source_job_id=str(job.id),
            source_url=source_url,
            application_url=source_url,
            title=job.position,
            company_name=job.company,
            description=description,
            requirements=None,
            location=location,
            remote_regions=remote_regions,
            employment_type=_normalize_employment_type(
                job.position,
                job.tags,
            ),
            experience_level=_normalize_experience_level(
                job.position,
                job.tags,
            ),
            salary_min=salary_min,
            salary_max=salary_max,
            salary_currency=salary_currency,
            skills=extract_skills(" ".join(job.tags)),
            is_remote=True,
            published_at=_published_at(job),
            expires_at=None,
        )
