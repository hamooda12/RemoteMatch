"""add pagination metadata to job sync run sources

Revision ID: 2e62e89b2a73
Revises: 274ee6db61c8
Create Date: 2026-08-17 15:49:20.968342

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "2e62e89b2a73"
down_revision: str | Sequence[str] | None = "274ee6db61c8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "job_sync_run_sources",
        sa.Column("page_limit", sa.Integer(), nullable=True),
    )
    op.add_column(
        "job_sync_run_sources",
        sa.Column("pagination_exhausted", sa.Boolean(), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("job_sync_run_sources", "pagination_exhausted")
    op.drop_column("job_sync_run_sources", "page_limit")
