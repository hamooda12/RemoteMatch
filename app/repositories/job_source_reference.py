from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.job_source_reference import JobSourceReference


class JobSourceReferenceRepository:
    def __init__(self, database: AsyncSession) -> None:
        self.database = database

    async def get_by_source(
        self,
        source_name: str,
        source_job_id: str,
    ) -> JobSourceReference | None:
        result = await self.database.execute(
            select(JobSourceReference)
            .where(
                JobSourceReference.source_name == source_name,
                JobSourceReference.source_job_id == source_job_id,
            )
            .options(selectinload(JobSourceReference.job))
        )
        return result.scalar_one_or_none()

    async def create(
        self,
        *,
        job_id: UUID,
        source_name: str,
        source_job_id: str,
        source_url: str,
        observed_at: datetime,
        sync_run_source_id: UUID | None = None,
    ) -> JobSourceReference:
        reference = JobSourceReference(
            job_id=job_id,
            source_name=source_name,
            source_job_id=source_job_id,
            source_url=source_url,
            first_seen_at=observed_at,
            last_seen_at=observed_at,
            last_seen_run_source_id=sync_run_source_id,
        )
        self.database.add(reference)
        return reference

    @staticmethod
    def touch(
        reference: JobSourceReference,
        *,
        source_url: str,
        observed_at: datetime,
        sync_run_source_id: UUID | None = None,
    ) -> JobSourceReference:
        reference.source_url = source_url
        reference.last_seen_at = observed_at

        if sync_run_source_id is not None:
            reference.last_seen_run_source_id = sync_run_source_id

        return reference
