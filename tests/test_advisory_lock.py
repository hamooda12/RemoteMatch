import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

from app.core.config import get_settings
from app.db.advisory_lock import (
    SOURCE_SYNC_LOCK_NAMESPACE,
    SourceLockOwnershipLostError,
    UnknownJobSourceLockKeyError,
    acquire_source_sync_lock,
    verify_lock_backend,
)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@asynccontextmanager
async def isolated_engine() -> AsyncIterator[AsyncEngine]:
    """A dedicated engine, simulating a fully separate process/connection
    sharing the same physical PostgreSQL database."""
    engine = create_async_engine(
        get_settings().database_url,
        pool_pre_ping=True,
    )
    try:
        yield engine
    finally:
        await engine.dispose()


async def held_advisory_lock_count(engine: AsyncEngine) -> int:
    async with engine.connect() as inspector:
        count = await inspector.scalar(
            text(
                "SELECT count(*) FROM pg_locks "
                "WHERE locktype = 'advisory' AND granted = true "
                "AND classid = :namespace"
            ),
            {"namespace": SOURCE_SYNC_LOCK_NAMESPACE},
        )
        return int(count)


# --- Acquisition, independence, release ----------------------------------


@pytest.mark.anyio
async def test_lock_conflicts_while_held_by_another_connection() -> None:
    async with (
        isolated_engine() as engine_a,
        isolated_engine() as engine_b,
        acquire_source_sync_lock(engine_a, "arbeitnow") as lock_a,
    ):
        assert lock_a.acquired is True

        async with acquire_source_sync_lock(engine_b, "arbeitnow") as lock_b:
            assert lock_b.acquired is False
            assert lock_b.connection is None
            assert lock_b.backend_pid is None


@pytest.mark.anyio
async def test_lock_is_available_again_after_normal_exit() -> None:
    async with isolated_engine() as engine_a, isolated_engine() as engine_b:
        async with acquire_source_sync_lock(engine_a, "greenhouse") as lock_a:
            assert lock_a.acquired is True

        async with acquire_source_sync_lock(engine_b, "greenhouse") as lock_b:
            assert lock_b.acquired is True


@pytest.mark.anyio
async def test_lock_is_released_when_an_exception_propagates() -> None:
    """Proves an application-level exception (connection stays healthy)
    still runs the explicit unlock, not just a normal commit."""
    async with isolated_engine() as engine_a, isolated_engine() as engine_b:
        with pytest.raises(RuntimeError, match="simulated failure mid-sync"):
            async with acquire_source_sync_lock(engine_a, "himalayas") as lock_a:
                assert lock_a.acquired is True
                raise RuntimeError("simulated failure mid-sync")

        async with acquire_source_sync_lock(engine_b, "himalayas") as lock_b:
            assert lock_b.acquired is True


@pytest.mark.anyio
async def test_different_known_sources_do_not_conflict() -> None:
    async with (
        isolated_engine() as engine_a,
        isolated_engine() as engine_b,
        acquire_source_sync_lock(engine_a, "jobicy") as lock_a,
    ):
        assert lock_a.acquired is True

        async with acquire_source_sync_lock(engine_b, "remoteok") as lock_b:
            assert lock_b.acquired is True


@pytest.mark.anyio
async def test_lock_conflict_is_visible_in_pg_locks_and_clears_after_exit() -> None:
    """Direct proof via pg_locks (not merely the Python boolean return)
    that the lock is a real PostgreSQL advisory lock while held, and that
    it is gone from pg_locks once released."""
    async with isolated_engine() as engine_a, isolated_engine() as engine_b:
        async with acquire_source_sync_lock(engine_a, "arbeitnow") as lock_a:
            assert lock_a.acquired is True
            assert await held_advisory_lock_count(engine_b) == 1

        assert await held_advisory_lock_count(engine_b) == 0


# --- Strict, known-connectors-only key contract (no hashtext fallback) ---


@pytest.mark.anyio
async def test_unrecognized_source_name_fails_clearly() -> None:
    async with isolated_engine() as engine:
        with pytest.raises(UnknownJobSourceLockKeyError, match="not-a-real-connector"):
            async with acquire_source_sync_lock(engine, "not-a-real-connector"):
                pass


