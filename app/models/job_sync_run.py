from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class JobSyncRun(Base):
    __tablename__ = "job_sync_runs"

    __table_args__ = (
        CheckConstraint(
            "status IN ('running', 'succeeded', 'partial', 'failed')",
            name="ck_job_sync_runs_status",
        ),
        Index(
            "ix_job_sync_runs_started_at",
            "started_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="running",
        server_default=text("'running'"),
    )

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    sources: Mapped[list[JobSyncRunSource]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class JobSyncRunSource(Base):
    __tablename__ = "job_sync_run_sources"

    __table_args__ = (
        UniqueConstraint(
            "run_id",
            "source_name",
            name="uq_job_sync_run_sources_run_source",
        ),
        CheckConstraint(
            "status IN ('running', 'succeeded', 'failed')",
            name="ck_job_sync_run_sources_status",
        ),
        CheckConstraint(
            """
            pages_fetched >= 0
            AND fetched_records >= 0
            AND created >= 0
            AND updated >= 0
            AND duplicates >= 0
            AND conflicts >= 0
            AND rejected >= 0
            AND skipped_non_remote >= 0
            """,
            name="ck_job_sync_run_sources_counts_non_negative",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "job_sync_runs.id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )

    source_name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="running",
        server_default=text("'running'"),
    )

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    pages_fetched: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )

    fetched_records: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )

    created: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )

    updated: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )

    duplicates: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )

    conflicts: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )

    rejected: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )

    skipped_non_remote: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )

    # --- Pagination-loop metadata (per source, per run) -----------------
    # page_limit: the EFFECTIVE page cap that bounded this source's fetch
    # loop in this run -- i.e. whatever value actually drove
    # `for page in range(1, max_pages + 1)` in
    # JobSyncService._fetch_and_ingest_source. This is min(requested
    # max_pages, connector's own max_pages) as already computed by the
    # caller (sync_source's validated max_pages, or sync_all's
    # min(max_pages, source_max_pages)) -- never the raw CLI-requested
    # value in isolation.
    #
    # pagination_exhausted: True only if a real run reached a connector
    # response whose has_next_page was False (the connector itself said
    # there was nothing more on that call). False for a completed/failed
    # real run where natural pagination exhaustion was not reached -- i.e.
    # the loop stopped because page_limit was reached while has_next_page
    # was still True, or the fetch failed before a natural stop was
    # reached.
    #
    # NULL on both fields means completion metadata was never populated --
    # it is unknown, not "known to be incomplete". This covers: rows
    # created before these columns existed; a row still status="running"
    # (both fields are only set by complete_run_source(), never by
    # create_run_source()); and rows left permanently "running" because
    # the process crashed, was cancelled, or otherwise failed before
    # completion metadata could be persisted. Do not treat NULL as
    # equivalent to False, and do not assume it only occurs on
    # pre-migration historical rows.
    #
    # IMPORTANT: pagination_exhausted is a narrow technical fact about one
    # pagination loop finishing -- it is NOT a "snapshot complete" or
    # "safe to reconcile" signal. Several connectors (Greenhouse, RemoteOK,
    # Jobicy) report has_next_page=False on every single-page call by
    # construction, which says nothing about whether the fetched results
    # represent that source's full current job set. Do not add a derived
    # property that reinterprets this field as reconciliation-safety.
    page_limit: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    pagination_exhausted: Mapped[bool | None] = mapped_column(
        Boolean,
        nullable=True,
    )

    error_code: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )

    error_message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    run: Mapped[JobSyncRun] = relationship(
        back_populates="sources",
    )
