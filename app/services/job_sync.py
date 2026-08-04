from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.job_sources.arbeitnow import (
    ARBEITNOW_SOURCE_NAME,
    ArbeitnowJobSource,
    ArbeitnowSourceError,
)
from app.services.job_ingestion import (
    JobIngestionAction,
    JobIngestionConflictError,
    JobIngestionService,
)


class JobSyncError(Exception):
    """Raised when a job source synchronization fails."""


@dataclass(slots=True)
class JobSyncSummary:
    source_name: str
    pages_fetched: int = 0
    fetched_records: int = 0
    created: int = 0
    updated: int = 0
    duplicates: int = 0
    conflicts: int = 0
    rejected: int = 0
    skipped_non_remote: int = 0


class JobSyncService:
    def __init__(
        self,
        database: AsyncSession,
        *,
        arbeitnow_source: ArbeitnowJobSource | None = None,
    ) -> None:
        self.database = database
        self.arbeitnow_source = arbeitnow_source or ArbeitnowJobSource()
        self.ingestion = JobIngestionService(database)

    async def sync_arbeitnow(
        self,
        *,
        max_pages: int = 1,
    ) -> JobSyncSummary:
        if max_pages < 1 or max_pages > 5:
            raise ValueError("max_pages must be between 1 and 5")

        summary = JobSyncSummary(
            source_name=ARBEITNOW_SOURCE_NAME,
        )
        observed_at = datetime.now(UTC)
        page = 1

        while page <= max_pages:
            try:
                fetch_result = await self.arbeitnow_source.fetch_page(page=page)
            except ArbeitnowSourceError as error:
                raise JobSyncError(f"Unable to synchronize Arbeitnow page {page}.") from error

            summary.pages_fetched += 1
            summary.fetched_records += len(fetch_result.records)
            summary.rejected += fetch_result.rejected_count
            summary.skipped_non_remote += fetch_result.skipped_non_remote_count

            for record in fetch_result.records:
                try:
                    ingestion_result = await self.ingestion.ingest(
                        record,
                        observed_at=observed_at,
                    )
                except JobIngestionConflictError:
                    summary.conflicts += 1
                    continue

                if ingestion_result.action == JobIngestionAction.CREATED:
                    summary.created += 1
                elif ingestion_result.action == JobIngestionAction.UPDATED:
                    summary.updated += 1
                else:
                    summary.duplicates += 1

            if not fetch_result.has_next_page or page >= max_pages:
                break

            page += 1

        return summary
