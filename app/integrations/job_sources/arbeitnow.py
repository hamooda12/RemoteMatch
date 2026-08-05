import html
import re
from datetime import UTC, datetime
from html.parser import HTMLParser

import httpx
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    ValidationError,
)

from app.integrations.job_sources.base import (
    JobSourceError,
    JobSourceFetchResult,
)
from app.schemas.job_ingestion import JobIngestionRecord
from app.services.cv_skill_extractor import extract_skills

ARBEITNOW_SOURCE_NAME = "arbeitnow"
ARBEITNOW_API_URL = "https://www.arbeitnow.com/api/job-board-api"
MAX_SOURCE_RESPONSE_BYTES = 20 * 1024 * 1024
MAX_DESCRIPTION_CHARACTERS = 100_000

_REQUEST_TIMEOUT = httpx.Timeout(
    connect=10.0,
    read=30.0,
    write=10.0,
    pool=10.0,
)


class ArbeitnowSourceError(JobSourceError):
    """Raised when Arbeitnow cannot be fetched or parsed."""


class _ArbeitnowJob(BaseModel):
    model_config = ConfigDict(extra="ignore")

    slug: str = Field(
        min_length=1,
        max_length=255,
    )
    company_name: str = Field(
        min_length=1,
        max_length=255,
    )
    title: str = Field(
        min_length=1,
        max_length=255,
    )
    description: str = Field(
        min_length=1,
        max_length=500_000,
    )
    remote: bool
    url: HttpUrl
    tags: list[str] = Field(
        default_factory=list,
    )
    job_types: list[str] = Field(
        default_factory=list,
    )
    location: str | None = None
    created_at: int = Field(
        ge=0,
        le=4_102_444_800,
    )


class _ArbeitnowLinks(BaseModel):
    model_config = ConfigDict(extra="ignore")

    next: HttpUrl | None = None


class _ArbeitnowPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    data: list[dict[str, object]]
    links: _ArbeitnowLinks


ArbeitnowFetchResult = JobSourceFetchResult


_BLOCK_TAGS = frozenset(
    {
        "article",
        "br",
        "div",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "li",
        "p",
        "section",
        "table",
        "td",
        "th",
        "tr",
        "ul",
        "ol",
    }
)

_IGNORED_TAGS = frozenset(
    {
        "script",
        "style",
    }
)


class _PlainTextHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(
            convert_charrefs=True,
        )
        self.parts: list[str] = []
        self.ignored_depth = 0

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        del attrs

        if tag in _IGNORED_TAGS:
            self.ignored_depth += 1
            return

        if self.ignored_depth == 0 and tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(
        self,
        tag: str,
    ) -> None:
        if tag in _IGNORED_TAGS:
            if self.ignored_depth > 0:
                self.ignored_depth -= 1

            return

        if self.ignored_depth == 0 and tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(
        self,
        data: str,
    ) -> None:
        if self.ignored_depth == 0:
            self.parts.append(data)

    def get_text(self) -> str:
        normalized_lines = [" ".join(line.split()) for line in "".join(self.parts).splitlines()]

        return "\n".join(line for line in normalized_lines if line)


def html_to_plain_text(
    value: str,
) -> str:
    decoded_value = value

    for _ in range(2):
        next_value = html.unescape(decoded_value)

        if next_value == decoded_value:
            break

        decoded_value = next_value

    parser = _PlainTextHTMLParser()
    parser.feed(decoded_value)
    parser.close()

    return parser.get_text()[:MAX_DESCRIPTION_CHARACTERS].rstrip()


def _classification_text(
    title: str,
    job_types: list[str],
) -> str:
    value = " ".join(
        (
            title,
            *job_types,
        )
    ).casefold()

    return re.sub(
        r"[_-]+",
        " ",
        value,
    )


def _normalize_employment_type(
    job_types: list[str],
) -> str | None:
    value = _classification_text(
        "",
        job_types,
    )

    mappings = (
        ("internship", "internship"),
        ("praktikum", "internship"),
        ("freelance", "freelance"),
        ("contract", "contract"),
        ("part time", "part_time"),
        ("parttime", "part_time"),
        ("full time", "full_time"),
        ("fulltime", "full_time"),
        ("permanent", "full_time"),
    )

    for (
        source_value,
        normalized_value,
    ) in mappings:
        if source_value in value:
            return normalized_value

    return None


def _normalize_experience_level(
    title: str,
    job_types: list[str],
) -> str | None:
    value = _classification_text(
        title,
        job_types,
    )

    mappings = (
        ("internship", "internship"),
        ("praktikum", "internship"),
        ("entry level", "entry_level"),
        ("graduate", "entry_level"),
        ("junior", "junior"),
        ("senior", "senior"),
        ("lead", "senior"),
        ("experienced", "mid_level"),
        ("berufserfahren", "mid_level"),
    )

    for (
        source_value,
        normalized_value,
    ) in mappings:
        if source_value in value:
            return normalized_value

    return None


class ArbeitnowJobSource:
    name = ARBEITNOW_SOURCE_NAME
    max_pages = 5

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.client = client

    async def fetch_page(
        self,
        page: int = 1,
    ) -> ArbeitnowFetchResult:
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
            payload = _ArbeitnowPayload.model_validate_json(content)
        except ValidationError as error:
            raise ArbeitnowSourceError("Arbeitnow returned an invalid response.") from error

        records: list[JobIngestionRecord] = []
        rejected_count = 0
        skipped_non_remote_count = 0

        for raw_job in payload.data:
            try:
                job = _ArbeitnowJob.model_validate(raw_job)
            except ValidationError:
                rejected_count += 1
                continue

            if not job.remote:
                skipped_non_remote_count += 1
                continue

            try:
                record = self._to_ingestion_record(job)
            except ValidationError:
                rejected_count += 1
                continue

            records.append(record)

        return ArbeitnowFetchResult(
            records=tuple(records),
            page=page,
            has_next_page=(payload.links.next is not None),
            rejected_count=rejected_count,
            skipped_non_remote_count=(skipped_non_remote_count),
        )

    async def _fetch_content(
        self,
        client: httpx.AsyncClient,
        page: int,
    ) -> bytes:
        try:
            async with client.stream(
                "GET",
                ARBEITNOW_API_URL,
                params={
                    "page": page,
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
                        raise ArbeitnowSourceError("Arbeitnow response exceeded the allowed size.")

                    chunks.append(chunk)

                return b"".join(chunks)
        except httpx.HTTPError as error:
            raise ArbeitnowSourceError("Unable to fetch jobs from Arbeitnow.") from error

    @staticmethod
    def _to_ingestion_record(
        job: _ArbeitnowJob,
    ) -> JobIngestionRecord:
        description = html_to_plain_text(job.description)

        location = " ".join(job.location.split()) if job.location else None

        return JobIngestionRecord(
            source_name=ARBEITNOW_SOURCE_NAME,
            source_job_id=job.slug,
            source_url=job.url,
            application_url=job.url,
            title=job.title,
            company_name=job.company_name,
            description=description,
            requirements=None,
            location=location,
            remote_regions=([location] if location is not None else []),
            employment_type=(_normalize_employment_type(job.job_types)),
            experience_level=(
                _normalize_experience_level(
                    job.title,
                    job.job_types,
                )
            ),
            salary_min=None,
            salary_max=None,
            salary_currency=None,
            skills=extract_skills(" ".join(job.tags)),
            is_remote=True,
            published_at=datetime.fromtimestamp(
                job.created_at,
                tz=UTC,
            ),
            expires_at=None,
        )
