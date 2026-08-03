from decimal import Decimal
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
from app.models.user import User
from app.schemas.job import (
    JobDetailResponse,
    JobListResponse,
    JobSummaryResponse,
)
from app.security.authentication import get_current_user
from app.services.job import JobNotFoundError, JobService

router = APIRouter(
    prefix="/jobs",
    tags=["Jobs"],
)

DatabaseSession = Annotated[AsyncSession, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]


@router.get("", response_model=JobListResponse)
async def list_jobs(
    response: Response,
    _current_user: CurrentUser,
    database: DatabaseSession,
    search: Annotated[
        str | None,
        Query(max_length=100),
    ] = None,
    skills: Annotated[
        list[str] | None,
        Query(),
    ] = None,
    remote_regions: Annotated[
        list[str] | None,
        Query(),
    ] = None,
    employment_type: Annotated[
        str | None,
        Query(max_length=50),
    ] = None,
    experience_level: Annotated[
        str | None,
        Query(max_length=50),
    ] = None,
    minimum_salary: Annotated[
        Decimal | None,
        Query(ge=0),
    ] = None,
    salary_currency: Annotated[
        str | None,
        Query(
            min_length=3,
            max_length=3,
            pattern=r"^[A-Za-z]{3}$",
        ),
    ] = None,
    limit: Annotated[
        int,
        Query(ge=1, le=100),
    ] = 20,
    offset: Annotated[
        int,
        Query(ge=0, le=10_000),
    ] = 0,
) -> JobListResponse:
    if minimum_salary is not None and salary_currency is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=("salary_currency is required when minimum_salary is provided."),
        )

    jobs, total = await JobService(database).list_jobs(
        search=search,
        skills=skills,
        remote_regions=remote_regions,
        employment_type=employment_type,
        experience_level=experience_level,
        minimum_salary=minimum_salary,
        salary_currency=salary_currency,
        limit=limit,
        offset=offset,
    )

    response.headers["Cache-Control"] = "private, max-age=60"

    return JobListResponse(
        items=[JobSummaryResponse.model_validate(job) for job in jobs],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{job_id}", response_model=JobDetailResponse)
async def get_job(
    job_id: UUID,
    response: Response,
    _current_user: CurrentUser,
    database: DatabaseSession,
) -> JobDetailResponse:
    try:
        job = await JobService(database).get_job(job_id)
    except JobNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job not found.",
        ) from error

    response.headers["Cache-Control"] = "private, max-age=60"

    return JobDetailResponse.model_validate(job)
