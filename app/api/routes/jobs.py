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
from app.models.job import Job
from app.models.user import User
from app.schemas.job import (
    JobDetailResponse,
    JobListResponse,
    JobSummaryResponse,
)
from app.schemas.job_match import (
    JobMatchBreakdownResponse,
    JobMatchListResponse,
    JobMatchResponse,
)
from app.security.authentication import get_current_user
from app.services.job import JobNotFoundError, JobService
from app.services.job_matcher import JobMatchResult
from app.services.job_matching import (
    JobMatchingService,
    MatchingCVRequiredError,
    MatchingProfileRequiredError,
)

router = APIRouter(
    prefix="/jobs",
    tags=["Jobs"],
)

DatabaseSession = Annotated[AsyncSession, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]


def _build_job_match_response(
    job: Job,
    match: JobMatchResult,
) -> JobMatchResponse:
    return JobMatchResponse(
        job=JobSummaryResponse.model_validate(job),
        score=match.score,
        is_eligible=match.is_eligible,
        breakdown=JobMatchBreakdownResponse(
            skill_score=match.skill_score,
            role_score=match.role_score,
            experience_score=match.experience_score,
            salary_score=match.salary_score,
        ),
        matched_skills=list(match.matched_skills),
        missing_skills=list(match.missing_skills),
        excluded_skills=list(match.excluded_skills),
        reasons=list(match.reasons),
    )


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


@router.get(
    "/matches",
    response_model=JobMatchListResponse,
)
async def list_job_matches(
    response: Response,
    current_user: CurrentUser,
    database: DatabaseSession,
    minimum_score: Annotated[
        int,
        Query(ge=0, le=100),
    ] = 1,
    limit: Annotated[
        int,
        Query(ge=1, le=100),
    ] = 20,
    offset: Annotated[
        int,
        Query(ge=0, le=10_000),
    ] = 0,
) -> JobMatchListResponse:
    try:
        matches, total = await JobMatchingService(
            database,
        ).list_matches(
            user_id=current_user.id,
            minimum_score=minimum_score,
            limit=limit,
            offset=offset,
        )
    except MatchingProfileRequiredError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=("Complete your profile before requesting job matches."),
        ) from error
    except MatchingCVRequiredError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=("Upload and process your CV before requesting job matches."),
        ) from error

    response.headers["Cache-Control"] = "private, max-age=60"

    return JobMatchListResponse(
        items=[_build_job_match_response(job, match) for job, match in matches],
        total=total,
        minimum_score=minimum_score,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{job_id}/match",
    response_model=JobMatchResponse,
)
async def get_job_match(
    job_id: UUID,
    response: Response,
    current_user: CurrentUser,
    database: DatabaseSession,
) -> JobMatchResponse:
    try:
        job, match = await JobMatchingService(
            database,
        ).match_job(
            user_id=current_user.id,
            job_id=job_id,
        )
    except JobNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job not found.",
        ) from error
    except MatchingProfileRequiredError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=("Complete your profile before requesting job matches."),
        ) from error
    except MatchingCVRequiredError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=("Upload and process your CV before requesting job matches."),
        ) from error

    response.headers["Cache-Control"] = "private, max-age=60"

    return _build_job_match_response(
        job,
        match,
    )


@router.get(
    "/{job_id}",
    response_model=JobDetailResponse,
)
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
