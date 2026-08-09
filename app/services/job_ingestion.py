from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import cast

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.job import Job
from app.models.job_source_reference import JobSourceReference
from app.repositories.job import JobRepository
from app.repositories.job_source_reference import JobSourceReferenceRepository
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
        self.source_references = JobSourceReferenceRepository(database)

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

        existing_reference = await self.source_references.get_by_source(
            record.source_name,
            record.source_job_id,
        )
        duplicate_job = await self.jobs.get_by_deduplication_key(
            cast(str, values["deduplication_key"])
        )

        if existing_reference is not None:
            job = existing_reference.job

            if duplicate_job is not None and duplicate_job.id != job.id:
                raise JobIngestionConflictError(
                    "The source job conflicts with another canonical job."
                )

            self._record_existing_reference_observation(
                existing_reference,
                record,
                values,
            )
            await self._commit_or_raise(job)

            return JobIngestionResult(
                job=job,
                action=JobIngestionAction.UPDATED,
            )

        if duplicate_job is not None:
            self._merge_secondary_observation(
                duplicate_job,
                values,
            )
            await self._create_reference(duplicate_job, record, values)

            try:
                await self.database.commit()
                await self.database.refresh(duplicate_job)
            except IntegrityError as error:
                await self.database.rollback()

                return await self._recover_from_insert_race(
                    record,
                    values,
                    error,
                )

            return JobIngestionResult(
                job=duplicate_job,
                action=JobIngestionAction.DUPLICATE,
            )

        job = await self.jobs.create(values)

        try:
            await self.database.flush()
        except IntegrityError as error:
            await self.database.rollback()

            return await self._recover_from_insert_race(
                record,
                values,
                error,
            )

        await self._create_reference(job, record, values)

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
        existing_reference = await self.source_references.get_by_source(
            record.source_name,
            record.source_job_id,
        )
        duplicate_job = await self.jobs.get_by_deduplication_key(
            cast(
                str,
                values["deduplication_key"],
            )
        )

        if existing_reference is not None:
            job = existing_reference.job

            if duplicate_job is not None and duplicate_job.id != job.id:
                raise JobIngestionConflictError(
                    "The source job conflicts with another canonical job."
                ) from original_error

            self._record_existing_reference_observation(
                existing_reference,
                record,
                values,
            )
            await self._commit_or_raise(job)

            return JobIngestionResult(
                job=job,
                action=JobIngestionAction.UPDATED,
            )

        if duplicate_job is None:
            raise JobIngestionConflictError(
                "Unable to resolve the ingestion conflict."
            ) from original_error

        self._merge_secondary_observation(
            duplicate_job,
            values,
        )
        await self._create_reference(duplicate_job, record, values)
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

    @staticmethod
    def _is_legacy_source(
        job: Job,
        record: JobIngestionRecord,
    ) -> bool:
        """Whether `record` is the source currently cached in Job's legacy
        source_name/source_job_id fields (not an authoritative identity
        check -- JobSourceReference is authoritative; this only decides
        whether a full overwrite or a backfill-only merge is safe)."""
        return job.source_name == record.source_name and job.source_job_id == record.source_job_id

    def _record_existing_reference_observation(
        self,
        existing_reference: JobSourceReference,
        record: JobIngestionRecord,
        values: dict[str, object],
    ) -> Job:
        job = existing_reference.job

        if self._is_legacy_source(job, record):
            self._apply_legacy_source_update(job, values)
        else:
            self._merge_secondary_observation(job, values)

        self.source_references.touch(
            existing_reference,
            source_url=cast(str, values["source_url"]),
            observed_at=cast(datetime, values["last_seen_at"]),
        )

        return job

    async def _create_reference(
        self,
        job: Job,
        record: JobIngestionRecord,
        values: dict[str, object],
    ) -> None:
        await self.source_references.create(
            job_id=job.id,
            source_name=record.source_name,
            source_job_id=record.source_job_id,
            source_url=cast(str, values["source_url"]),
            observed_at=cast(datetime, values["last_seen_at"]),
        )

    # Scalar enrichment fields: a "current state" value with one source of
    # truth at a time. Secondary observations only backfill from None (see
    # _backfill_scalar_fields); the legacy/authoritative source may update
    # them non-destructively (see _update_scalar_fields_non_destructively)
    # since it -- not a secondary source -- is authoritative for its own
    # posting's current details.
    _ENRICHMENT_SCALAR_FIELDS: tuple[str, ...] = (
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
    # Collection enrichment fields: always accumulate from any source,
    # regardless of observer -- see _merge_collection_fields.
    _ENRICHMENT_LIST_FIELDS: tuple[str, ...] = (
        "skills",
        "remote_regions",
    )

    def _apply_legacy_source_update(
        self,
        job: Job,
        values: dict[str, object],
    ) -> None:
        """Full-overwrite for core/source-owned fields (title, company,
        description, identity/timestamp fields, ...); enrichment fields use
        non-destructive rules so a legacy-source re-sync can both (a) still
        legitimately update its own current details (a changed application
        URL, salary, location, or extended expiry) and (b) never erase
        enrichment another source already contributed by sending None."""
        enrichment_field_names = {
            *self._ENRICHMENT_SCALAR_FIELDS,
            *self._ENRICHMENT_LIST_FIELDS,
        }
        core_values = {
            field_name: value
            for field_name, value in values.items()
            if field_name not in enrichment_field_names
        }

        self.jobs.update(job, core_values)
        self._merge_collection_fields(job, values)
        self._update_scalar_fields_non_destructively(job, values)

    @classmethod
    def _merge_secondary_observation(
        cls,
        job: Job,
        values: dict[str, object],
    ) -> None:
        job.last_seen_at = cast(
            datetime,
            values["last_seen_at"],
        )
        job.is_active = True

        cls._merge_collection_fields(job, values)
        cls._backfill_scalar_fields(job, values)

    @classmethod
    def _merge_collection_fields(
        cls,
        job: Job,
        values: dict[str, object],
    ) -> None:
        job.skills = cls._merge_string_lists(
            job.skills,
            cast(list[str], values["skills"]),
        )
        job.remote_regions = cls._merge_string_lists(
            job.remote_regions,
            cast(list[str], values["remote_regions"]),
        )

    @classmethod
    def _backfill_scalar_fields(
        cls,
        job: Job,
        values: dict[str, object],
    ) -> None:
        """Secondary-observation rule: only fill a currently-empty field.
        Never overwrites an existing value, never erases with None."""
        for field_name in cls._ENRICHMENT_SCALAR_FIELDS:
            current_value = getattr(job, field_name)
            incoming_value = values[field_name]

            if current_value is None and incoming_value is not None:
                setattr(job, field_name, incoming_value)

    @classmethod
    def _update_scalar_fields_non_destructively(
        cls,
        job: Job,
        values: dict[str, object],
    ) -> None:
        """Legacy-source rule: any non-null incoming value replaces the
        current one (even if already set), but an incoming None never
        erases an existing value."""
        for field_name in cls._ENRICHMENT_SCALAR_FIELDS:
            incoming_value = values[field_name]

            if incoming_value is not None:
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
