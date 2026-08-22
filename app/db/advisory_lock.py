"""PostgreSQL session-level advisory locking for per-source job syncs.

Guarantees at most one authoritative synchronization attempt for a given
job source can perform ingestion at a time, across processes/connections
sharing the same database -- while leaving different sources fully
independent.

Architecture (single pinned physical connection):

The lock is acquired on a single dedicated `AsyncConnection` obtained
directly from the engine, using a SESSION-level advisory lock
(`pg_try_advisory_lock`/`pg_advisory_unlock`, not the transaction-scoped
variant). The caller is expected to bind its authoritative-write
`AsyncSession` to that SAME connection (`AsyncSession(bind=connection)`) for
the entire source sync, so the PostgreSQL backend that owns the lock is
always the exact same backend performing the writes -- if that backend
dies, both lock ownership and write capability disappear together,
atomically. This is deliberately NOT a two-connection design: an earlier
version of this module used a transaction-scoped lock on a connection
separate from ingestion's own session, which left a window where the lock
connection could be terminated (idle-in-transaction timeout, network loss,
server-side kill) while the *separate* ingestion connection kept writing,
silently breaking the exclusivity guarantee. Pinning both concerns to one
connection closes that gap without needing a heartbeat or a fencing token.

A session-level lock is required (not `pg_try_advisory_xact_lock`) because
ingestion commits once per record: a transaction-scoped lock would be
released by the very first commit and protect nothing beyond it. Session
scope survives every COMMIT/ROLLBACK on the pinned connection and is only
released by an explicit `pg_advisory_unlock` or by the backend/session
ending.

Defense against a stale connection wrapper: `verify_lock_backend()` lets a
caller re-confirm, immediately before each authoritative write, that the
physical backend currently reachable through the pinned connection/session
is still the exact backend (`pg_backend_pid()`) that acquired the lock --
guarding against the (in this bind=connection design, believed-unreachable,
but not assumed) possibility of the connection wrapper silently ending up
bound to a different physical backend later.

Deliberately knows nothing about JobSyncRun/JobSyncRunSource or any other
ORM state: it operates on source_name strings, integer PIDs, and raw
connections/sessions, never receiving or returning ORM objects owned by an
unrelated session.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession

# Arbitrary, stable namespace for all RemoteMatch job-source-sync advisory
# locks (fits PostgreSQL's int4 range). Must never change: advisory locks
# are matched by (namespace, key) alone, so changing this would silently
# stop old and new processes from contending on the same lock during a
# deploy.
SOURCE_SYNC_LOCK_NAMESPACE = 0x524D4A53  # "RMJS" -- RemoteMatch Job Sync

# Deterministic, collision-free keys for the known, registered RemoteMatch
# connectors ONLY. This module is a production helper for those five
# sources -- it is not a general-purpose named-lock utility. Do NOT use
# Python's built-in hash() here -- it is randomized per-process
# (PYTHONHASHSEED), so two processes would compute different keys for the
# same source name and never actually contend. There is deliberately no
# fallback for unrecognized names (e.g. hashtext()-derived keys): a name
# outside this set fails clearly via UnknownJobSourceLockKeyError rather
# than silently taking on a shared or "close enough" key. Tests that need
# to exercise JobSyncService with fictional source names must inject a
# fake lock provider (see app/services/job_sync.py's
# `always_acquired_source_lock`) instead of routing fictional names
# through this production module.
KNOWN_SOURCE_LOCK_KEYS: dict[str, int] = {
    "arbeitnow": 1,
    "greenhouse": 2,
    "himalayas": 3,
    "jobicy": 4,
    "remoteok": 5,
}


class UnknownJobSourceLockKeyError(Exception):
    """Raised when source_name has no registered advisory-lock key.

    This module only serves the five registered RemoteMatch connectors --
    an unrecognized name fails clearly rather than silently sharing a
    fallback key with other unrelated names.
    """


class SourceLockOwnershipLostError(Exception):
    """Raised by verify_lock_backend() when the physical PostgreSQL
    backend reachable through the caller's connection/session is no
    longer the backend that acquired the source lock (or is no longer
    reachable at all)."""


@dataclass(slots=True)
class SourceLockHandle:
    acquired: bool
    connection: AsyncConnection | None
    backend_pid: int | None


def _require_source_key(source_name: str) -> int:
    try:
        return KNOWN_SOURCE_LOCK_KEYS[source_name]
    except KeyError:
        raise UnknownJobSourceLockKeyError(
            f"No advisory-lock key is registered for job source "
            f"'{source_name}'. Only {sorted(KNOWN_SOURCE_LOCK_KEYS)} are "
            f"supported by try_acquire/acquire_source_sync_lock."
        ) from None


@asynccontextmanager
async def acquire_source_sync_lock(
    engine: AsyncEngine,
    source_name: str,
) -> AsyncIterator[SourceLockHandle]:
    """Attempt a non-blocking, SESSION-level advisory lock for source_name
    on a single dedicated connection.

    Yields a SourceLockHandle. When `acquired` is False, `connection` and
    `backend_pid` are None and the caller must not use them. When
    `acquired` is True, `connection` is a live AsyncConnection the caller
    should bind its authoritative-write AsyncSession to for the rest of
    the operation, and `backend_pid` is the PostgreSQL backend PID that
    holds the lock (from `pg_backend_pid()`), captured while still inside
    this function so it reflects the exact backend that just acquired it.

    On exit, this function always attempts `pg_advisory_unlock` on the
    same connection. If that cannot be confidently verified as successful
    (it raises, or returns false), the connection is invalidated rather
    than returned to the pool as healthy -- a connection that might still
    be carrying lock state (or might already be dead) must never be
    reused as if nothing happened.
    """
    source_key = _require_source_key(source_name)

    async with engine.connect() as connection:
        acquired = bool(
            await connection.scalar(
                text("SELECT pg_try_advisory_lock(:namespace, :source_key)"),
                {
                    "namespace": SOURCE_SYNC_LOCK_NAMESPACE,
                    "source_key": source_key,
                },
            )
        )

        if not acquired:
            await connection.rollback()
            yield SourceLockHandle(acquired=False, connection=None, backend_pid=None)
            return

        backend_pid = await connection.scalar(text("SELECT pg_backend_pid()"))
        # Close out the read-only transaction the two queries above opened
        # -- the lock is session-level, so it survives this cleanly. This
        # also leaves `connection` transaction-free before the caller
        # binds an AsyncSession to it.
        await connection.commit()

        release_confirmed = False

        try:
            yield SourceLockHandle(
                acquired=True,
                connection=connection,
                backend_pid=backend_pid,
            )
        finally:
            try:
                released = await connection.scalar(
                    text("SELECT pg_advisory_unlock(:namespace, :source_key)"),
                    {
                        "namespace": SOURCE_SYNC_LOCK_NAMESPACE,
                        "source_key": source_key,
                    },
                )
                await connection.commit()
                release_confirmed = bool(released)
            except Exception:
                release_confirmed = False

            if not release_confirmed:
                await connection.invalidate()


async def verify_lock_backend(
    database: AsyncSession,
    expected_backend_pid: int,
) -> None:
    """Re-confirm, on the caller's pinned session, that the physical
    PostgreSQL backend it is about to write through is still the exact
    backend that acquired the source lock.

    Must be called (and awaited) immediately before each authoritative
    write, inside the same transaction that will perform that write --
    calling it starts/participates in that transaction, so if the
    connection dies between this check and the write, the write itself
    fails outright rather than silently landing on a different backend.
    """
    try:
        current_pid = await database.scalar(text("SELECT pg_backend_pid()"))
    except SQLAlchemyError as error:
        raise SourceLockOwnershipLostError(
            "Unable to confirm source-lock ownership -- the pinned "
            "database connection is no longer usable."
        ) from error

    if current_pid != expected_backend_pid:
        raise SourceLockOwnershipLostError(
            f"Source-lock ownership changed: acquired on PostgreSQL "
            f"backend {expected_backend_pid}, but the pinned connection "
            f"now reports backend {current_pid}."
        )
