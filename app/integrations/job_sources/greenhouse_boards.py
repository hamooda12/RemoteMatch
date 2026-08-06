from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class GreenhouseBoard:
    slug: str
    company_name: str
    all_jobs_remote: bool = False


GREENHOUSE_BOARDS: tuple[GreenhouseBoard, ...] = (
    GreenhouseBoard(
        slug="gitlab",
        company_name="GitLab",
        all_jobs_remote=True,
    ),
    GreenhouseBoard(
        slug="remotecom",
        company_name="Remote",
        all_jobs_remote=True,
    ),
    GreenhouseBoard(
        slug="stackexchange",
        company_name="Stack Overflow",
        all_jobs_remote=True,
    ),
)
