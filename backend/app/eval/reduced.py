"""The reduced eval corpus (Phase 4 brief, item 1) and the CI regression gate (item 8).

The full snapshot stays a local database. CI gets a committed reduced corpus:
eval/snapshots/<id>/reduced/ with companies.csv.gz and jobs.csv.gz (Postgres COPY CSV of
every column, so a load is exact) and manifest.json (sha256 and size of each file, row
counts, the schema revision, how the jobs were chosen). The jobs are every job any variant
ranked for any profile on the full snapshot (runs.jsonl, all 30 ranks) plus distractors:
a seeded sample of the other searchable jobs, proportional to source.

The gate (`python -m app.eval.cli gate`) loads the corpus into its own database (schema
by `alembic upgrade head`), builds a BM25 index from it, runs the query-mode variants
every profile needs for the gated settings, scores NDCG@10 against the committed Gemini
labels (export/judge_labels.jsonl, condensed lists) and fails if any gated variant's mean
drops more than GATE_DROP below the committed baseline (eval/gate/baseline.json). The
numbers are a regression signal on the reduced corpus, not the reported metrics.
"""

import gzip
import hashlib
import io
import json
import os
import random
import subprocess
import sys
from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import psycopg
from sqlalchemy.engine import make_url

from app.eval import EVAL_DIR

FILES = ("companies.csv.gz", "jobs.csv.gz")
GATE_DROP = 0.02
GATE_DATABASE = "jobmatch_eval_reduced"
BASELINE = EVAL_DIR / "gate" / "baseline.json"
# The fast subset: query mode (what a user typing a search gets), the stages of the
# no-rerank search plus the interactive rerank setting chosen in ADR 0003.
GATED = ("query:bm25", "query:vector", "query:fused", "query:rescore", "query:rerank_10_128")
SEARCHABLE = "status <> 'expired' AND duplicate_of IS NULL"


def sync_url(url: str, database: str | None = None) -> str:
    """A psycopg connection string from the app's SQLAlchemy URL."""
    u = make_url(url).set(drivername="postgresql")
    if database:
        u = u.set(database=database)
    return u.render_as_string(hide_password=False)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def choose_jobs(
    pooled: Iterable[str], searchable: dict[str, str], distractors: int, seed: int
) -> tuple[list[str], list[str]]:
    """(pooled jobs still searchable, distractors): `distractors` other searchable jobs,
    split across sources in proportion to their share of the rest, seeded."""
    keep_set = set(pooled) & set(searchable)
    keep = sorted(keep_set)
    by_source: dict[str, list[str]] = defaultdict(list)
    for job_id, source in sorted(searchable.items()):
        if job_id not in keep_set:
            by_source[source].append(job_id)
    rest = sum(len(v) for v in by_source.values())
    rng = random.Random(seed)  # noqa: S311 - a reproducible sample, not security
    chosen: list[str] = []
    for source in sorted(by_source):
        share = round(distractors * len(by_source[source]) / rest) if rest else 0
        chosen += rng.sample(by_source[source], min(share, len(by_source[source])))
    return keep, sorted(chosen)


def _write_gz(path: Path, data: bytes) -> None:
    # mtime=0 and no file name: the same rows give the same bytes, so the same hash.
    with path.open("wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", mtime=0, filename="") as gz:
        gz.write(data)


