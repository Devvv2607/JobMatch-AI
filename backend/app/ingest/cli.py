"""Ingestion commands.

python -m app.ingest.cli run [--sources greenhouse,lever,ashby,remotive]
python -m app.ingest.cli report [--country IN]
python -m app.ingest.cli check-boards
python -m app.ingest.cli embed
python -m app.ingest.cli bm25
python -m app.ingest.cli retag
python -m app.ingest.cli dedup [--dry-run]
"""

import argparse
import asyncio
import json
import sys
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from sqlalchemy import text

from app.core.config import get_settings
from app.core.db import SessionLocal, engine
from app.core.logging import configure_logging
from app.core.redis import redis
from app.ingest.companies import load_companies
from app.ingest.lock import IngestLockedError, ingest_lock
from app.ingest.runner import (
    ADAPTERS,
    ALL_SOURCES,
    build_http_client,
    peak_rss_mib,
    run_ingest,
)
from app.ingest.sources.base import SourceError
from app.retrieval.bm25 import rebuild as rebuild_bm25


async def cmd_run(sources: list[str]) -> int:
    from app.ml.embedder import OnnxEmbedder  # loaded only when embedding is needed

    settings = get_settings()
    embedder = OnnxEmbedder(
        Path(settings.embedding_model_dir),
        settings.embedding_model_file,
        settings.embedding_threads,
    )
    async with (
        ingest_lock(redis, settings.ingest_lock_ttl_seconds, "cli run"),
        build_http_client(settings) as http,
    ):
        summary = await run_ingest(
            SessionLocal, http, embedder, load_companies(), settings, sources=sources
        )
    print(
        json.dumps(
            {
                "run_id": str(summary.run_id),
                "seconds": summary.seconds,
                "embedded": summary.embedded,
                "stale_marked": summary.stale,
                "duplicates_marked": summary.duplicates,
                "sources": {
                    name: {
                        "status": run.status,
                        "boards_ok": run.boards_ok,
                        "boards_failed": run.boards_failed,
                        "fetched": run.fetched,
                        "new": run.new,
                        "updated": run.updated,
                        "unchanged": run.unchanged,
                        "expired": run.expired,
                        "skipped_postings": run.skipped,
                        "note": run.note,
                        "embedded": run.embedded,
                        "embed_pending": run.embed_pending,
                        "error": run.error,
                    }
                    for name, run in summary.sources.items()
                },
            },
            indent=2,
        )
    )
    return 0


async def cmd_embed() -> int:
    """Prepare the embedding input, embed only what is pending (no fetching), then dedup.
    Resumes an interrupted run, and applies a new embedding recipe or dedup setting."""
    from app.ingest.dedup import deduplicate, text_rules
    from app.ingest.embed import embed_pending, pending_by_source, prepare_embedding_input
    from app.ml.embedder import OnnxEmbedder

    settings = get_settings()
    embedder = OnnxEmbedder(
        Path(settings.embedding_model_dir),
        settings.embedding_model_file,
        settings.embedding_threads,
    )
    started = time.perf_counter()
    async with (
        ingest_lock(redis, settings.ingest_lock_ttl_seconds, "cli embed"),
        SessionLocal() as session,
    ):
        prepared = await prepare_embedding_input(
            session,
            min_share=settings.ingest_boilerplate_min_share,
            min_postings=settings.ingest_boilerplate_min_postings,
        )
        before = await pending_by_source(session)
        done: dict[str, int] = {}
        embedded = await embed_pending(session, embedder, done)
        embed_seconds = round(time.perf_counter() - started, 1)
        duplicates = await deduplicate(session, text_rules(settings))
        await session.commit()
        after = await pending_by_source(session)
        bm25_version, bm25_documents, bm25_seconds = await rebuild_bm25(
            session, redis, Path(settings.bm25_index_dir)
        )
    print(
        json.dumps(
            {
                "inputs_changed": prepared,
                "pending_before": before,
                "embedded": embedded,
                "embedded_by_source": done,
                "pending_after": after,
                "embed_seconds": embed_seconds,
                "total_seconds": round(time.perf_counter() - started, 1),
                "duplicates_marked": duplicates,
                "bm25": {
                    "version": bm25_version,
                    "documents": bm25_documents,
                    "seconds": bm25_seconds,
                },
                "peak_rss_mib": peak_rss_mib(),
            },
            indent=2,
        )
    )
    return 0 if not after else 1


