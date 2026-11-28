"""Daily database backup, run by the worker (arq cron, BACKUP_CRON 02:30 in
INGEST_CRON_TIMEZONE): the same archive as `make backup` (pg_dump custom format) into
the bind-mounted ./backups folder, keeping the newest BACKUP_KEEP. Skipped, and logged,
when the disk holding the backups has less than BACKUP_MIN_FREE_GB free: on this machine
the bind mount is drive C:, whose filling up once crashed Docker.

The host has had unclean shutdowns (2026-11-23 and -24); a daily archive bounds what one
can cost.
"""

import asyncio
import logging
import os
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.engine import make_url

from app.core.config import Settings

logger = logging.getLogger(__name__)

PATTERN = "jobmatch-*.dump"


@dataclass(frozen=True)
class BackupResult:
    status: str  # written | skipped | failed
    path: str | None = None
    size_bytes: int | None = None
    removed: tuple[str, ...] = ()
    detail: str | None = None


def free_gb(directory: Path) -> float:
    return shutil.disk_usage(directory).free / 1024**3


def prune(directory: Path, keep: int) -> list[str]:
    """Deletes all but the newest `keep` archives (names sort by their UTC timestamp)."""
    archives = sorted(directory.glob(PATTERN))
    old = archives[:-keep] if keep > 0 else archives
    for path in old:
        path.unlink(missing_ok=True)
    return [p.name for p in old]


def _libpq_env(database_url: str) -> tuple[list[str], dict[str, str]]:
    url = make_url(database_url)
    args = [
        "--host", url.host or "db",
        "--port", str(url.port or 5432),
        "--username", url.username or "jobmatch",
        "--dbname", url.database or "jobmatch",
    ]  # fmt: skip
    env = {**os.environ, "PGPASSWORD": url.password or ""}
    return args, env


def _finish(partial: Path, final: Path) -> int:
    partial.rename(final)
    return final.stat().st_size


async def _run(*command: str, env: dict[str, str]) -> tuple[int, bytes]:
    process = await asyncio.create_subprocess_exec(
        *command,
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, err = await process.communicate()
    return process.returncode or 0, out if process.returncode == 0 else err


async def backup_database(settings: Settings, now: datetime | None = None) -> BackupResult:
    directory = Path(settings.backup_dir)
    if not await asyncio.to_thread(directory.is_dir):
        return BackupResult("failed", detail=f"{directory} does not exist (not mounted?)")
    free = await asyncio.to_thread(free_gb, directory)
    if free < settings.backup_min_free_gb:
        detail = f"{free:.1f} GB free < {settings.backup_min_free_gb} GB"
        logger.warning("daily backup skipped: low disk", extra={"detail": detail})
        return BackupResult("skipped", detail=detail)

    stamp = (now or datetime.now(UTC)).strftime("%Y%m%dT%H%M%SZ")
    final = directory / f"jobmatch-{stamp}.dump"
    partial = final.with_name(final.name + ".partial")
    args, env = _libpq_env(settings.database_url)
    code, output = await _run("pg_dump", *args, "--format=custom", f"--file={partial}", env=env)
    if code != 0:
        await asyncio.to_thread(partial.unlink, missing_ok=True)
        detail = output.decode(errors="replace")[:300]
        logger.error("daily backup failed", extra={"detail": detail})
        return BackupResult("failed", detail=detail)
    # An archive pg_restore cannot list is not a backup.
    code, listing = await _run("pg_restore", "--list", str(partial), env=env)
    if code != 0 or b"TABLE DATA" not in listing:
        await asyncio.to_thread(partial.unlink, missing_ok=True)
        return BackupResult("failed", detail="pg_restore could not list the archive")
    size = await asyncio.to_thread(_finish, partial, final)
    removed = await asyncio.to_thread(prune, directory, settings.backup_keep)
    result = BackupResult("written", str(final), size, tuple(removed))
    logger.info(
        "daily backup written",
        extra={"path": result.path, "size_bytes": result.size_bytes, "removed": removed},
    )
    return result
