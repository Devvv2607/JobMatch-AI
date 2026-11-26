"""The frozen evaluation snapshot (Phase 4 brief, item 1).

A snapshot is a `make backup` dump restored into its own database (`jobmatch_eval_<id>`)
plus a copy of the BM25 index that was current when the dump was taken, so pooling,
judging and metrics never see the daily ingest. Nothing in it changes after creation
except the exclusions applied once at creation:

- is_evergreen jobs (standing pipelines, not openings) and jobs whose company is unknown
  ("Unknown" or empty) are set to status 'expired' in the snapshot database, so no
  retrieval variant returns them (every variant filters on status, BM25 included).

Files (eval/snapshots/<id>/): manifest.json (committed: ids, counts, hashes, versions),
bm25/<version>/ (gitignored: the index). The dump itself stays in backups/ (gitignored);
the manifest records its name and SHA-256.
"""

import asyncio
import hashlib
import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from app.eval import EVAL_DIR

SNAPSHOTS_DIR = EVAL_DIR / "snapshots"
UNKNOWN_COMPANY = r"^\s*(unknown|confidential|undisclosed|not disclosed|n/?a|-)?\s*$"

_EXCLUDE = text("""
UPDATE jobs AS j SET status = 'expired'
FROM companies c
WHERE c.id = j.company_id AND j.status != 'expired'
  AND (j.is_evergreen OR c.name ~* :unknown_company)
RETURNING j.is_evergreen, j.source
""")
_COUNTS = text("""
SELECT count(*) FILTER (WHERE status != 'expired') AS active,
       count(*) FILTER (WHERE status != 'expired' AND duplicate_of IS NULL) AS unique_active,
       count(*) FILTER (WHERE status != 'expired' AND duplicate_of IS NULL
                        AND embedding IS NOT NULL) AS unique_embedded
FROM jobs
""")
_BY_SOURCE = text("""
SELECT source, count(*) AS n FROM jobs
WHERE status != 'expired' AND duplicate_of IS NULL GROUP BY source ORDER BY source
""")
# The corpus fingerprint: every searchable job's id, content and embedding input.
_FINGERPRINT = text("""
SELECT id::text || '|' || content_hash || '|' || coalesce(embedded_hash, '')
FROM jobs WHERE status != 'expired' AND duplicate_of IS NULL ORDER BY id
""")
_LAST_RUN = text("""
SELECT max(finished_at) FROM ingest_runs WHERE status IN ('succeeded', 'partial')
""")


@dataclass(frozen=True)
class Snapshot:
    id: str
    manifest: dict[str, Any]

    @property
    def folder(self) -> Path:
        return SNAPSHOTS_DIR / self.id

    def database_url(self, live_url: str) -> str:
        """The live connection with the snapshot's database (no password is stored)."""
        url = make_url(live_url).set(database=str(self.manifest["database"]))
        return url.render_as_string(hide_password=False)

    @property
    def bm25_dir(self) -> Path:
        return self.folder / "bm25" / str(self.manifest["bm25"]["version"])


def database_name(snapshot_id: str) -> str:
    return "jobmatch_eval_" + snapshot_id.replace("-", "_")


def load_snapshot(snapshot_id: str) -> Snapshot:
    manifest = json.loads((SNAPSHOTS_DIR / snapshot_id / "manifest.json").read_text())
    return Snapshot(snapshot_id, manifest)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def snapshot_engine(snapshot: Snapshot, live_url: str) -> AsyncEngine:
    return create_async_engine(snapshot.database_url(live_url), pool_size=2, max_overflow=0)