@pytest.mark.anyio
async def test_unrecognized_source_name_never_opens_a_connection() -> None:
    """The key lookup must fail before any connection is checked out --
    proving it truly rejects rather than falling back to some default
    behavior that happens to work."""
    async with isolated_engine() as engine:
        with pytest.raises(UnknownJobSourceLockKeyError):
            async with acquire_source_sync_lock(engine, "unknown"):
                pass

        # The engine's pool must show no checked-out connections leaked by
        # the rejected attempt.
        assert engine.pool.checkedout() == 0


# --- Session-level scope: survives commits on a bound AsyncSession -------


@pytest.mark.anyio
async def test_lock_survives_multiple_commits_on_a_bound_session() -> None:
    """The whole reason for using pg_try_advisory_lock (session-level)
    instead of pg_try_advisory_xact_lock: ingestion commits once per
    record, and the lock must survive every one of them."""
    async with isolated_engine() as engine_a, isolated_engine() as engine_b:
        async with acquire_source_sync_lock(engine_a, "arbeitnow") as lock_a:
            assert lock_a.acquired is True
            assert lock_a.connection is not None

            source_database = AsyncSession(bind=lock_a.connection, expire_on_commit=False)
            try:
                for _ in range(5):
                    await source_database.execute(text("SELECT 1"))
                    await source_database.commit()

                    async with acquire_source_sync_lock(engine_b, "arbeitnow") as lock_b:
                        assert lock_b.acquired is False
            finally:
                await source_database.close()

        async with acquire_source_sync_lock(engine_b, "arbeitnow") as lock_b:
            assert lock_b.acquired is True


@pytest.mark.anyio
async def test_lock_survives_a_rollback_on_a_bound_session() -> None:
    """Direct proof (not merely inferred through ingestion's rollback-
    recovery behavior) that the session-level lock survives ROLLBACK, not
    just COMMIT -- required since JobIngestionService's race-recovery path
    performs real rollbacks on the pinned connection."""
    async with isolated_engine() as engine_a, isolated_engine() as engine_b:
        async with acquire_source_sync_lock(engine_a, "arbeitnow") as lock_a:
            assert lock_a.acquired is True
            assert lock_a.connection is not None

            async with acquire_source_sync_lock(engine_b, "arbeitnow") as lock_b:
                assert lock_b.acquired is False

            source_database = AsyncSession(bind=lock_a.connection, expire_on_commit=False)
            try:
                await source_database.execute(text("SELECT 1"))
                await source_database.rollback()

                async with acquire_source_sync_lock(engine_b, "arbeitnow") as lock_b:
                    assert lock_b.acquired is False
            finally:
                await source_database.close()

        async with acquire_source_sync_lock(engine_b, "arbeitnow") as lock_b:
            assert lock_b.acquired is True


@pytest.mark.anyio
async def test_bound_session_uses_the_exact_backend_that_holds_the_lock() -> None:
    """Direct proof that the physical PostgreSQL backend performing writes
    through the bound AsyncSession is the same backend pg_backend_pid()
    reported when the lock was acquired -- the core B3 guarantee."""
    async with isolated_engine() as engine, acquire_source_sync_lock(engine, "jobicy") as lock:
        assert lock.acquired is True
        assert lock.connection is not None
        assert lock.backend_pid is not None

        source_database = AsyncSession(bind=lock.connection, expire_on_commit=False)
        try:
            for _ in range(3):
                observed_pid = await source_database.scalar(text("SELECT pg_backend_pid()"))
                assert observed_pid == lock.backend_pid
                await source_database.commit()
        finally:
            await source_database.close()


# --- verify_lock_backend() ------------------------------------------------


@pytest.mark.anyio
async def test_verify_lock_backend_passes_when_pid_matches() -> None:
    async with (
        isolated_engine() as engine,
        acquire_source_sync_lock(engine, "remoteok") as lock,
    ):
        assert lock.acquired is True
        assert lock.connection is not None
        assert lock.backend_pid is not None

        source_database = AsyncSession(bind=lock.connection, expire_on_commit=False)
        try:
            await verify_lock_backend(source_database, lock.backend_pid)
        finally:
            await source_database.close()


