"""create job source references table

Revision ID: 274ee6db61c8
Revises: 0dbe1758f41c
Create Date: 2026-08-09 13:52:18.988532

"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import column, table

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "274ee6db61c8"
down_revision: str | Sequence[str] | None = "0dbe1758f41c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "job_source_references",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("job_id", sa.UUID(), nullable=False),
        sa.Column("source_name", sa.String(length=100), nullable=False),
        sa.Column("source_job_id", sa.String(length=255), nullable=False),
        sa.Column("source_url", sa.String(length=2048), nullable=False),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["jobs.id"],
            name=op.f("fk_job_source_references_job_id_jobs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_job_source_references")),
        sa.UniqueConstraint(
            "source_name",
            "source_job_id",
            name="uq_job_source_references_source",
        ),
    )
    op.create_index(
        "ix_job_source_references_job_id",
        "job_source_references",
        ["job_id"],
        unique=False,
    )

    # Backfill: every existing Job row already represents exactly one known
    # source observation. Use ad-hoc table proxies (not the live ORM model)
    # so this migration keeps working unchanged if `app.models.job.Job`
    # changes shape later. No Postgres UUID extension is enabled anywhere
    # in this database, so `id` values are generated in Python, matching the
    # app-side `default=uuid.uuid4` convention used everywhere else.
    jobs_table = table(
        "jobs",
        column("id", sa.UUID()),
        column("source_name", sa.String()),
        column("source_job_id", sa.String()),
        column("source_url", sa.String()),
        column("first_seen_at", sa.DateTime(timezone=True)),
        column("last_seen_at", sa.DateTime(timezone=True)),
    )
    job_source_references_table = table(
        "job_source_references",
        column("id", sa.UUID()),
        column("job_id", sa.UUID()),
        column("source_name", sa.String()),
        column("source_job_id", sa.String()),
        column("source_url", sa.String()),
        column("first_seen_at", sa.DateTime(timezone=True)),
        column("last_seen_at", sa.DateTime(timezone=True)),
    )

    bind = op.get_bind()
    existing_jobs = bind.execute(
        sa.select(
            jobs_table.c.id,
            jobs_table.c.source_name,
            jobs_table.c.source_job_id,
            jobs_table.c.source_url,
            jobs_table.c.first_seen_at,
            jobs_table.c.last_seen_at,
        )
    ).fetchall()

    if existing_jobs:
        backfill_rows = [
            {
                "id": uuid.uuid4(),
                "job_id": job_row.id,
                "source_name": job_row.source_name,
                "source_job_id": job_row.source_job_id,
                "source_url": job_row.source_url,
                "first_seen_at": job_row.first_seen_at,
                "last_seen_at": job_row.last_seen_at,
            }
            for job_row in existing_jobs
        ]

        insert_statement = (
            sa.dialects.postgresql.insert(job_source_references_table)
            .values(backfill_rows)
            .on_conflict_do_nothing(
                index_elements=["source_name", "source_job_id"],
            )
        )
        bind.execute(insert_statement)


def downgrade() -> None:
    """Downgrade schema.

    This drops job_source_references only. Job.source_name/source_job_id/
    source_url (the legacy compatibility fields) are untouched and remain
    intact, so no existing source identity is lost. However, any additional
    JobSourceReference rows created for secondary sources *after* this
    migration's upgrade (i.e. multi-source data that only ever existed in
    this table) will be permanently discarded. Do not downgrade past this
    revision once multi-source ingestion has run in production.
    """
    op.drop_index(
        "ix_job_source_references_job_id",
        table_name="job_source_references",
    )
    op.drop_table("job_source_references")
