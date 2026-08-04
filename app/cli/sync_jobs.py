import argparse
import asyncio
import json
import sys
from dataclasses import asdict

from sqlalchemy.exc import SQLAlchemyError

from app.db.session import AsyncSessionFactory, engine
from app.services.job_sync import (
    JobSyncError,
    JobSyncService,
    JobSyncSummary,
)


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=("Synchronize normalized remote jobs from approved sources.")
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=1,
        help=("Maximum Arbeitnow pages to fetch (1-5, default: 1)."),
    )

    return parser.parse_args()


async def run_sync(
    max_pages: int,
) -> JobSyncSummary:
    try:
        async with AsyncSessionFactory() as database:
            return await JobSyncService(database).sync_arbeitnow(
                max_pages=max_pages,
            )
    finally:
        await engine.dispose()


def main() -> int:
    arguments = parse_arguments()

    try:
        summary = asyncio.run(run_sync(arguments.max_pages))
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

    print(
        json.dumps(
            asdict(summary),
            sort_keys=True,
        )
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
