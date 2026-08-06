from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.job_sources import (
    ARBEITNOW_SOURCE_NAME,
    JobSource,
    JobSourceError,
    build_job_source_registry,
)
from app.services.job_ingestion import (
    JobIngestionAction,
    JobIngestionConflictError,
    JobIngestionService,
)


class JobSyncError(Exception):
    """Raised when a job-source synchronization fails."""


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
    error: str | None = None


class JobSyncService:
    def __init__(
        self,
        database: AsyncSession,
        *,
        sources: Mapping[str, JobSource] | None = None,
        arbeitnow_source: JobSource | None = None,
    ) -> None:
        if sources is not None and arbeitnow_source is not None:
            raise ValueError("Provide either sources or arbeitnow_source, not both.")

        if sources is not None:
            self.sources = dict(sources)
        else:
            self.sources = build_job_source_registry()

            if arbeitnow_source is not None:
                self.sources[ARBEITNOW_SOURCE_NAME] = arbeitnow_source

        self.database = database
        self.ingestion = JobIngestionService(database)

    async def sync_source(
        self,
        source_name: str,
        *,
        max_pages: int = 1,
    ) -> JobSyncSummary:
        source = self.sources.get(source_name)

        if source is None:
            available_sources = ", ".join(sorted(self.sources))

            raise ValueError(
                f"Unknown job source '{source_name}'. Available sources: {available_sources}."
            )

        source_max_pages = getattr(
            source,
            "max_pages",
            5,
        )

        if max_pages < 1 or max_pages > source_max_pages:
            raise ValueError(
                f"max_pages must be between 1 and {source_max_pages} for {source_name}"
            )

        summary = JobSyncSummary(source_name=source_name)
        observed_at = datetime.now(UTC)

        for page in range(1, max_pages + 1):
            try:
                fetch_result = await source.fetch_page(page=page)
            except JobSourceError as error:
                raise JobSyncError(f"Unable to synchronize {source_name} page {page}.") from error

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

            if not fetch_result.has_next_page:
                break

        return summary

    async def sync_all(
        self,
        *,
        max_pages: int = 1,
    ) -> list[JobSyncSummary]:
        if max_pages < 1:
            raise ValueError("max_pages must be at least 1")

        summaries: list[JobSyncSummary] = []

        for source_name, source in self.sources.items():
            source_max_pages = getattr(
                source,
                "max_pages",
                max_pages,
            )
            pages_to_fetch = min(
                max_pages,
                source_max_pages,
            )

            try:
                summary = await self.sync_source(
                    source_name,
                    max_pages=pages_to_fetch,
                )
            except JobSyncError as error:
                summaries.append(
                    JobSyncSummary(
                        source_name=source_name,
                        error=str(error),
                    )
                )
                continue

            summaries.append(summary)

        return summaries

    async def sync_arbeitnow(
        self,
        *,
        max_pages: int = 1,
    ) -> JobSyncSummary:
        """Synchronize Arbeitnow for compatibility."""
        return await self.sync_source(
            ARBEITNOW_SOURCE_NAME,
            max_pages=max_pages,
        )
