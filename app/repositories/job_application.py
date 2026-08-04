from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.job import Job
from app.models.job_application import JobApplication


class JobApplicationRepository:
    def __init__(self, database: AsyncSession) -> None:
        self.database = database

    async def get_by_user_and_job(
        self,
        *,
        user_id: UUID,
        job_id: UUID,
    ) -> JobApplication | None:
        result = await self.database.execute(
            select(JobApplication).where(
                JobApplication.user_id == user_id,
                JobApplication.job_id == job_id,
            )
        )

        return result.scalar_one_or_none()

    async def get_with_job(
        self,
        *,
        user_id: UUID,
        application_id: UUID,
    ) -> tuple[JobApplication, Job] | None:
        result = await self.database.execute(
            select(
                JobApplication,
                Job,
            )
            .join(
                Job,
                Job.id == JobApplication.job_id,
            )
            .where(
                JobApplication.id == application_id,
                JobApplication.user_id == user_id,
            )
        )

        row = result.one_or_none()

        if row is None:
            return None

        return row[0], row[1]

    async def list_for_user(
        self,
        *,
        user_id: UUID,
        status: str | None,
        limit: int,
        offset: int,
    ) -> tuple[
        list[tuple[JobApplication, Job]],
        int,
    ]:
        filters = [
            JobApplication.user_id == user_id,
        ]

        if status is not None:
            filters.append(
                JobApplication.status == status,
            )

        result = await self.database.execute(
            select(
                JobApplication,
                Job,
            )
            .join(
                Job,
                Job.id == JobApplication.job_id,
            )
            .where(*filters)
            .order_by(
                JobApplication.updated_at.desc(),
                JobApplication.id.desc(),
            )
            .limit(limit)
            .offset(offset)
        )

        total = await self.database.scalar(
            select(func.count()).select_from(JobApplication).where(*filters)
        )

        return (
            [
                (
                    row[0],
                    row[1],
                )
                for row in result.all()
            ],
            int(total or 0),
        )

    async def create(
        self,
        values: dict[str, object],
    ) -> JobApplication:
        application = JobApplication(**values)
        self.database.add(application)

        return application

    @staticmethod
    def update(
        application: JobApplication,
        values: dict[str, object],
    ) -> JobApplication:
        for field_name, value in values.items():
            setattr(
                application,
                field_name,
                value,
            )

        return application

    async def delete(
        self,
        application: JobApplication,
    ) -> None:
        await self.database.delete(application)