@pytest.mark.anyio
async def test_verify_lock_backend_raises_on_pid_mismatch() -> None:
    async with (
        isolated_engine() as engine,
        acquire_source_sync_lock(engine, "himalayas") as lock,
    ):
        assert lock.acquired is True
        assert lock.connection is not None

        source_database = AsyncSession(bind=lock.connection, expire_on_commit=False)
        try:
            with pytest.raises(SourceLockOwnershipLostError):
                await verify_lock_backend(source_database, -1)
        finally:
            await source_database.close()


# --- The critical regression: lock-holder backend termination ------------


@pytest.mark.anyio
async def test_lock_holder_backend_termination_releases_the_lock_for_others() -> None:
    """Protocol-level version of the critical B3 regression: kill the
    exact backend holding the lock (not the whole process) and prove (1)
    the lock becomes immediately available to a fresh acquirer, and (2)
    the now-dead connection/session can no longer be used to write."""
    async with (
        isolated_engine() as engine_a,
        isolated_engine() as engine_terminator,
        acquire_source_sync_lock(engine_a, "arbeitnow") as lock_a,
    ):
        assert lock_a.acquired is True
        assert lock_a.connection is not None
        backend_pid = lock_a.backend_pid

        async with engine_terminator.connect() as terminator:
            terminated = await terminator.scalar(
                text("SELECT pg_terminate_backend(:pid)"),
                {"pid": backend_pid},
            )
            assert terminated is True

        # Give PostgreSQL a moment to finish tearing the backend down
        # and release its advisory lock.
        async with isolated_engine() as engine_probe:
            acquired_elsewhere = False
            for _ in range(20):
                async with acquire_source_sync_lock(engine_probe, "arbeitnow") as probe:
                    if probe.acquired:
                        acquired_elsewhere = True
                        break
                await asyncio.sleep(0.1)
            assert acquired_elsewhere, (
                "Expected a fresh connection to acquire the lock promptly "
                "after the holding backend was terminated."
            )

        # The original (now-dead) connection must fail, not silently
        # succeed, on further use -- proving Run A cannot keep writing.
        source_database = AsyncSession(bind=lock_a.connection, expire_on_commit=False)
        try:
            with pytest.raises(Exception):  # noqa: B017 - any DBAPI/SQLAlchemy failure is correct here
                await source_database.scalar(text("SELECT pg_backend_pid()"))
        finally:
            with suppress(Exception):
                await source_database.close()


@pytest.mark.anyio
async def test_lock_cleanup_does_not_raise_when_unlock_fails_on_a_dead_connection() -> None:
    """When the holder's backend is terminated mid-use, the unlock attempt
    inside acquire_source_sync_lock's own cleanup will itself fail against
    the now-dead connection (confirmed directly: SourceLockHandle.connection
    reports `.invalidated is True` immediately after such a failure, per a
    focused reproduction of this exact sequence -- see the module's
    `finally` block). That failure must be swallowed internally rather
    than propagating out and masking whatever the caller's body was doing.
    Proven here black-box: the whole call completes with no exception, and
    the lock is confirmed available again immediately afterward (see also
    test_lock_holder_backend_termination_releases_the_lock_for_others for
    the fuller version of that same proof)."""
    async with isolated_engine() as engine_a:

        async def run_and_kill() -> None:
            async with acquire_source_sync_lock(engine_a, "greenhouse") as lock:
                assert lock.acquired is True
                assert lock.connection is not None

                async with (
                    isolated_engine() as engine_terminator,
                    engine_terminator.connect() as terminator,
                ):
                    await terminator.execute(
                        text("SELECT pg_terminate_backend(:pid)"),
                        {"pid": lock.backend_pid},
                    )

                await asyncio.sleep(0.2)

        # No exception should escape here: cleanup swallows the failed
        # unlock (caught by `except Exception` around the pg_advisory_unlock
        # call) rather than letting it propagate and mask this call.
        await run_and_kill()

    async with (
        isolated_engine() as engine_b,
        acquire_source_sync_lock(engine_b, "greenhouse") as lock_b,
    ):
        assert lock_b.acquired is True
