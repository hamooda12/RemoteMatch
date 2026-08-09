import json

import pytest
from sqlalchemy.exc import SQLAlchemyError

from app.cli import sync_jobs
from app.services.job_sync import JobSyncError, JobSyncSummary


def _patch_run_sync(monkeypatch: pytest.MonkeyPatch, *, result=None, exception=None) -> None:
    async def fake_run_sync(source_name: str, max_pages: int):
        if exception is not None:
            raise exception

        return result

    monkeypatch.setattr(sync_jobs, "run_sync", fake_run_sync)


def test_sync_all_exits_zero_when_every_source_succeeds(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    summaries = [
        JobSyncSummary(source_name="arbeitnow", fetched_records=3),
        JobSyncSummary(source_name="remoteok", fetched_records=2),
    ]
    _patch_run_sync(monkeypatch, result=summaries)
    monkeypatch.setattr(sync_jobs.sys, "argv", ["sync_jobs.py", "--source", "all"])

    exit_code = sync_jobs.main()

    assert exit_code == 0

    output = json.loads(capsys.readouterr().out)
    assert [entry["source_name"] for entry in output] == ["arbeitnow", "remoteok"]


def test_sync_all_exits_nonzero_when_one_source_fails_but_others_still_ran(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    summaries = [
        JobSyncSummary(source_name="arbeitnow", error="Unable to synchronize arbeitnow page 1."),
        JobSyncSummary(source_name="remoteok", fetched_records=4),
    ]
    _patch_run_sync(monkeypatch, result=summaries)
    monkeypatch.setattr(sync_jobs.sys, "argv", ["sync_jobs.py", "--source", "all"])

    exit_code = sync_jobs.main()

    assert exit_code != 0

    output = json.loads(capsys.readouterr().out)
    assert [entry["source_name"] for entry in output] == ["arbeitnow", "remoteok"]
    assert output[0]["error"] is not None
    assert output[1]["error"] is None


def test_sync_all_exits_nonzero_when_every_source_fails(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    summaries = [
        JobSyncSummary(source_name="arbeitnow", error="Unable to synchronize arbeitnow page 1."),
        JobSyncSummary(source_name="remoteok", error="Unable to synchronize remoteok page 1."),
    ]
    _patch_run_sync(monkeypatch, result=summaries)
    monkeypatch.setattr(sync_jobs.sys, "argv", ["sync_jobs.py", "--source", "all"])

    exit_code = sync_jobs.main()

    assert exit_code != 0


def test_single_source_sync_exits_zero_on_success(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    summaries = [JobSyncSummary(source_name="arbeitnow", fetched_records=1)]
    _patch_run_sync(monkeypatch, result=summaries)
    monkeypatch.setattr(sync_jobs.sys, "argv", ["sync_jobs.py", "--source", "arbeitnow"])

    exit_code = sync_jobs.main()

    assert exit_code == 0

    output = json.loads(capsys.readouterr().out)
    assert output["source_name"] == "arbeitnow"


def test_single_source_sync_exits_nonzero_on_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _patch_run_sync(
        monkeypatch,
        exception=JobSyncError("Unable to synchronize arbeitnow page 1."),
    )
    monkeypatch.setattr(sync_jobs.sys, "argv", ["sync_jobs.py", "--source", "arbeitnow"])

    exit_code = sync_jobs.main()

    assert exit_code == 1


def test_database_failure_exits_nonzero(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _patch_run_sync(
        monkeypatch,
        exception=SQLAlchemyError("connection refused"),
    )
    monkeypatch.setattr(sync_jobs.sys, "argv", ["sync_jobs.py", "--source", "all"])

    exit_code = sync_jobs.main()

    assert exit_code == 1