async def cmd_bm25() -> int:
    """Rebuild and publish the BM25 index from the current pool (no fetching)."""
    async with SessionLocal() as session:
        version, documents, seconds = await rebuild_bm25(
            session, redis, Path(get_settings().bm25_index_dir)
        )
    print(json.dumps({"version": version, "documents": documents, "seconds": seconds}))
    return 0


_RETAG_BATCH = 2000


_TEXT_MARKS = text("""
SELECT d.id, d.duplicate_of, d.duplicate_reason, d.title, d.source, d.location,
       c.name AS company
FROM jobs d JOIN companies c ON c.id = d.company_id
WHERE d.status != 'expired' AND d.duplicate_reason IN ('cross_source', 'near_duplicate_text')
""")
_BODIES = text("""
SELECT id, source, coalesce(search_text, description) AS body FROM jobs WHERE id = ANY(:ids)
""")


async def cmd_dedup(dry_run: bool) -> int:
    """Recompute duplicates with the current rules. --dry-run (read-only) compares the
    text pass's current marks with what the rules would mark now and lists every merge
    that would be undone or moved, with its score against the posting it is hidden under.
    Without --dry-run: dedup, commit, rebuild the BM25 index (takes the ingest lock)."""
    from app.ingest.dedup import (
        containment,
        deduplicate,
        find_text_duplicates,
        jaccard,
        text_rules,
        words,
    )

    settings = get_settings()
    rules = text_rules(settings)
    if rules is None:
        print("near-duplicate pass is off (INGEST_NEAR_DUPLICATES_ENABLED=false)")
        return 1
    if not dry_run:
        async with (
            ingest_lock(redis, settings.ingest_lock_ttl_seconds, "cli dedup"),
            SessionLocal() as session,
        ):
            counts = await deduplicate(session, rules)
            await session.commit()
            version, documents, seconds = await rebuild_bm25(
                session, redis, Path(settings.bm25_index_dir)
            )
        print(json.dumps({"duplicates_marked": counts, "bm25": [version, documents, seconds]}))
        return 0

    async with SessionLocal() as session:
        current = {r.id: r for r in (await session.execute(_TEXT_MARKS)).all()}
        new = await find_text_duplicates(session, rules, include_text_marked=True)
        undone = [r for i, r in current.items() if i not in new.canonical_of]
        moved = [
            r
            for i, r in current.items()
            if i in new.canonical_of and new.canonical_of[i][0] != r.duplicate_of
        ]
        added = [i for i in new.canonical_of if i not in current]
        ids = list({*(r.id for r in undone + moved), *(r.duplicate_of for r in undone + moved)})
        bodies = {r.id: r for r in (await session.execute(_BODIES, {"ids": ids})).all()}

    def score(a: Any, b: Any) -> str:
        wa, wb = words(bodies[a].body or ""), words(bodies[b].body or "")
        if bodies[a].source != bodies[b].source:
            return f"containment {containment(wa, wb):.3f}"
        return f"jaccard {jaccard(wa, wb):.3f}"

    print(
        f"text-pass marks now: {len(current)}; under the rules now: {len(new.canonical_of)} "
        f"(undone {len(undone)}, moved to another canonical {len(moved)}, new {len(added)})"
    )
    for label, rows in (("UNDONE", undone), ("MOVED", moved)):
        for r in sorted(rows, key=lambda r: (r.company, r.title)):
            print(
                f"{label}	{r.id}	{r.duplicate_reason}	{r.company}	{r.title[:60]}	"
                f"{r.source}: {r.location[:40]}	vs kept {r.duplicate_of}: "
                f"{score(r.duplicate_of, r.id)}"
            )
    return 0