async def create_snapshot(
    snapshot_id: str,
    dump: Path,
    live_url: str,
    bm25_root: Path,
    bm25_version: str,
    commit: str,
) -> Snapshot:
    """Restores `dump` into its own database, applies the exclusions, copies the BM25
    index `bm25_version` and writes the manifest. Refuses to overwrite a snapshot."""
    folder = SNAPSHOTS_DIR / snapshot_id
    if folder.exists():
        raise FileExistsError(f"snapshot {snapshot_id} exists: {folder}")
    source_index = bm25_root / bm25_version
    if not source_index.is_dir():
        raise FileNotFoundError(f"BM25 index {source_index} not found")
    name = database_name(snapshot_id)
    live = make_url(live_url)
    target = live.set(database=name)

    admin = create_async_engine(live_url, isolation_level="AUTOCOMMIT")
    async with admin.connect() as conn:
        exists = await conn.scalar(
            text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": name}
        )
        if exists:
            raise FileExistsError(f"database {name} exists")
        await conn.execute(text(f'CREATE DATABASE "{name}"'))
    await admin.dispose()

    env = {**os.environ, "PGPASSWORD": live.password or ""}
    restore = [
        "pg_restore",
        "-h",
        live.host or "db",
        "-p",
        str(live.port or 5432),
        "-U",
        live.username or "jobmatch",
        "-d",
        name,
        "--no-owner",
        "--exit-on-error",
        str(dump),
    ]
    try:
        await asyncio.to_thread(subprocess.run, restore, check=True, env=env)
    except (OSError, subprocess.CalledProcessError):
        # Leave nothing half-made behind: a retry would otherwise find the database.
        admin = create_async_engine(live_url, isolation_level="AUTOCOMMIT")
        async with admin.connect() as conn:
            await conn.execute(text(f'DROP DATABASE IF EXISTS "{name}"'))
        await admin.dispose()
        raise

    engine = create_async_engine(target.render_as_string(hide_password=False))
    async with async_sessionmaker(engine)() as session:
        before = dict((await session.execute(_COUNTS)).one()._mapping)
        indexed = await asyncio.to_thread(_indexed_jobs, source_index)
        if indexed != before["unique_active"]:
            raise ValueError(
                f"BM25 index {bm25_version} has {indexed} jobs, the dump {before['unique_active']}"
                " unique active ones: the index is not the dump's (an ingest ran in between?)"
            )
        excluded = (await session.execute(_EXCLUDE, {"unknown_company": UNKNOWN_COMPANY})).all()
        await session.commit()
        after = dict((await session.execute(_COUNTS)).one()._mapping)
        by_source = {r.source: r.n for r in (await session.execute(_BY_SOURCE)).all()}
        lines = (await session.execute(_FINGERPRINT)).scalars().all()
        last_ingest = await session.scalar(_LAST_RUN)
    await engine.dispose()

    dump_info, bm25_files = await asyncio.to_thread(
        _copy_index, folder, source_index, bm25_version, dump
    )
    manifest: dict[str, Any] = {
        "id": snapshot_id,
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "commit": commit,
        "database": name,
        "dump": dump_info,
        "last_successful_ingest": last_ingest.isoformat() if last_ingest else None,
        "bm25": {"version": bm25_version, "files": bm25_files},
        "counts_before_exclusions": before,
        "excluded": {
            "evergreen": sum(1 for r in excluded if r.is_evergreen),
            "unknown_company": sum(1 for r in excluded if not r.is_evergreen),
            "rule": "status set to 'expired' in the snapshot database: is_evergreen, or "
            f"company name matching {UNKNOWN_COMPANY!r}",
        },
        "counts": after,
        "unique_by_source": by_source,
        "corpus_sha256": hashlib.sha256("\n".join(lines).encode()).hexdigest(),
        "corpus_fingerprint": "sha256 of 'id|content_hash|embedded_hash' per "
        "searchable job (current, not a duplicate), ordered by id",
    }
    await asyncio.to_thread(
        (folder / "manifest.json").write_text, json.dumps(manifest, indent=2) + "\n"
    )
    return Snapshot(snapshot_id, manifest)


def _indexed_jobs(index_dir: Path) -> int:
    return len(json.loads((index_dir / "job_ids.json").read_text()))


def _copy_index(
    folder: Path, source_index: Path, version: str, dump: Path
) -> tuple[dict[str, Any], dict[str, str]]:
    """Copies the index into the snapshot folder; returns (dump info, index file hashes)."""
    folder.mkdir(parents=True)
    index_copy = folder / "bm25" / version
    shutil.copytree(source_index, index_copy)
    dump_info = {"file": dump.name, "sha256": sha256_file(dump), "bytes": dump.stat().st_size}
    files = {p.name: sha256_file(p) for p in sorted(index_copy.iterdir()) if p.is_file()}
    return dump_info, files
