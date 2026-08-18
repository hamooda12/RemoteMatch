"""add run source correlation to job source references

Revision ID: 5b0e9aeadf39
Revises: 2e62e89b2a73
Create Date: 2026-08-18 13:49:03.377554

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "5b0e9aeadf39"
down_revision: str | Sequence[str] | None = "2e62e89b2a73"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema.

    Adds a single mutable "most recently observed by" pointer from
    JobSourceReference to JobSyncRunSource (Task B2). This is NOT a
    historical observation log -- see the column comment in
    app/models/job_source_reference.py for the exact semantics and the
    pre-Task-B3 overlapping-run limitation.

    No backfill: existing rows get NULL, since no historical run-source
    correlation was ever recorded for them and inferring one from
    first_seen_at/last_seen_at proximity would be exactly the unreliable
    guess this task exists to replace. They populate naturally the next
    time each reference is observed.
    """
    op.add_column(
        "job_source_references",
        sa.Column("last_seen_run_source_id", sa.UUID(), nullable=True),
    )
    op.create_index(
        "ix_job_source_references_last_seen_run_source_id",
        "job_source_references",
        ["last_seen_run_source_id"],
        unique=False,
    )
    op.create_foreign_key(
        op.f("fk_job_source_references_last_seen_run_source_id_job_sync_run_sources"),
        "job_source_references",
        "job_sync_run_sources",
        ["last_seen_run_source_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(
        op.f("fk_job_source_references_last_seen_run_source_id_job_sync_run_sources"),
        "job_source_references",
        type_="foreignkey",
    )
    op.drop_index(
        "ix_job_source_references_last_seen_run_source_id",
        table_name="job_source_references",
    )
    op.drop_column("job_source_references", "last_seen_run_source_id")