async def cmd_retag() -> int:
    """Recomputes engagement_type and poster_type for every job from its stored title,
    description, employment type and company name: the same functions ingest uses
    (app/ingest/tags.py), for rows ingested before the tags existed or rules changed.
    Takes the ingest lock (it rewrites job rows)."""
    from sqlalchemy import select, update

    from app.ingest.tags import engagement_type, poster_type
    from app.models import Company, Job

    settings = get_settings()
    changed = {"engagement_type": 0, "poster_type": 0}
    seen = 0
    async with ingest_lock(redis, settings.ingest_lock_ttl_seconds, "retag"):
        last = None
        while True:
            async with SessionLocal() as session:
                query = (
                    select(
                        Job.id,
                        Job.title,
                        Job.description,
                        Job.employment_type,
                        Job.engagement_type,
                        Job.poster_type,
                        Company.name,
                    )
                    .join(Company, Company.id == Job.company_id)
                    .order_by(Job.id)
                    .limit(_RETAG_BATCH)
                )
                if last is not None:
                    query = query.where(Job.id > last)
                rows = (await session.execute(query)).all()
                if not rows:
                    break
                updates = []
                for r in rows:
                    engagement = engagement_type(r.employment_type, r.title, r.description, r.name)
                    poster = poster_type(r.name, r.description)
                    if (engagement, poster) != (r.engagement_type, r.poster_type):
                        changed["engagement_type"] += engagement != r.engagement_type
                        changed["poster_type"] += poster != r.poster_type
                        updates.append(
                            {"id": r.id, "engagement_type": engagement, "poster_type": poster}
                        )
                if updates:
                    await session.execute(update(Job), updates)
                    await session.commit()
                seen += len(rows)
                last = rows[-1].id
    print(json.dumps({"jobs": seen, "changed": changed}))
    return 0


_REPORT_SQL = {
    "totals": """
        SELECT count(*) FILTER (WHERE status != 'expired') AS active,
               count(*) FILTER (
                   WHERE status != 'expired' AND duplicate_of IS NULL
               ) AS unique_active,
               count(*) FILTER (WHERE status = 'expired') AS expired,
               count(*) FILTER (WHERE embedding IS NOT NULL AND status != 'expired') AS embedded
        FROM jobs""",
    "by_source": """
        SELECT source, count(*) AS active, count(*) FILTER (WHERE duplicate_of IS NULL) AS unique
        FROM jobs WHERE status != 'expired' GROUP BY source ORDER BY source""",
    "by_status": """
        SELECT status, count(*) AS jobs FROM jobs GROUP BY status ORDER BY status""",
    "eligibility": """
        SELECT CASE
                 WHEN eligibility_scope = 'worldwide' THEN 'eligible'
                 WHEN eligibility_scope = 'listed' AND :country = ANY(work_countries)
                   THEN 'eligible'
                 WHEN eligibility_scope = 'listed' THEN 'ineligible'
                 ELSE 'unknown'
               END AS eligibility,
               count(*) AS jobs
        FROM jobs WHERE status != 'expired' AND duplicate_of IS NULL
        GROUP BY 1 ORDER BY 1""",
    "eligibility_by_source": """
        SELECT source,
               count(*) FILTER (
                   WHERE eligibility_scope = 'worldwide'
                      OR (eligibility_scope = 'listed' AND :country = ANY(work_countries))
               ) AS eligible,
               count(*) FILTER (WHERE eligibility_scope = 'unknown') AS unknown,
               count(*) FILTER (WHERE eligibility_scope = 'listed'
                                 AND NOT :country = ANY(work_countries)) AS ineligible,
               count(*) AS total
        FROM jobs WHERE status != 'expired' AND duplicate_of IS NULL
        GROUP BY source ORDER BY source""",
    "eligibility_rules": """
        SELECT eligibility_source AS rule, count(*) AS jobs
        FROM jobs WHERE status != 'expired' AND duplicate_of IS NULL
        GROUP BY 1 ORDER BY 2 DESC""",
    "unknown_location_phrases": """
        SELECT coalesce(nullif(location, ''), '(empty)') AS location, count(*) AS jobs
        FROM jobs WHERE status != 'expired' AND duplicate_of IS NULL
          AND eligibility_scope = 'unknown'
        GROUP BY 1 ORDER BY 2 DESC LIMIT 10""",
    "duplicates": """
        SELECT duplicate_reason AS reason, count(*) AS jobs
        FROM jobs WHERE duplicate_of IS NOT NULL AND status != 'expired'
        GROUP BY 1 ORDER BY 1""",
    "coverage": """
        SELECT count(*) FILTER (
                   WHERE salary_min_usd IS NOT NULL OR salary_max_usd IS NOT NULL
               ) AS with_salary,
               count(*) FILTER (WHERE cardinality(skills) > 0) AS with_skills,
               count(*) FILTER (WHERE remote_policy = 'remote') AS remote,
               count(*) FILTER (WHERE remote_policy = 'hybrid') AS hybrid,
               count(*) FILTER (WHERE remote_policy = 'onsite') AS onsite,
               count(*) FILTER (WHERE remote_policy = 'unknown') AS workplace_unknown,
               count(*) AS total
        FROM jobs WHERE status != 'expired' AND duplicate_of IS NULL""",
    "last_run": """
        SELECT source, status, boards_ok, boards_failed, fetched, new, updated, unchanged,
               expired, skipped, embedded, embed_pending, error, failures, note,
               round(extract(epoch FROM finished_at - started_at)::numeric, 1) AS seconds
        FROM ingest_runs
        WHERE run_id = (SELECT run_id FROM ingest_runs ORDER BY started_at DESC LIMIT 1)
        ORDER BY source""",
}


