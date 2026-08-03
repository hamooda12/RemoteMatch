from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import cast

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.job import Job
from app.repositories.job import JobRepository
from app.schemas.job_ingestion import JobIngestionRecord
from app.services.job_normalizer import build_job_values


class JobIngestionAction(StrEnum):
    CREATED = "created"
    UPDATED = "updated"
    DUPLICATE = "duplicate"


class JobIngestionConflictError(Exception):
    """Raised when ingestion encounters conflicting identities."""


@dataclass(frozen=True, slots=True)
class JobIngestionResult:
    job: Job
    action: JobIngestionAction


class JobIngestionService:
    def __init__(self, database: AsyncSession) -> None:
        self.database = database
        self.jobs = JobRepository(database)

    async def ingest(
        self,
        record: JobIngestionRecord,
        *,
        observed_at: datetime | None = None,
    ) -> JobIngestionResult:
        values = build_job_values(
            record,
            observed_at=observed_at,
        )

        source_job = await self.jobs.get_by_source(
            record.source_name,
            record.source_job_id,
        )
        duplicate_job = await self.jobs.get_by_deduplication_key(
            cast(str, values["deduplication_key"])
        )

        if source_job is not None:
            if duplicate_job is not None and duplicate_job.id != source_job.id:
                raise JobIngestionConflictError(
                    "The source job conflicts with another canonical job."
                )

            self.jobs.update(source_job, values)
            await self._commit_or_raise(source_job)

            return JobIngestionResult(
                job=source_job,
                action=JobIngestionAction.UPDATED,
            )

        if duplicate_job is not None:
            self._merge_duplicate(
                duplicate_job,
                values,
            )
            await self._commit_or_raise(duplicate_job)

            return JobIngestionResult(
                job=duplicate_job,
                action=JobIngestionAction.DUPLICATE,
            )

        job = await self.jobs.create(values)

        try:
            await self.database.commit()
            await self.database.refresh(job)
        except IntegrityError as error:
            await self.database.rollback()

            return await self._recover_from_insert_race(
                record,
                values,
                error,
            )

        return JobIngestionResult(
            job=job,
            action=JobIngestionAction.CREATED,
        )

    async def _recover_from_insert_race(
        self,
        record: JobIngestionRecord,
        values: dict[str, object],
        original_error: IntegrityError,
    ) -> JobIngestionResult:
        source_job = await self.jobs.get_by_source(
            record.source_name,
            record.source_job_id,
        )

        if source_job is not None:
            duplicate_job = await self.jobs.get_by_deduplication_key(
                cast(
                    str,
                    values["deduplication_key"],
                )
            )

            if duplicate_job is not None and duplicate_job.id != source_job.id:
                raise JobIngestionConflictError(
                    "The source job conflicts with another canonical job."
                ) from original_error

            self.jobs.update(source_job, values)
            await self._commit_or_raise(source_job)

            return JobIngestionResult(
                job=source_job,
                action=JobIngestionAction.UPDATED,
            )

        duplicate_job = await self.jobs.get_by_deduplication_key(
            cast(
                str,
                values["deduplication_key"],
            )
        )

        if duplicate_job is None:
            raise JobIngestionConflictError(
                "Unable to resolve the ingestion conflict."
            ) from original_error

        self._merge_duplicate(
            duplicate_job,
            values,
        )
        await self._commit_or_raise(duplicate_job)

        return JobIngestionResult(
            job=duplicate_job,
            action=JobIngestionAction.DUPLICATE,
        )

    async def _commit_or_raise(self, job: Job) -> None:
        try:
            await self.database.commit()
            await self.database.refresh(job)
        except IntegrityError as error:
            await self.database.rollback()

            raise JobIngestionConflictError("Unable to persist the normalized job.") from error

    @classmethod
    def _merge_duplicate(
        cls,
        job: Job,
        values: dict[str, object],
    ) -> None:
        job.last_seen_at = cast(
            datetime,
            values["last_seen_at"],
        )
        job.is_active = True

        job.skills = cls._merge_string_lists(
            job.skills,
            cast(list[str], values["skills"]),
        )
        job.remote_regions = cls._merge_string_lists(
            job.remote_regions,
            cast(list[str], values["remote_regions"]),
        )

        optional_fields = (
            "application_url",
            "requirements",
            "location",
            "employment_type",
            "experience_level",
            "salary_min",
            "salary_max",
            "salary_currency",
            "published_at",
            "expires_at",
        )

        for field_name in optional_fields:
            current_value = getattr(job, field_name)
            incoming_value = values[field_name]

            if current_value is None and incoming_value is not None:
                setattr(job, field_name, incoming_value)

    @staticmethod
    def _merge_string_lists(
        existing_values: list[str],
        incoming_values: list[str],
    ) -> list[str]:
        merged_values = list(existing_values)
        seen_values = {value.casefold() for value in existing_values}

        for value in incoming_values:
            comparison_value = value.casefold()

            if comparison_value in seen_values:
                continue

            seen_values.add(comparison_value)
            merged_values.append(value)

        return merged_values
