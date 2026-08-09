from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.job_sync_run import JobSyncRun, JobSyncRunSource


class JobSyncRunRepository:
    def __init__(self, database: AsyncSession) -> None:
        self.database = database

    async def create_run(self) -> JobSyncRun:
        run = JobSyncRun()
        self.database.add(run)
        return run

    async def create_run_source(
        self,
        run_id: UUID,
        source_name: str,
    ) -> JobSyncRunSource:
        source = JobSyncRunSource(
            run_id=run_id,
            source_name=source_name,
        )
        self.database.add(source)
        return source

    @staticmethod
    def complete_run_source(
        source: JobSyncRunSource,
        *,
        status: str,
        completed_at: datetime,
        error_code: str | None = None,
        error_message: str | None = None,
        pages_fetched: int = 0,
        fetched_records: int = 0,
        created: int = 0,
        updated: int = 0,
        duplicates: int = 0,
        conflicts: int = 0,
        rejected: int = 0,
        skipped_non_remote: int = 0,
    ) -> JobSyncRunSource:
        source.status = status
        source.completed_at = completed_at
        source.error_code = error_code
        source.error_message = error_message
        source.pages_fetched = pages_fetched
        source.fetched_records = fetched_records
        source.created = created
        source.updated = updated
        source.duplicates = duplicates
        source.conflicts = conflicts
        source.rejected = rejected
        source.skipped_non_remote = skipped_non_remote

        return source

    @staticmethod
    def complete_run(
        run: JobSyncRun,
        *,
        status: str,
        completed_at: datetime,
    ) -> JobSyncRun:
        run.status = status
        run.completed_at = completed_at

        return run

    async def get_run_with_sources(
        self,
        run_id: UUID,
    ) -> JobSyncRun | None:
        result = await self.database.execute(
            select(JobSyncRun)
            .where(JobSyncRun.id == run_id)
            .options(selectinload(JobSyncRun.sources))
        )
        return result.scalar_one_or_none()

    async def delete_run(
        self,
        run: JobSyncRun,
    ) -> None:
        await self.database.delete(run)
