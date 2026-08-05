import asyncio
import re
from datetime import UTC, datetime

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
from app.integrations.job_sources.greenhouse_boards import (
    GREENHOUSE_BOARDS,
    GreenhouseBoard,
)
from app.schemas.job_ingestion import JobIngestionRecord
from app.services.cv_skill_extractor import extract_skills

GREENHOUSE_SOURCE_NAME = "greenhouse"
GREENHOUSE_API_URL = "https://boards-api.greenhouse.io/v1/boards"
MAX_SOURCE_RESPONSE_BYTES = 25 * 1024 * 1024

_REQUEST_TIMEOUT = httpx.Timeout(
    connect=10.0,
    read=40.0,
    write=10.0,
    pool=10.0,
)

_REMOTE_PATTERN = re.compile(
    r"\b(remote|work[\s-]+from[\s-]+home|distributed)\b",
    flags=re.IGNORECASE,
)


class GreenhouseSourceError(JobSourceError):
    """Raised when a Greenhouse board cannot be fetched."""


class _GreenhouseLocation(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = Field(
        min_length=1,
        max_length=500,
    )


class _GreenhouseDepartment(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = Field(
        min_length=1,
        max_length=255,
    )


class _GreenhouseOffice(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = Field(
        min_length=1,
        max_length=255,
    )
    location: str | None = Field(
        default=None,
        max_length=500,
    )


class _GreenhouseJob(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int = Field(ge=1)
    title: str = Field(
        min_length=1,
        max_length=255,
    )
    updated_at: datetime
    location: _GreenhouseLocation
    absolute_url: HttpUrl
    content: str = Field(
        min_length=1,
        max_length=500_000,
    )
    departments: list[_GreenhouseDepartment] = Field(
        default_factory=list,
    )
    offices: list[_GreenhouseOffice] = Field(
        default_factory=list,
    )


class _GreenhousePayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    jobs: list[dict[str, object]]


def _normalize_location(
    value: str,
) -> tuple[str, list[str]]:
    location = " ".join(value.split())

    without_remote_prefix = re.sub(
        r"^remote\s*[-–—:/]*\s*",
        "",
        location,
        flags=re.IGNORECASE,
    ).strip()

    if not without_remote_prefix:
        return location, ["Worldwide"]

    if without_remote_prefix.casefold() in {
        "anywhere",
        "global",
        "worldwide",
    }:
        return location, ["Worldwide"]

    regions = [
        " ".join(region.split())
        for region in re.split(
            r"[,;|]",
            without_remote_prefix,
        )
        if region.strip() and region.strip().casefold() != "remote"
    ]

    return location, regions[:20] or ["Worldwide"]


def _normalize_employment_type(
    title: str,
    description: str,
) -> str | None:
    value = f"{title} {description[:2_000]}".casefold()
    value = re.sub(r"[_-]+", " ", value)

    mappings = (
        (r"\bintern(ship)?\b", "internship"),
        (r"\bfreelance\b", "freelance"),
        (r"\bcontract(or)?\b", "contract"),
        (r"\bpart\s*time\b", "part_time"),
        (r"\bfull\s*time\b", "full_time"),
        (r"\bpermanent\b", "full_time"),
    )

    for pattern, normalized_value in mappings:
        if re.search(pattern, value):
            return normalized_value

    return None


def _normalize_experience_level(
    title: str,
) -> str | None:
    value = re.sub(
        r"[_-]+",
        " ",
        title.casefold(),
    )

    mappings = (
        (r"\bintern(ship)?\b", "internship"),
        (
            r"\b(entry\s*level|graduate|new\s*grad)\b",
            "entry_level",
        ),
        (r"\bjunior\b", "junior"),
        (
            r"\b(mid\s*level|midlevel|midweight)\b",
            "mid_level",
        ),
        (
            r"\b(senior|staff|principal|lead)\b",
            "senior",
        ),
    )

    for pattern, normalized_value in mappings:
        if re.search(pattern, value):
            return normalized_value

    return None


def _is_remote_job(
    board: GreenhouseBoard,
    job: _GreenhouseJob,
    description: str,
) -> bool:
    if board.all_jobs_remote:
        return True

    searchable_values = [
        job.title,
        job.location.name,
        description[:5_000],
        *(office.name for office in job.offices),
        *(office.location for office in job.offices if office.location),
    ]

    return _REMOTE_PATTERN.search(" ".join(searchable_values)) is not None


def _normalize_datetime(
    value: datetime,
) -> datetime:
    if value.utcoffset() is None:
        return value.replace(tzinfo=UTC)

    return value.astimezone(UTC)


class GreenhouseJobSource:
    name = GREENHOUSE_SOURCE_NAME
    max_pages = 1

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        boards: tuple[
            GreenhouseBoard,
            ...,
        ] = GREENHOUSE_BOARDS,
    ) -> None:
        if not boards:
            raise ValueError("At least one Greenhouse board is required")

        self.client = client
        self.boards = boards

    async def fetch_page(
        self,
        page: int = 1,
    ) -> JobSourceFetchResult:
        if page != 1:
            raise ValueError("Greenhouse supports only page 1")

        if self.client is not None:
            contents = await self._fetch_all_boards(self.client)
        else:
            async with httpx.AsyncClient(
                follow_redirects=False,
            ) as client:
                contents = await self._fetch_all_boards(client)

        records: list[JobIngestionRecord] = []
        rejected_count = 0
        skipped_non_remote_count = 0

        for board, content in zip(
            self.boards,
            contents,
            strict=True,
        ):
            try:
                payload = _GreenhousePayload.model_validate_json(content)
            except ValidationError as error:
                raise GreenhouseSourceError(
                    f"{board.company_name} returned an invalid Greenhouse response."
                ) from error

            for raw_job in payload.jobs:
                try:
                    job = _GreenhouseJob.model_validate(raw_job)
                    description = html_to_plain_text(job.content)
                except ValidationError:
                    rejected_count += 1
                    continue

                if not description:
                    rejected_count += 1
                    continue

                if not _is_remote_job(
                    board,
                    job,
                    description,
                ):
                    skipped_non_remote_count += 1
                    continue

                try:
                    record = self._to_ingestion_record(
                        board,
                        job,
                        description,
                    )
                except ValidationError:
                    rejected_count += 1
                    continue

                records.append(record)

        return JobSourceFetchResult(
            records=tuple(records),
            page=1,
            has_next_page=False,
            rejected_count=rejected_count,
            skipped_non_remote_count=(skipped_non_remote_count),
        )

    async def _fetch_all_boards(
        self,
        client: httpx.AsyncClient,
    ) -> tuple[bytes, ...]:
        contents = await asyncio.gather(
            *(
                self._fetch_board_content(
                    client,
                    board,
                )
                for board in self.boards
            )
        )

        return tuple(contents)

    async def _fetch_board_content(
        self,
        client: httpx.AsyncClient,
        board: GreenhouseBoard,
    ) -> bytes:
        if not re.fullmatch(
            r"[a-zA-Z0-9][a-zA-Z0-9_-]*",
            board.token,
        ):
            raise GreenhouseSourceError("Invalid Greenhouse board token.")

        url = f"{GREENHOUSE_API_URL}/{board.token}/jobs"

        try:
            async with client.stream(
                "GET",
                url,
                params={
                    "content": "true",
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
                        raise GreenhouseSourceError(
                            f"{board.company_name} Greenhouse response exceeded the allowed size."
                        )

                    chunks.append(chunk)

                return b"".join(chunks)
        except httpx.HTTPError as error:
            raise GreenhouseSourceError(
                f"Unable to fetch the {board.company_name} Greenhouse board."
            ) from error

    @staticmethod
    def _to_ingestion_record(
        board: GreenhouseBoard,
        job: _GreenhouseJob,
        description: str,
    ) -> JobIngestionRecord:
        location, remote_regions = _normalize_location(job.location.name)

        classification_text = " ".join(
            (
                job.title,
                description,
                *(department.name for department in job.departments),
            )
        )

        return JobIngestionRecord(
            source_name=GREENHOUSE_SOURCE_NAME,
            source_job_id=(f"{board.token}:{job.id}"),
            source_url=job.absolute_url,
            application_url=job.absolute_url,
            title=job.title,
            company_name=board.company_name,
            description=description,
            requirements=None,
            location=location,
            remote_regions=remote_regions,
            employment_type=(
                _normalize_employment_type(
                    job.title,
                    description,
                )
            ),
            experience_level=(_normalize_experience_level(job.title)),
            salary_min=None,
            salary_max=None,
            salary_currency=None,
            skills=extract_skills(classification_text),
            is_remote=True,
            published_at=_normalize_datetime(job.updated_at),
            expires_at=None,
        )
