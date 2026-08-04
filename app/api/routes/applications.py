from typing import Annotated
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    Response,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.job import Job
from app.models.job_application import JobApplication
from app.models.user import User
from app.schemas.job import JobSummaryResponse
from app.schemas.job_application import (
    ApplicationStatus,
    JobApplicationCreateRequest,
    JobApplicationResponse,
    JobApplicationUpdateRequest,
    TrackedJobListResponse,
    TrackedJobResponse,
)
from app.security.authentication import get_current_user
from app.security.csrf import verify_csrf_token
from app.services.job import JobNotFoundError
from app.services.job_application import (
    InvalidJobApplicationStateError,
    JobApplicationAlreadyExistsError,
    JobApplicationNotFoundError,
    JobApplicationService,
)

router = APIRouter(
    prefix="/applications",
    tags=["Applications"],
)

DatabaseSession = Annotated[AsyncSession, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]
CsrfProtection = Annotated[None, Depends(verify_csrf_token)]


def _build_tracked_job_response(
    application: JobApplication,
    job: Job,
) -> TrackedJobResponse:
    return TrackedJobResponse(
        application=JobApplicationResponse.model_validate(
            application,
        ),
        job=JobSummaryResponse.model_validate(job),
    )


@router.post(
    "",
    response_model=TrackedJobResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_application(
    request: JobApplicationCreateRequest,
    response: Response,
    current_user: CurrentUser,
    database: DatabaseSession,
    _csrf: CsrfProtection,
) -> TrackedJobResponse:
    try:
        application, job = await JobApplicationService(
            database,
        ).create_application(
            user_id=current_user.id,
            request=request,
        )
    except JobNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job not found.",
        ) from error
    except JobApplicationAlreadyExistsError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This job is already being tracked.",
        ) from error

    response.headers["Cache-Control"] = "private, no-store"

    return _build_tracked_job_response(
        application,
        job,
    )


@router.get(
    "",
    response_model=TrackedJobListResponse,
)
async def list_applications(
    response: Response,
    current_user: CurrentUser,
    database: DatabaseSession,
    application_status: Annotated[
        ApplicationStatus | None,
        Query(alias="status"),
    ] = None,
    limit: Annotated[
        int,
        Query(ge=1, le=100),
    ] = 20,
    offset: Annotated[
        int,
        Query(ge=0, le=10_000),
    ] = 0,
) -> TrackedJobListResponse:
    applications, total = await JobApplicationService(
        database,
    ).list_applications(
        user_id=current_user.id,
        status=application_status,
        limit=limit,
        offset=offset,
    )

    response.headers["Cache-Control"] = "private, no-store"

    return TrackedJobListResponse(
        items=[
            _build_tracked_job_response(
                application,
                job,
            )
            for application, job in applications
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{application_id}",
    response_model=TrackedJobResponse,
)
async def get_application(
    application_id: UUID,
    response: Response,
    current_user: CurrentUser,
    database: DatabaseSession,
) -> TrackedJobResponse:
    try:
        application, job = await JobApplicationService(
            database,
        ).get_application(
            user_id=current_user.id,
            application_id=application_id,
        )
    except JobApplicationNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Application not found.",
        ) from error

    response.headers["Cache-Control"] = "private, no-store"

    return _build_tracked_job_response(
        application,
        job,
    )


@router.patch(
    "/{application_id}",
    response_model=TrackedJobResponse,
)
async def update_application(
    application_id: UUID,
    request: JobApplicationUpdateRequest,
    response: Response,
    current_user: CurrentUser,
    database: DatabaseSession,
    _csrf: CsrfProtection,
) -> TrackedJobResponse:
    try:
        application, job = await JobApplicationService(
            database,
        ).update_application(
            user_id=current_user.id,
            application_id=application_id,
            request=request,
        )
    except JobApplicationNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Application not found.",
        ) from error
    except InvalidJobApplicationStateError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(error),
        ) from error

    response.headers["Cache-Control"] = "private, no-store"

    return _build_tracked_job_response(
        application,
        job,
    )


@router.delete(
    "/{application_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_application(
    application_id: UUID,
    current_user: CurrentUser,
    database: DatabaseSession,
    _csrf: CsrfProtection,
) -> Response:
    try:
        await JobApplicationService(
            database,
        ).delete_application(
            user_id=current_user.id,
            application_id=application_id,
        )
    except JobApplicationNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Application not found.",
        ) from error

    return Response(
        status_code=status.HTTP_204_NO_CONTENT,
        headers={
            "Cache-Control": "private, no-store",
        },
    )
