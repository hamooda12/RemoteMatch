from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.job import Job
from app.repositories.cv_document import CVDocumentRepository
from app.repositories.job import JobRepository
from app.repositories.profile import ProfileRepository
from app.services.job import JobService
from app.services.job_matcher import (
    CandidateMatchContext,
    JobMatchResult,
    calculate_job_match,
)


class MatchingProfileRequiredError(Exception):
    """Raised when matching is requested without a profile."""


class MatchingCVRequiredError(Exception):
    """Raised when matching is requested without processed CV skills."""


class JobMatchingService:
    def __init__(self, database: AsyncSession) -> None:
        self.profiles = ProfileRepository(database)
        self.cv_documents = CVDocumentRepository(database)
        self.job_repository = JobRepository(database)
        self.jobs = JobService(database)

    async def build_candidate_context(
        self,
        user_id: UUID,
    ) -> CandidateMatchContext:
        profile = await self.profiles.get_by_user_id(user_id)

        if profile is None:
            raise MatchingProfileRequiredError

        cv_document = await self.cv_documents.get_with_extracted_skills(
            user_id,
        )

        if (
            cv_document is None
            or cv_document.parse_status != "processed"
            or cv_document.skills_extraction_version is None
        ):
            raise MatchingCVRequiredError

        return CandidateMatchContext(
            skills=tuple(cv_document.extracted_skills or []),
            target_roles=tuple(profile.target_roles or []),
            experience_level=profile.experience_level,
            minimum_salary=profile.minimum_salary,
            salary_currency=profile.salary_currency,
            excluded_technologies=tuple(
                profile.excluded_technologies or [],
            ),
        )

    @staticmethod
    def calculate_match(
        candidate: CandidateMatchContext,
        job: Job,
    ) -> JobMatchResult:
        return calculate_job_match(
            candidate=candidate,
            job_title=job.title,
            job_skills=tuple(job.skills or []),
            job_experience_level=job.experience_level,
            job_salary_min=job.salary_min,
            job_salary_max=job.salary_max,
            job_salary_currency=job.salary_currency,
        )

    async def match_job(
        self,
        *,
        user_id: UUID,
        job_id: UUID,
    ) -> tuple[Job, JobMatchResult]:
        job = await self.jobs.get_job(job_id)
        candidate = await self.build_candidate_context(user_id)

        return job, self.calculate_match(
            candidate,
            job,
        )

    async def list_matches(
        self,
        *,
        user_id: UUID,
        minimum_score: int,
        limit: int,
        offset: int,
    ) -> tuple[
        list[tuple[Job, JobMatchResult]],
        int,
    ]:
        candidate = await self.build_candidate_context(user_id)
        jobs = await self.job_repository.list_active_for_matching()

        matches: list[tuple[Job, JobMatchResult]] = []

        for job in jobs:
            match = self.calculate_match(
                candidate,
                job,
            )

            if not match.is_eligible:
                continue

            if match.score < minimum_score:
                continue

            matches.append(
                (
                    job,
                    match,
                )
            )

        matches.sort(
            key=lambda item: item[1].score,
            reverse=True,
        )

        total = len(matches)

        return (
            matches[offset : offset + limit],
            total,
        )
