from datetime import datetime
from enum import StrEnum
from typing import Self
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from app.schemas.job import JobSummaryResponse


class ApplicationStatus(StrEnum):
    SAVED = "saved"
    APPLIED = "applied"
    INTERVIEW = "interview"
    OFFER = "offer"
    REJECTED = "rejected"


class JobApplicationCreateRequest(BaseModel):
    job_id: UUID
    status: ApplicationStatus = ApplicationStatus.SAVED
    notes: str | None = Field(
        default=None,
        max_length=2_000,
    )
    applied_at: datetime | None = None

    @field_validator("notes")
    @classmethod
    def normalize_notes(
        cls,
        value: str | None,
    ) -> str | None:
        if value is None:
            return None

        normalized_value = value.strip()

        return normalized_value or None

    @field_validator("applied_at")
    @classmethod
    def validate_applied_at(
        cls,
        value: datetime | None,
    ) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError(
                "applied_at must include a timezone",
            )

        return value

    @model_validator(mode="after")
    def validate_saved_application(self) -> Self:
        if self.status is ApplicationStatus.SAVED and self.applied_at is not None:
            raise ValueError(
                "A saved job cannot have an applied_at value",
            )

        return self


class JobApplicationUpdateRequest(BaseModel):
    status: ApplicationStatus | None = None
    notes: str | None = Field(
        default=None,
        max_length=2_000,
    )
    applied_at: datetime | None = None

    @field_validator("notes")
    @classmethod
    def normalize_notes(
        cls,
        value: str | None,
    ) -> str | None:
        if value is None:
            return None

        normalized_value = value.strip()

        return normalized_value or None

    @field_validator("applied_at")
    @classmethod
    def validate_applied_at(
        cls,
        value: datetime | None,
    ) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError(
                "applied_at must include a timezone",
            )

        return value

    @model_validator(mode="after")
    def validate_update(self) -> Self:
        if not self.model_fields_set:
            raise ValueError(
                "At least one application field is required",
            )

        if "status" in self.model_fields_set and self.status is None:
            raise ValueError(
                "status cannot be null",
            )

        if self.status is ApplicationStatus.SAVED and self.applied_at is not None:
            raise ValueError(
                "A saved job cannot have an applied_at value",
            )

        return self


class JobApplicationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    job_id: UUID
    status: ApplicationStatus
    notes: str | None
    applied_at: datetime | None
    status_changed_at: datetime
    created_at: datetime
    updated_at: datetime


class TrackedJobResponse(BaseModel):
    application: JobApplicationResponse
    job: JobSummaryResponse


class TrackedJobListResponse(BaseModel):
    items: list[TrackedJobResponse]
    total: int
    limit: int
    offset: int
