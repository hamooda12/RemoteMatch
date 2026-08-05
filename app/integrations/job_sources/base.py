from dataclasses import dataclass
from typing import Protocol

from app.services.job_ingestion import JobIngestionRecord


class JobSourceError(Exception):
    """Raised when a remote job source cannot be fetched or parsed."""


@dataclass(frozen=True, slots=True)
class JobSourceFetchResult:
    records: tuple[JobIngestionRecord, ...]
    page: int
    has_next_page: bool
    rejected_count: int = 0
    skipped_non_remote_count: int = 0


class JobSource(Protocol):
    name: str
    max_pages: int

    async def fetch_page(
        self,
        page: int = 1,
    ) -> JobSourceFetchResult:
        """Fetch and normalize one page of remote jobs."""
        ...
