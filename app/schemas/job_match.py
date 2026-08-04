from pydantic import BaseModel, Field

from app.schemas.job import JobSummaryResponse


class JobMatchBreakdownResponse(BaseModel):
    skill_score: int = Field(ge=0, le=60)
    role_score: int = Field(ge=0, le=20)
    experience_score: int = Field(ge=0, le=10)
    salary_score: int = Field(ge=0, le=10)


class JobMatchResponse(BaseModel):
    job: JobSummaryResponse
    score: int = Field(ge=0, le=100)
    is_eligible: bool
    breakdown: JobMatchBreakdownResponse
    matched_skills: list[str]
    missing_skills: list[str]
    excluded_skills: list[str]
    reasons: list[str]


class JobMatchListResponse(BaseModel):
    items: list[JobMatchResponse]
    total: int
    minimum_score: int = Field(ge=0, le=100)
    limit: int
    offset: int
