from app.integrations.job_sources.arbeitnow import (
    ARBEITNOW_SOURCE_NAME,
    ArbeitnowJobSource,
)
from app.integrations.job_sources.base import (
    JobSource,
    JobSourceError,
    JobSourceFetchResult,
)
from app.integrations.job_sources.himalayas import (
    HIMALAYAS_SOURCE_NAME,
    HimalayasJobSource,
)


def build_job_source_registry() -> dict[str, JobSource]:
    sources: tuple[JobSource, ...] = (
        ArbeitnowJobSource(),
        HimalayasJobSource(),
    )

    return {source.name: source for source in sources}


def available_job_source_names() -> tuple[str, ...]:
    return tuple(build_job_source_registry())


__all__ = [
    "ARBEITNOW_SOURCE_NAME",
    "HIMALAYAS_SOURCE_NAME",
    "ArbeitnowJobSource",
    "HimalayasJobSource",
    "JobSource",
    "JobSourceError",
    "JobSourceFetchResult",
    "available_job_source_names",
    "build_job_source_registry",
]
