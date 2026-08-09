from app.core.config import Settings, get_settings
from app.integrations.job_sources.arbeitnow import (
    ARBEITNOW_SOURCE_NAME,
    ArbeitnowJobSource,
)
from app.integrations.job_sources.base import (
    JobSource,
    JobSourceError,
    JobSourceFetchResult,
)
from app.integrations.job_sources.greenhouse import (
    GREENHOUSE_SOURCE_NAME,
    GreenhouseJobSource,
)
from app.integrations.job_sources.himalayas import (
    HIMALAYAS_SOURCE_NAME,
    HimalayasJobSource,
)
from app.integrations.job_sources.jobicy import (
    JOBICY_SOURCE_NAME,
    JobicyJobSource,
)
from app.integrations.job_sources.remoteok import (
    REMOTEOK_SOURCE_NAME,
    RemoteOKJobSource,
)


def build_job_source_registry(
    settings: Settings | None = None,
) -> dict[str, JobSource]:
    settings = settings if settings is not None else get_settings()

    sources: tuple[JobSource, ...] = (
        ArbeitnowJobSource(),
        GreenhouseJobSource(),
        HimalayasJobSource(),
        JobicyJobSource(),
        RemoteOKJobSource(),
    )

    enabled = {
        ARBEITNOW_SOURCE_NAME: settings.job_source_arbeitnow_enabled,
        GREENHOUSE_SOURCE_NAME: settings.job_source_greenhouse_enabled,
        HIMALAYAS_SOURCE_NAME: settings.job_source_himalayas_enabled,
        JOBICY_SOURCE_NAME: settings.job_source_jobicy_enabled,
        REMOTEOK_SOURCE_NAME: settings.job_source_remoteok_enabled,
    }

    return {source.name: source for source in sources if enabled[source.name]}


def available_job_source_names() -> tuple[str, ...]:
    return tuple(build_job_source_registry())


__all__ = [
    "ARBEITNOW_SOURCE_NAME",
    "GREENHOUSE_SOURCE_NAME",
    "HIMALAYAS_SOURCE_NAME",
    "JOBICY_SOURCE_NAME",
    "REMOTEOK_SOURCE_NAME",
    "ArbeitnowJobSource",
    "GreenhouseJobSource",
    "HimalayasJobSource",
    "JobSource",
    "JobSourceError",
    "JobSourceFetchResult",
    "JobicyJobSource",
    "RemoteOKJobSource",
    "available_job_source_names",
    "build_job_source_registry",
]
