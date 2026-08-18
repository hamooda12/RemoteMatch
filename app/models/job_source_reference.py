from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.job import Job


class JobSourceReference(Base):
    __tablename__ = "job_source_references"

    __table_args__ = (
        UniqueConstraint(
            "source_name",
            "source_job_id",
            name="uq_job_source_references_source",
        ),
        Index(
            "ix_job_source_references_job_id",
            "job_id",
        ),
        Index(
            "ix_job_source_references_last_seen_run_source_id",
            "last_seen_run_source_id",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "jobs.id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )

    source_name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    source_job_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    source_url: Mapped[str] = mapped_column(
        String(2048),
        nullable=False,
    )

    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    # The JobSyncRunSource associated with the most recently *persisted*
    # last_seen_run_source_id points to the most recent
    # sync-run-correlated observation of this source reference.

    # If an observation is performed without a sync_run_source_id,
    # touch() intentionally leaves the existing correlation unchanged.

    # This is a latest correlation pointer, not observation history.

    # Before same-source overlap protection exists, overlapping runs
    # remain last-write-wins and may not reflect chronological order.
    last_seen_run_source_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "job_sync_run_sources.id",
            ondelete="SET NULL",
        ),
        nullable=True,
    )

    job: Mapped[Job] = relationship(back_populates="source_references")
