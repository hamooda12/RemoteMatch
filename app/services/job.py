from decimal import Decimal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.job import Job
from app.repositories.job import JobRepository


class JobNotFoundError(Exception):
    """Raised when an active job cannot be found."""


class JobService:
    def __init__(self, database: AsyncSession) -> None:
        self.jobs = JobRepository(database)

    async def get_job(self, job_id: UUID) -> Job:
        job = await self.jobs.get_active_by_id(job_id)

        if job is None:
            raise JobNotFoundError

        return job

    async def list_jobs(
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
        normalized_search = self._normalize_search(search)
        normalized_skills = self._normalize_values(skills)
        normalized_regions = self._normalize_values(remote_regions)

        normalized_employment_type = self._normalize_optional_value(employment_type)
        normalized_experience_level = self._normalize_optional_value(experience_level)

        normalized_currency = salary_currency.upper() if salary_currency is not None else None

        return await self.jobs.list_active(
            search=normalized_search,
            skills=normalized_skills,
            remote_regions=normalized_regions,
            employment_type=normalized_employment_type,
            experience_level=normalized_experience_level,
            minimum_salary=minimum_salary,
            salary_currency=normalized_currency,
            limit=limit,
            offset=offset,
        )

    @staticmethod
    def _normalize_search(value: str | None) -> str | None:
        if value is None:
            return None

        normalized_value = " ".join(value.split())
        return normalized_value or None

    @staticmethod
    def _normalize_optional_value(
        value: str | None,
    ) -> str | None:
        if value is None:
            return None

        normalized_value = " ".join(value.split())
        return normalized_value or None

    @staticmethod
    def _normalize_values(
        values: list[str] | None,
    ) -> list[str] | None:
        if not values:
            return None

        normalized_values: list[str] = []
        seen_values: set[str] = set()

        for value in values:
            normalized_value = " ".join(value.split())

            if not normalized_value:
                continue

            comparison_value = normalized_value.casefold()

            if comparison_value in seen_values:
                continue

            seen_values.add(comparison_value)
            normalized_values.append(normalized_value)

        return normalized_values or None
