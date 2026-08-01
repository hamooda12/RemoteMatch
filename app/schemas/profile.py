from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Self
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


class ExperienceLevel(StrEnum):
    NO_EXPERIENCE = "no_experience"
    INTERNSHIP = "internship"
    ENTRY_LEVEL = "entry_level"
    JUNIOR = "junior"
    MID_LEVEL = "mid_level"
    SENIOR = "senior"


class ProfileUpsert(BaseModel):
    location: str | None = Field(
        default=None,
        max_length=120,
    )

    timezone: str = Field(
        default="Asia/Hebron",
        max_length=50,
    )

    target_roles: list[str] = Field(
        default_factory=list,
        max_length=20,
    )

    experience_level: ExperienceLevel | None = None

    minimum_salary: Decimal | None = Field(
        default=None,
        ge=0,
        max_digits=12,
        decimal_places=2,
    )

    salary_currency: str | None = Field(
        default=None,
        min_length=3,
        max_length=3,
    )

    excluded_technologies: list[str] = Field(
        default_factory=list,
        max_length=30,
    )

    availability: dict[str, str] = Field(
        default_factory=dict,
    )

    @field_validator("location")
    @classmethod
    def normalize_location(cls, value: str | None) -> str | None:
        if value is None:
            return None

        cleaned_value = " ".join(value.split())

        if not cleaned_value:
            return None

        return cleaned_value

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as error:
            raise ValueError("Unknown IANA timezone") from error

        return value

    @field_validator(
        "target_roles",
        "excluded_technologies",
    )
    @classmethod
    def normalize_string_list(cls, values: list[str]) -> list[str]:
        normalized_values: list[str] = []
        seen_values: set[str] = set()

        for value in values:
            cleaned_value = " ".join(value.split())

            if not cleaned_value:
                continue

            if len(cleaned_value) > 100:
                raise ValueError("List values cannot exceed 100 characters")

            comparison_value = cleaned_value.casefold()

            if comparison_value in seen_values:
                continue

            seen_values.add(comparison_value)
            normalized_values.append(cleaned_value)

        return normalized_values

    @field_validator("salary_currency")
    @classmethod
    def normalize_currency(cls, value: str | None) -> str | None:
        if value is None:
            return None

        return value.upper()

    @model_validator(mode="after")
    def validate_salary(self) -> Self:
        if self.minimum_salary is not None and self.salary_currency is None:
            raise ValueError("salary_currency is required when minimum_salary is provided")

        return self


class ProfileResponse(ProfileUpsert):
    model_config = ConfigDict(from_attributes=True)

    user_id: UUID
    created_at: datetime
    updated_at: datetime
