from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.job_sources import (
    ARBEITNOW_SOURCE_NAME,
    JobSource,
    JobSourceError,
    build_job_source_registry,
)
from app.repositories.job_sync_run import JobSyncRunRepository
from app.services.job_ingestion import (
    JobIngestionAction,
    JobIngestionConflictError,
    JobIngestionService,
)

_SOURCE_SYNC_FAILED_ERROR_CODE = "SOURCE_SYNC_FAILED"


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
    page_limit: int | None = None
    pagination_exhausted: bool | None = None
    error: str | None = None


class JobSyncError(Exception):
    """Raised when a job-source synchronization fails.

    Carries the JobSyncSummary accumulated for pages that completed
    successfully before the failure (i.e. NOT including the page whose
    fetch_page() raised), so callers can persist accurate partial-failure
    accounting instead of discarding all prior-page progress.
    """

    def __init__(
        self,
        message: str,
        *,
        partial_summary: JobSyncSummary | None = None,
    ) -> None:
        super().__init__(message)
        self.partial_summary = partial_summary


class JobSyncService:
    def __init__(
        self,
        database: AsyncSession,
        *,
        sources: Mapping[str, JobSource] | None = None,
        arbeitnow_source: JobSource | None = None,
        runs: JobSyncRunRepository | None = None,
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
        self.runs = runs if runs is not None else JobSyncRunRepository(database)

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

        run = await self.runs.create_run()
        await self.database.commit()
        run_id = run.id

        run_source = await self.runs.create_run_source(
            run_id,
            source_name,
        )
        await self.database.commit()

        run_source_id = run_source.id

        try:
            summary = await self._fetch_and_ingest_source(
                source,
                source_name,
                max_pages,
                run_source_id,
            )
        except JobSyncError as error:
            completed_at = datetime.now(UTC)
            partial_summary = error.partial_summary or JobSyncSummary(
                source_name=source_name,
                page_limit=max_pages,
                pagination_exhausted=False,
            )

            self.runs.complete_run_source(
                run_source,
                status="failed",
                completed_at=completed_at,
                error_code=_SOURCE_SYNC_FAILED_ERROR_CODE,
                error_message=str(error),
                pages_fetched=partial_summary.pages_fetched,
                fetched_records=partial_summary.fetched_records,
                created=partial_summary.created,
                updated=partial_summary.updated,
                duplicates=partial_summary.duplicates,
                conflicts=partial_summary.conflicts,
                rejected=partial_summary.rejected,
                skipped_non_remote=partial_summary.skipped_non_remote,
                page_limit=partial_summary.page_limit,
                pagination_exhausted=partial_summary.pagination_exhausted,
            )
            await self.database.commit()

            self.runs.complete_run(
                run,
                status="failed",
                completed_at=completed_at,
            )
            await self.database.commit()

            raise

        completed_at = datetime.now(UTC)

        self.runs.complete_run_source(
            run_source,
            status="succeeded",
            completed_at=completed_at,
            pages_fetched=summary.pages_fetched,
            fetched_records=summary.fetched_records,
            created=summary.created,
            updated=summary.updated,
            duplicates=summary.duplicates,
            conflicts=summary.conflicts,
            rejected=summary.rejected,
            skipped_non_remote=summary.skipped_non_remote,
            page_limit=summary.page_limit,
            pagination_exhausted=summary.pagination_exhausted,
        )
        await self.database.commit()

        self.runs.complete_run(
            run,
            status="succeeded",
            completed_at=completed_at,
        )
        await self.database.commit()

        return summary

    async def sync_all(
        self,
        *,
        max_pages: int = 1,
    ) -> list[JobSyncSummary]:
        if max_pages < 1:
            raise ValueError("max_pages must be at least 1")

        if not self.sources:
            raise ValueError("No job sources are enabled.")

        run = await self.runs.create_run()
        await self.database.commit()
        run_id = run.id

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

            run_source = await self.runs.create_run_source(
                run_id,
                source_name,
            )
            await self.database.commit()
            run_source_id = run_source.id

            try:
                summary = await self._fetch_and_ingest_source(
                    source,
                    source_name,
                    pages_to_fetch,
                    run_source_id,
                )
            except JobSyncError as error:
                completed_at = datetime.now(UTC)
                partial_summary = error.partial_summary or JobSyncSummary(
                    source_name=source_name,
                    page_limit=pages_to_fetch,
                    pagination_exhausted=False,
                )

                self.runs.complete_run_source(
                    run_source,
                    status="failed",
                    completed_at=completed_at,
                    error_code=_SOURCE_SYNC_FAILED_ERROR_CODE,
                    error_message=str(error),
                    pages_fetched=partial_summary.pages_fetched,
                    fetched_records=partial_summary.fetched_records,
                    created=partial_summary.created,
                    updated=partial_summary.updated,
                    duplicates=partial_summary.duplicates,
                    conflicts=partial_summary.conflicts,
                    rejected=partial_summary.rejected,
                    skipped_non_remote=partial_summary.skipped_non_remote,
                    page_limit=partial_summary.page_limit,
                    pagination_exhausted=partial_summary.pagination_exhausted,
                )
                await self.database.commit()

                partial_summary.error = str(error)
                summaries.append(partial_summary)
                continue

            completed_at = datetime.now(UTC)

            self.runs.complete_run_source(
                run_source,
                status="succeeded",
                completed_at=completed_at,
                pages_fetched=summary.pages_fetched,
                fetched_records=summary.fetched_records,
                created=summary.created,
                updated=summary.updated,
                duplicates=summary.duplicates,
                conflicts=summary.conflicts,
                rejected=summary.rejected,
                skipped_non_remote=summary.skipped_non_remote,
                page_limit=summary.page_limit,
                pagination_exhausted=summary.pagination_exhausted,
            )
            await self.database.commit()

            summaries.append(summary)

        if not summaries or all(summary.error is None for summary in summaries):
            overall_status = "succeeded"
        elif all(summary.error is not None for summary in summaries):
            overall_status = "failed"
        else:
            overall_status = "partial"

        self.runs.complete_run(
            run,
            status=overall_status,
            completed_at=datetime.now(UTC),
        )
        await self.database.commit()

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

    async def _fetch_and_ingest_source(
        self,
        source: JobSource,
        source_name: str,
        max_pages: int,
        run_source_id: UUID,
    ) -> JobSyncSummary:
        summary = JobSyncSummary(
            source_name=source_name,
            page_limit=max_pages,
            pagination_exhausted=False,
        )
        observed_at = datetime.now(UTC)

        for page in range(1, max_pages + 1):
            try:
                fetch_result = await source.fetch_page(page=page)
            except JobSourceError as error:
                raise JobSyncError(
                    f"Unable to synchronize {source_name} page {page}.",
                    partial_summary=summary,
                ) from error

            summary.pages_fetched += 1
            summary.fetched_records += len(fetch_result.records)
            summary.rejected += fetch_result.rejected_count
            summary.skipped_non_remote += fetch_result.skipped_non_remote_count

            for record in fetch_result.records:
                try:
                    ingestion_result = await self.ingestion.ingest(
                        record,
                        observed_at=observed_at,
                        sync_run_source_id=run_source_id,
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
                summary.pagination_exhausted = True
                break

        return summary
