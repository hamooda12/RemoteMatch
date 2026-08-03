import re
import unicodedata
from datetime import UTC, datetime
from hashlib import sha256

from app.schemas.job_ingestion import JobIngestionRecord
from app.services.cv_skill_extractor import (
    MAX_EXTRACTED_SKILLS,
    SKILL_TAXONOMY,
    extract_skills,
)


def _comparison_value(value: str) -> str:
    return " ".join(value.split()).casefold()


_SKILL_ALIAS_MAP: dict[str, str] = {
    _comparison_value(alias): canonical_name
    for canonical_name, aliases in SKILL_TAXONOMY
    for alias in (canonical_name, *aliases)
}


def normalize_job_skills(
    record: JobIngestionRecord,
) -> list[str]:
    extracted_skills = extract_skills(
        "\n".join(
            value
            for value in (
                record.description,
                record.requirements,
            )
            if value
        )
    )

    normalized_skills: list[str] = []
    seen_skills: set[str] = set()

    for skill in (
        *record.skills,
        *extracted_skills,
    ):
        comparison_value = _comparison_value(skill)
        canonical_name = _SKILL_ALIAS_MAP.get(
            comparison_value,
            skill,
        )
        canonical_comparison = canonical_name.casefold()

        if canonical_comparison in seen_skills:
            continue

        seen_skills.add(canonical_comparison)
        normalized_skills.append(canonical_name)

        if len(normalized_skills) >= MAX_EXTRACTED_SKILLS:
            break

    return normalized_skills


def _fingerprint_value(value: str | None) -> str:
    if value is None:
        return ""

    normalized_value = unicodedata.normalize(
        "NFKC",
        value,
    ).casefold()

    return " ".join(
        re.sub(
            r"[^\w]+",
            " ",
            normalized_value,
        ).split()
    )


def build_job_deduplication_key(
    record: JobIngestionRecord,
) -> str:
    normalized_regions = sorted(_fingerprint_value(region) for region in record.remote_regions)

    fingerprint_parts = (
        _fingerprint_value(record.company_name),
        _fingerprint_value(record.title),
        _fingerprint_value(record.location),
        "|".join(normalized_regions),
    )

    fingerprint = "\x1f".join(fingerprint_parts)

    return sha256(fingerprint.encode("utf-8")).hexdigest()


def build_job_values(
    record: JobIngestionRecord,
    *,
    observed_at: datetime | None = None,
) -> dict[str, object]:
    observation_time = observed_at or datetime.now(UTC)

    return {
        "source_name": record.source_name,
        "source_job_id": record.source_job_id,
        "deduplication_key": build_job_deduplication_key(record),
        "source_url": str(record.source_url),
        "application_url": (
            str(record.application_url) if record.application_url is not None else None
        ),
        "title": record.title,
        "company_name": record.company_name,
        "description": record.description,
        "requirements": record.requirements,
        "location": record.location,
        "remote_regions": list(record.remote_regions),
        "employment_type": record.employment_type,
        "experience_level": record.experience_level,
        "salary_min": record.salary_min,
        "salary_max": record.salary_max,
        "salary_currency": record.salary_currency,
        "skills": normalize_job_skills(record),
        "is_remote": True,
        "is_active": True,
        "published_at": record.published_at,
        "expires_at": record.expires_at,
        "last_seen_at": observation_time,
    }
