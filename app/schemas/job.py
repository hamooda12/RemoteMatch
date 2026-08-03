from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class JobSummaryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    company_name: str
    location: str | None
    remote_regions: list[str]
    employment_type: str | None
    experience_level: str | None
    salary_min: Decimal | None
    salary_max: Decimal | None
    salary_currency: str | None
    skills: list[str]
    is_remote: bool
    source_name: str
    source_url: str
    application_url: str | None
    published_at: datetime | None
    first_seen_at: datetime


class JobDetailResponse(JobSummaryResponse):
    description: str
    requirements: str | None
    expires_at: datetime | None
    last_seen_at: datetime


class JobListResponse(BaseModel):
    items: list[JobSummaryResponse]
    total: int
    limit: int
    offset: int
