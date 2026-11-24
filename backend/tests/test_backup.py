"""The worker's daily backup: written and verified, pruned to the newest 7, skipped on
low disk. pg_dump / pg_restore are replaced by a stand-in (the CI host has neither); the
real tools run in the image (checked live, see the PR)."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.core.config import get_settings
from app.ops import backup
from app.worker import backup_database as worker_backup
from app.worker import cron_jobs

NOW = datetime(2026, 11, 25, 21, 0, tzinfo=UTC)


@pytest.fixture
def fake_tools(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, ...]]:
    calls: list[tuple[str, ...]] = []

    async def run(*command: str, env: dict[str, str]) -> tuple[int, bytes]:
        calls.append(command)
        assert env["PGPASSWORD"]  # the password goes in the environment, not argv
        if command[0] == "pg_dump":
            target = next(a for a in command if a.startswith("--file="))[len("--file=") :]
            Path(target).write_bytes(b"PGDMP fake archive")
            return 0, b""
        return 0, b"; Archive\n1; 0 0 TABLE DATA public jobs jobmatch\n"

    monkeypatch.setattr(backup, "_run", run)
    return calls


def settings_for(directory: Path, **overrides: object):  # type: ignore[no-untyped-def]
    return get_settings().model_copy(update={"backup_dir": str(directory), **overrides})


async def test_a_backup_is_written_verified_and_old_ones_pruned(
    tmp_path: Path, fake_tools: list[tuple[str, ...]], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(backup, "free_gb", lambda _: 40.0)
    for day in range(8):  # eight older archives, from make backup or earlier runs
        stamp = (NOW - timedelta(days=day + 1)).strftime("%Y%m%dT%H%M%SZ")
        (tmp_path / f"jobmatch-{stamp}.dump").write_bytes(b"old")
    (tmp_path / "notes.txt").write_text("not an archive")

    result = await backup.backup_database(settings_for(tmp_path), now=NOW)

    assert result.status == "written"
    assert result.path is not None and result.path.endswith("jobmatch-20261125T210000Z.dump")
    assert [c[0] for c in fake_tools] == ["pg_dump", "pg_restore"]
    archives = sorted(p.name for p in tmp_path.glob("jobmatch-*.dump"))
    assert len(archives) == 7 and archives[-1] == "jobmatch-20261125T210000Z.dump"
    assert len(result.removed) == 2  # the two oldest
    assert (tmp_path / "notes.txt").exists()
    assert not list(tmp_path.glob("*.partial"))


async def test_low_disk_skips_and_writes_nothing(
    tmp_path: Path, fake_tools: list[tuple[str, ...]], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(backup, "free_gb", lambda _: 14.2)
    result = await backup.backup_database(settings_for(tmp_path), now=NOW)
    assert (result.status, result.detail) == ("skipped", "14.2 GB free < 15.0 GB")
    assert fake_tools == [] and not list(tmp_path.iterdir())


async def test_an_unreadable_archive_is_not_kept(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(backup, "free_gb", lambda _: 40.0)

    async def run(*command: str, env: dict[str, str]) -> tuple[int, bytes]:
        if command[0] == "pg_dump":
            target = next(a for a in command if a.startswith("--file="))[len("--file=") :]
            Path(target).write_bytes(b"truncated")
            return 0, b""
        return 1, b"pg_restore: error: could not read input file"

    monkeypatch.setattr(backup, "_run", run)
    result = await backup.backup_database(settings_for(tmp_path), now=NOW)
    assert result.status == "failed" and not list(tmp_path.iterdir())


async def test_a_missing_backup_folder_fails_clearly(tmp_path: Path) -> None:
    result = await backup.backup_database(settings_for(tmp_path / "absent"), now=NOW)
    assert result.status == "failed" and "not mounted" in (result.detail or "")


def test_the_backup_runs_daily_at_two_thirty() -> None:
    job = next(j for j in cron_jobs(get_settings()) if j.name == "cron:backup_database")
    assert job.coroutine is worker_backup
    assert (job.hour, job.minute) == (2, 30)
