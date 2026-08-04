from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.job import Job
from app.models.job_application import JobApplication
from app.repositories.job_application import (
    JobApplicationRepository,
)
from app.schemas.job_application import (
    ApplicationStatus,
    JobApplicationCreateRequest,
    JobApplicationUpdateRequest,
)
from app.services.job import JobService


class JobApplicationAlreadyExistsError(Exception):
    """Raised when a user already tracks a job."""


class JobApplicationNotFoundError(Exception):
    """Raised when a tracked application cannot be found."""


class InvalidJobApplicationStateError(Exception):
    """Raised when application timestamps conflict with its status."""


class JobApplicationService:
    def __init__(self, database: AsyncSession) -> None:
        self.database = database
        self.applications = JobApplicationRepository(database)
        self.jobs = JobService(database)

    async def create_application(
        self,
        *,
        user_id: UUID,
        request: JobApplicationCreateRequest,
    ) -> tuple[JobApplication, Job]:
        existing_application = await self.applications.get_by_user_and_job(
            user_id=user_id,
            job_id=request.job_id,
        )

        if existing_application is not None:
            raise JobApplicationAlreadyExistsError

        job = await self.jobs.get_job(request.job_id)
        current_time = datetime.now(UTC)

        applied_at = request.applied_at

        if request.status is not ApplicationStatus.SAVED and applied_at is None:
            applied_at = current_time

        application = await self.applications.create(
            {
                "user_id": user_id,
                "job_id": request.job_id,
                "status": request.status.value,
                "notes": request.notes,
                "applied_at": applied_at,
                "status_changed_at": current_time,
            }
        )

        try:
            await self.database.commit()
        except IntegrityError as error:
            await self.database.rollback()

            raise JobApplicationAlreadyExistsError from error

        await self.database.refresh(application)

        return application, job

    async def get_application(
        self,
        *,
        user_id: UUID,
        application_id: UUID,
    ) -> tuple[JobApplication, Job]:
        result = await self.applications.get_with_job(
            user_id=user_id,
            application_id=application_id,
        )

        if result is None:
            raise JobApplicationNotFoundError

        return result

    async def list_applications(
        self,
        *,
        user_id: UUID,
        status: ApplicationStatus | None,
        limit: int,
        offset: int,
    ) -> tuple[
        list[tuple[JobApplication, Job]],
        int,
    ]:
        return await self.applications.list_for_user(
            user_id=user_id,
            status=(status.value if status is not None else None),
            limit=limit,
            offset=offset,
        )

    async def update_application(
        self,
        *,
        user_id: UUID,
        application_id: UUID,
        request: JobApplicationUpdateRequest,
    ) -> tuple[JobApplication, Job]:
        application, job = await self.get_application(
            user_id=user_id,
            application_id=application_id,
        )

        current_time = datetime.now(UTC)
        values: dict[str, object] = {}

        if "notes" in request.model_fields_set:
            values["notes"] = request.notes

        effective_status = ApplicationStatus(
            application.status,
        )

        if request.status is not None:
            effective_status = request.status

            if request.status.value != application.status:
                values["status"] = request.status.value
                values["status_changed_at"] = current_time

        if effective_status is ApplicationStatus.SAVED:
            if request.applied_at is not None:
                raise InvalidJobApplicationStateError(
                    "A saved job cannot have an applied_at value.",
                )

            values["applied_at"] = None
        elif "applied_at" in request.model_fields_set:
            if request.applied_at is None:
                raise InvalidJobApplicationStateError(
                    "A submitted application requires applied_at.",
                )

            values["applied_at"] = request.applied_at
        elif application.applied_at is None:
            values["applied_at"] = current_time

        self.applications.update(
            application,
            values,
        )

        await self.database.commit()
        await self.database.refresh(application)

        return application, job

    async def delete_application(
        self,
        *,
        user_id: UUID,
        application_id: UUID,
    ) -> None:
        application, _job = await self.get_application(
            user_id=user_id,
            application_id=application_id,
        )

        await self.applications.delete(application)
        await self.database.commit()
