import argparse
import asyncio
import json
import sys
from dataclasses import asdict

from sqlalchemy.exc import SQLAlchemyError

from app.db.session import (
    AsyncSessionFactory,
    engine,
)
from app.integrations.job_sources import (
    ARBEITNOW_SOURCE_NAME,
    available_job_source_names,
)
from app.services.job_sync import (
    JobSyncError,
    JobSyncService,
    JobSyncSummary,
)


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Synchronize remote jobs.",
    )

    parser.add_argument(
        "--source",
        choices=(
            *available_job_source_names(),
            "all",
        ),
        default=ARBEITNOW_SOURCE_NAME,
        help=(f"Job source to synchronize, or 'all'. Default: {ARBEITNOW_SOURCE_NAME}."),
    )

    parser.add_argument(
        "--max-pages",
        type=int,
        default=1,
        help=("Maximum number of pages to fetch (default: 1)."),
    )

    return parser.parse_args()


async def run_sync(
    source_name: str,
    max_pages: int,
) -> list[JobSyncSummary]:
    try:
        async with AsyncSessionFactory() as database:
            service = JobSyncService(database, engine=engine)

            if source_name == "all":
                return await service.sync_all(
                    max_pages=max_pages,
                )

            summary = await service.sync_source(
                source_name,
                max_pages=max_pages,
            )

            return [summary]
    finally:
        await engine.dispose()


def main() -> int:
    arguments = parse_arguments()

    try:
        summaries = asyncio.run(
            run_sync(
                arguments.source,
                arguments.max_pages,
            )
        )
    except ValueError as error:
        print(
            f"Invalid job sync configuration: {error}",
            file=sys.stderr,
        )
        return 2
    except JobSyncError as error:
        print(
            str(error),
            file=sys.stderr,
        )
        return 1
    except SQLAlchemyError:
        print(
            "Job sync failed because the database is unavailable.",
            file=sys.stderr,
        )
        return 1

    if arguments.source == "all":
        output: object = [asdict(summary) for summary in summaries]
        exit_code = 1 if any(summary.error is not None for summary in summaries) else 0
    else:
        output = asdict(summaries[0])
        exit_code = 0

    print(
        json.dumps(
            output,
            sort_keys=True,
        )
    )

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
