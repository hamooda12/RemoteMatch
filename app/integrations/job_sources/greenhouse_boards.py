from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class GreenhouseBoard:
    token: str
    company_name: str
    all_jobs_remote: bool = False


GREENHOUSE_BOARDS: tuple[GreenhouseBoard, ...] = (
    GreenhouseBoard(
        token="gitlab",
        company_name="GitLab",
        all_jobs_remote=True,
    ),
    GreenhouseBoard(
        token="remotecom",
        company_name="Remote",
        all_jobs_remote=True,
    ),
    GreenhouseBoard(
        token="stackexchange",
        company_name="Stack Overflow",
        all_jobs_remote=True,
    ),
)
