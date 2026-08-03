import re
from datetime import datetime
from decimal import Decimal
from typing import Literal, Self

from pydantic import (
    BaseModel,
    Field,
    HttpUrl,
    field_validator,
    model_validator,
)


class JobIngestionRecord(BaseModel):
    source_name: str = Field(max_length=100)
    source_job_id: str = Field(min_length=1, max_length=255)
    source_url: HttpUrl
    application_url: HttpUrl | None = None

    title: str = Field(min_length=1, max_length=255)
    company_name: str = Field(min_length=1, max_length=255)
    description: str = Field(min_length=1, max_length=100_000)
    requirements: str | None = Field(
        default=None,
        max_length=100_000,
    )

    location: str | None = Field(
        default=None,
        max_length=255,
    )
    remote_regions: list[str] = Field(
        default_factory=list,
        max_length=20,
    )

    employment_type: str | None = Field(
        default=None,
        max_length=50,
    )
    experience_level: str | None = Field(
        default=None,
        max_length=50,
    )

    salary_min: Decimal | None = Field(
        default=None,
        ge=0,
        max_digits=12,
        decimal_places=2,
    )
    salary_max: Decimal | None = Field(
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

    skills: list[str] = Field(
        default_factory=list,
        max_length=100,
    )

    is_remote: Literal[True] = True
    published_at: datetime | None = None
    expires_at: datetime | None = None

    @field_validator("source_name")
    @classmethod
    def normalize_source_name(cls, value: str) -> str:
        normalized_value = re.sub(
            r"[\s_]+",
            "-",
            value.strip().casefold(),
        )

        if not re.fullmatch(
            r"[a-z0-9][a-z0-9-]*",
            normalized_value,
        ):
            raise ValueError("source_name must be a valid source slug")

        return normalized_value

    @field_validator(
        "source_job_id",
        "title",
        "company_name",
    )
    @classmethod
    def normalize_required_text(cls, value: str) -> str:
        normalized_value = " ".join(value.split())

        if not normalized_value:
            raise ValueError("Value cannot be empty")

        return normalized_value

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str) -> str:
        normalized_lines = [" ".join(line.split()) for line in value.splitlines()]
        normalized_value = "\n".join(line for line in normalized_lines if line)

        if not normalized_value:
            raise ValueError("description cannot be empty")

        return normalized_value

    @field_validator("requirements")
    @classmethod
    def normalize_requirements(
        cls,
        value: str | None,
    ) -> str | None:
        if value is None:
            return None

        normalized_lines = [" ".join(line.split()) for line in value.splitlines()]
        normalized_value = "\n".join(line for line in normalized_lines if line)

        return normalized_value or None

    @field_validator("location")
    @classmethod
    def normalize_location(
        cls,
        value: str | None,
    ) -> str | None:
        if value is None:
            return None

        normalized_value = " ".join(value.split())
        return normalized_value or None

    @field_validator(
        "employment_type",
        "experience_level",
    )
    @classmethod
    def normalize_category(
        cls,
        value: str | None,
    ) -> str | None:
        if value is None:
            return None

        normalized_value = re.sub(
            r"[\s-]+",
            "_",
            value.strip().casefold(),
        )

        return normalized_value or None

    @field_validator(
        "remote_regions",
        "skills",
    )
    @classmethod
    def normalize_string_list(
        cls,
        values: list[str],
    ) -> list[str]:
        normalized_values: list[str] = []
        seen_values: set[str] = set()

        for value in values:
            normalized_value = " ".join(value.split())

            if not normalized_value:
                continue

            if len(normalized_value) > 100:
                raise ValueError("List values cannot exceed 100 characters")

            comparison_value = normalized_value.casefold()

            if comparison_value in seen_values:
                continue

            seen_values.add(comparison_value)
            normalized_values.append(normalized_value)

        return normalized_values

    @field_validator("salary_currency")
    @classmethod
    def normalize_currency(
        cls,
        value: str | None,
    ) -> str | None:
        if value is None:
            return None

        return value.upper()

    @field_validator(
        "published_at",
        "expires_at",
    )
    @classmethod
    def require_timezone(
        cls,
        value: datetime | None,
    ) -> datetime | None:
        if value is not None and value.utcoffset() is None:
            raise ValueError("Datetime values must include a timezone")

        return value

    @model_validator(mode="after")
    def validate_salary_and_dates(self) -> Self:
        has_salary = self.salary_min is not None or self.salary_max is not None

        if has_salary and self.salary_currency is None:
            raise ValueError("salary_currency is required when salary is provided")

        if (
            self.salary_min is not None
            and self.salary_max is not None
            and self.salary_min > self.salary_max
        ):
            raise ValueError("salary_min cannot exceed salary_max")

        if (
            self.published_at is not None
            and self.expires_at is not None
            and self.expires_at < self.published_at
        ):
            raise ValueError("expires_at cannot be earlier than published_at")

        return self
