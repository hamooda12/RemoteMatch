from decimal import Decimal
from uuid import UUID

from sqlalchemy import String, func, or_, select
from sqlalchemy.dialects.postgresql import array
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.models.job import Job


class JobRepository:
    def __init__(self, database: AsyncSession) -> None:
        self.database = database

    async def get_active_by_id(
        self,
        job_id: UUID,
    ) -> Job | None:
        result = await self.database.execute(
            select(Job).where(
                Job.id == job_id,
                Job.is_active.is_(True),
            )
        )
        return result.scalar_one_or_none()

    async def get_by_source(
        self,
        source_name: str,
        source_job_id: str,
    ) -> Job | None:
        result = await self.database.execute(
            select(Job).where(
                Job.source_name == source_name,
                Job.source_job_id == source_job_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_by_deduplication_key(
        self,
        deduplication_key: str,
    ) -> Job | None:
        result = await self.database.execute(
            select(Job).where(
                Job.deduplication_key == deduplication_key,
            )
        )
        return result.scalar_one_or_none()

    async def list_active(
        self,
        *,
        search: str | None = None,
        skills: list[str] | None = None,
        remote_regions: list[str] | None = None,
        employment_type: str | None = None,
        experience_level: str | None = None,
        minimum_salary: Decimal | None = None,
        salary_currency: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[Job], int]:
        filters: list[ColumnElement[bool]] = [
            Job.is_active.is_(True),
        ]

        if search:
            escaped_search = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            search_pattern = f"%{escaped_search}%"

            filters.append(
                or_(
                    Job.title.ilike(search_pattern, escape="\\"),
                    Job.company_name.ilike(
                        search_pattern,
                        escape="\\",
                    ),
                    Job.description.ilike(
                        search_pattern,
                        escape="\\",
                    ),
                )
            )

        if skills:
            filters.append(
                Job.skills.op("?|")(
                    array(
                        skills,
                        type_=String(),
                    )
                )
            )

        if remote_regions:
            filters.append(
                Job.remote_regions.op("?|")(
                    array(
                        remote_regions,
                        type_=String(),
                    )
                )
            )

        if employment_type:
            filters.append(
                Job.employment_type == employment_type,
            )

        if experience_level:
            filters.append(
                Job.experience_level == experience_level,
            )

        if minimum_salary is not None:
            filters.append(
                or_(
                    Job.salary_max >= minimum_salary,
                    Job.salary_min >= minimum_salary,
                )
            )

        if salary_currency:
            filters.append(
                Job.salary_currency == salary_currency,
            )

        jobs_result = await self.database.scalars(
            select(Job)
            .where(*filters)
            .order_by(
                Job.published_at.desc().nullslast(),
                Job.first_seen_at.desc(),
                Job.id.desc(),
            )
            .limit(limit)
            .offset(offset)
        )

        total = await self.database.scalar(select(func.count()).select_from(Job).where(*filters))

        return list(jobs_result.all()), int(total or 0)

    async def create(
        self,
        values: dict[str, object],
    ) -> Job:
        job = Job(**values)
        self.database.add(job)
        return job

    @staticmethod
    def update(
        job: Job,
        values: dict[str, object],
    ) -> Job:
        for field_name, value in values.items():
            setattr(job, field_name, value)

        return job