def export_corpus(url: str, job_ids: list[str], out: Path, meta: dict[str, Any]) -> dict[str, Any]:
    """COPY the chosen jobs and their companies out of the snapshot database."""
    out.mkdir(parents=True, exist_ok=True)
    with psycopg.connect(url) as conn, conn.cursor() as cur:
        cur.execute("CREATE TEMP TABLE chosen (id uuid PRIMARY KEY)")
        with cur.copy("COPY chosen (id) FROM STDIN") as copy:
            for job_id in job_ids:
                copy.write_row((job_id,))
        queries = {
            "companies.csv.gz": "SELECT c.* FROM companies c WHERE c.id IN "
            "(SELECT j.company_id FROM jobs j JOIN chosen USING (id)) ORDER BY c.id",
            "jobs.csv.gz": "SELECT j.* FROM jobs j JOIN chosen USING (id) ORDER BY j.id",
        }
        files: dict[str, Any] = {}
        for name, query in queries.items():
            buffer = io.BytesIO()
            with cur.copy(f"COPY ({query}) TO STDOUT WITH (FORMAT csv, HEADER)") as copy:
                for block in copy:
                    buffer.write(block)
            data = buffer.getvalue()
            _write_gz(out / name, data)
            files[name] = {
                "sha256": sha256(out / name),
                "bytes": (out / name).stat().st_size,
                "rows": cur.rowcount,  # Postgres's own count ("COPY n")
            }
        cur.execute("SELECT version_num FROM alembic_version")
        row = cur.fetchone()
    manifest = {**meta, "schema_revision": row[0] if row else None, "files": files}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def verify(folder: Path) -> dict[str, Any]:
    manifest: dict[str, Any] = json.loads((folder / "manifest.json").read_text())
    for name in FILES:
        if sha256(folder / name) != manifest["files"][name]["sha256"]:
            raise ValueError(f"{folder / name}: sha256 differs from manifest.json")
    return manifest


def _rows_checked(conn: psycopg.Connection[Any], manifest: dict[str, Any]) -> bool:
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT value FROM eval_corpus WHERE key = 'manifest'")
            row = cur.fetchone()
    except psycopg.Error:
        return False
    return row is not None and json.loads(row[0]) == manifest["files"]


def load_corpus(live_url: str, folder: Path, database: str = GATE_DATABASE) -> str:
    """Loads the corpus into `database` (created and migrated if needed; reloaded unless
    it already holds exactly this corpus). Returns the database's SQLAlchemy URL."""
    manifest = verify(folder)
    target = make_url(live_url).set(database=database)
    with psycopg.connect(sync_url(live_url), autocommit=True) as admin:
        exists = admin.execute("SELECT 1 FROM pg_database WHERE datname = %s", (database,))
        if exists.fetchone():
            with psycopg.connect(sync_url(live_url, database)) as conn:
                if _rows_checked(conn, manifest):
                    return target.render_as_string(hide_password=False)
            admin.execute(f'DROP DATABASE "{database}"')
        admin.execute(f'CREATE DATABASE "{database}"')
    env = {**os.environ, "DATABASE_URL": target.render_as_string(hide_password=False)}
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], check=True, env=env)
    with psycopg.connect(sync_url(live_url, database)) as conn, conn.cursor() as cur:
        for name, table in (("companies.csv.gz", "companies"), ("jobs.csv.gz", "jobs")):
            data = gzip.decompress((folder / name).read_bytes())
            header = data.split(b"\n", 1)[0].decode()
            with cur.copy(f"COPY {table} ({header}) FROM STDIN WITH (FORMAT csv, HEADER)") as copy:
                copy.write(data)
        cur.execute("CREATE TABLE eval_corpus (key text PRIMARY KEY, value text)")
        cur.execute(
            "INSERT INTO eval_corpus VALUES ('manifest', %s)", (json.dumps(manifest["files"]),)
        )
        cur.execute("ANALYZE")
    return target.render_as_string(hide_password=False)


def gate_check(
    scores: dict[str, float], baseline: dict[str, Any], drop: float = GATE_DROP
) -> list[str]:
    """Failures: each gated variant whose mean NDCG@10 fell more than `drop` below the
    baseline, or that the run is missing."""
    failures = []
    for variant, base in baseline["ndcg10"].items():
        now = scores.get(variant)
        if now is None:
            failures.append(f"{variant}: not measured")
        elif now < base - drop:
            failures.append(f"{variant}: NDCG@10 {now:.4f} < baseline {base:.4f} - {drop}")
    return failures