async def cmd_report(country: str) -> int:
    report: dict[str, Any] = {"country": country.upper()}
    async with engine.connect() as conn:
        for name, sql in _REPORT_SQL.items():
            rows = (await conn.execute(text(sql), {"country": country.upper()})).mappings().all()
            report[name] = [dict(r) for r in rows]
    print(json.dumps(report, indent=2, default=str))
    return 0


async def cmd_check_boards() -> int:
    settings = get_settings()
    dead = 0
    async with build_http_client(settings) as http:
        for entry in load_companies():
            try:
                result = await ADAPTERS[entry.ats].fetch(http, entry.token, entry.name)
                status = f"live  {len(result.postings):4d} postings"
                if not result.postings:
                    status, dead = "EMPTY (no postings)", dead + 1
            except SourceError as exc:
                status, dead = f"DEAD  {exc}", dead + 1
            print(f"{entry.ats:10} {entry.token:16} {status}", flush=True)
            await asyncio.sleep(0.25)
    print(f"{dead} dead or empty of {len(load_companies())}")
    return 1 if dead else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.ingest.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="run one ingestion")
    run.add_argument("--sources", default=",".join(ALL_SOURCES))
    report = sub.add_parser("report", help="print the pool report")
    report.add_argument("--country", default="IN")
    sub.add_parser("check-boards", help="check every board token in companies.yaml")
    sub.add_parser(
        "embed", help="prepare embedding input, embed pending jobs (no fetching), then dedup"
    )
    sub.add_parser("bm25", help="rebuild and publish the BM25 index (no fetching)")
    sub.add_parser("retag", help="recompute engagement and poster tags for every job")
    dedup = sub.add_parser("dedup", help="recompute duplicates (no fetching), rebuild BM25")
    dedup.add_argument("--dry-run", action="store_true", help="read-only: list what changes")
    args = parser.parse_args(argv)

    sources = (
        [s.strip() for s in args.sources.split(",") if s.strip()] if args.command == "run" else []
    )
    if unknown := set(sources) - set(ALL_SOURCES):
        parser.error(f"unknown sources: {sorted(unknown)}")

    configure_logging(get_settings().log_level)
    commands: dict[str, Callable[[], Awaitable[int]]] = {
        "run": lambda: cmd_run(sources),
        "report": lambda: cmd_report(args.country),
        "check-boards": cmd_check_boards,
        "embed": cmd_embed,
        "bm25": cmd_bm25,
        "retag": cmd_retag,
        "dedup": lambda: cmd_dedup(args.dry_run),
    }
    command = commands[args.command]

    async def dispatch() -> int:
        try:
            return await command()
        except IngestLockedError as exc:
            print(f"not started: {exc}", file=sys.stderr)
            return 2
        finally:
            await engine.dispose()
            await redis.aclose()

    return asyncio.run(dispatch())


if __name__ == "__main__":
    sys.exit(main())
