"""Search latency on the live pool: per stage, sequential, then under concurrency.

Usage (make bench-search): python -m scripts.bench_search [--out ../docs/bench]

What it measures, all in one process with the real models and database (no HTTP, no
auth, the response cache off):
  1. sequential: every query in QUERIES x every rule set, one at a time; p50/p95 per stage
  2. rerank sweep: the same, for each (rerank top M, tokens per pair) setting
  3. concurrency: the default settings with C searches in flight at once; p50/p95 of the
     whole search. Both models run on one thread per process, so this shows queueing.
  4. EXPLAIN ANALYZE of the vector query, without and with a selective filter.

Writes <out>/search-<UTC date>.md and .json and prints the markdown.
"""

import argparse
import asyncio
import json
import os
import platform
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func, literal_column, select, text

from app.core.config import Settings, get_settings
from app.core.db import SessionLocal, engine
from app.core.redis import redis
from app.models import Job
from app.retrieval.rules import (
    DealbreakerRule,
    Rule,
    WorkEligibility,
    WorkplaceRule,
    allowed,
    base_pool,
)
from app.retrieval.schemas import SearchRequest
from app.retrieval.scoring import SearchProfile
from app.retrieval.service import SearchEngine, build_engine, search

QUERIES = [
    "senior python backend engineer",
    "data engineer spark airflow",
    "frontend engineer react typescript",
    "machine learning engineer",
    "devops engineer kubernetes terraform",
    "product designer",
    "site reliability engineer",
    "android developer kotlin",
    "security engineer",
    "engineering manager",
    "golang distributed systems",
    "analytics engineer dbt sql",
    "full stack developer node",
    "ios engineer swift",
    "staff software engineer infrastructure",
    "technical writer",
    "solutions engineer",
    "data scientist",
    "embedded c++ engineer",
    "customer support specialist",
]
PROFILE = SearchProfile(skills=["Python", "PostgreSQL", "Docker", "AWS"], years_experience=5)
RULE_SETS: dict[str, list[DealbreakerRule]] = {
    "none": [],
    "IN eligible": [WorkEligibility(country="IN")],
    "IN eligible + remote (strict)": [
        WorkEligibility(country="IN"),
        WorkplaceRule(allowed=["remote"], strict=True),
    ],
}
SWEEP = [(10, 128), (20, 128), (30, 128), (10, 256), (20, 256), (30, 256)]
CONCURRENCY = [1, 4, 8]


def pct(values: list[float], q: float) -> float:
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, round(q * (len(ordered) - 1))))
    return round(ordered[index], 1)


def summarise(samples: list[dict[str, float]]) -> dict[str, dict[str, float]]:
    """p50/p95 per stage, over the searches that ran it ("ruled_out" runs only with
    dealbreakers); `n` says how many that was."""
    stages = list(dict.fromkeys(stage for sample in samples for stage in sample))
    stages.sort(key=lambda stage: stage == "total")  # total last
    out: dict[str, dict[str, float]] = {}
    for stage in stages:
        values = [s[stage] for s in samples if stage in s]
        out[stage] = {"n": len(values), "p50": pct(values, 0.5), "p95": pct(values, 0.95)}
    return out


def requests() -> list[tuple[str, SearchRequest]]:
    return [
        (name, SearchRequest(query=q, profile=PROFILE, rules=rules, limit=10))
        for name, rules in RULE_SETS.items()
        for q in QUERIES
    ]


async def run_one(
    engine_: SearchEngine, request: SearchRequest, settings: Settings
) -> dict[str, float]:
    async with SessionLocal() as session:
        response = await search(session, engine_, request, settings)
        await session.rollback()
    return response.timings_ms


async def sequential(engine_: SearchEngine, settings: Settings) -> list[dict[str, float]]:
    return [await run_one(engine_, request, settings) for _, request in requests()]


async def concurrent(engine_: SearchEngine, settings: Settings, level: int) -> list[float]:
    work = [request for _, request in requests()][: max(level * 4, 12)]
    gate = asyncio.Semaphore(level)
    latencies: list[float] = []

    async def one(request: SearchRequest) -> None:
        async with gate:
            started = time.perf_counter()
            await run_one(engine_, request, settings)
            latencies.append((time.perf_counter() - started) * 1000)

    await asyncio.gather(*(one(r) for r in work))
    return latencies


async def explain_vector(engine_: SearchEngine, settings: Settings) -> dict[str, str]:
    vector = await engine_.on_model_thread(engine_.embedder.embed_query, QUERIES[0])
    plans: dict[str, str] = {}
    cases: dict[str, list[Rule]] = {
        "unfiltered (pool only)": [],
        "filtered (IN eligible + remote strict)": list(RULE_SETS["IN eligible + remote (strict)"]),
    }
    for name, rules in cases.items():
        where = allowed(rules) if rules else base_pool()
        # The vector as a literal (floats only); everything else stays a bound parameter,
        # compiled exactly as the search sends it (array casts included).
        literal = "'[" + ",".join(f"{x:.6f}" for x in vector) + "]'::vector"
        distance = Job.embedding.op("<=>")(literal_column(literal))
        statement = (
            select(Job.id).where(where, Job.embedding.is_not(None)).order_by(distance).limit(100)
        )
        async with SessionLocal() as session:
            await session.execute(
                text(f"SET LOCAL hnsw.ef_search = {settings.search_hnsw_ef_search}")
            )
            await session.execute(text("SET LOCAL hnsw.iterative_scan = relaxed_order"))
            conn = await session.connection()
            compiled = statement.compile(
                dialect=conn.dialect, compile_kwargs={"render_postcompile": True}
            )
            result = await conn.exec_driver_sql(
                "EXPLAIN (ANALYZE, BUFFERS) " + compiled.string, compiled.params
            )
            rows = result.all()
            await session.rollback()
        plans[name] = "\n".join(row[0] for row in rows)
    return plans


async def main(out: Path, explain_only: bool) -> int:
    base = get_settings()
    settings = base.model_copy(update={"search_cache_seconds": 0})
    report: dict[str, Any] = {
        "when": datetime.now(UTC).isoformat(timespec="seconds"),
        "hardware": {
            "cpus_visible": os.cpu_count(),
            "platform": platform.platform(),
            "python": platform.python_version(),
        },
        "settings": {
            k: getattr(settings, k)
            for k in (
                "search_candidates",
                "search_rerank_top",
                "rerank_max_tokens",
                "search_hnsw_ef_search",
                "reranker_threads",
                "embedding_threads",
            )
        },
        "queries": len(QUERIES),
        "rule_sets": list(RULE_SETS),
    }
    default_engine = build_engine(settings, redis)
    index = await default_engine.bm25_index()
    async with SessionLocal() as session:
        pool = await session.scalar(select(func.count()).select_from(Job).where(base_pool()))
    report["pool"] = {"jobs": pool, "bm25_version": index.version if index else None}

    report["explain"] = await explain_vector(default_engine, settings)
    if explain_only:
        print(render(report))
        default_engine.close()
        return 0

    # Warm-up: model sessions, the HNSW index pages and the connection pool.
    for _, request in requests()[:3]:
        await run_one(default_engine, request, settings)

    # The report is rewritten after each part, so a failure keeps what was measured.
    report["sequential"] = summarise(await sequential(default_engine, settings))
    await save(out, report)

    sweep: dict[str, Any] = {}
    for top, tokens in SWEEP:
        swept = settings.model_copy(update={"search_rerank_top": top, "rerank_max_tokens": tokens})
        engine_ = (
            build_engine(swept, redis) if tokens != settings.rerank_max_tokens else default_engine
        )
        samples = await sequential(engine_, swept)
        stats = summarise(samples)
        sweep[f"top {top} @ {tokens} tokens"] = {"rerank": stats["rerank"], "total": stats["total"]}
        if engine_ is not default_engine:
            engine_.close()
        report["rerank_sweep"] = sweep
        await save(out, report)

    report["concurrency"] = {}
    for level in CONCURRENCY:
        latencies = await concurrent(default_engine, settings, level)
        report["concurrency"][str(level)] = {
            "requests": len(latencies),
            "p50": pct(latencies, 0.5),
            "p95": pct(latencies, 0.95),
        }
        await save(out, report)
    default_engine.close()
    print(render(report))
    return 0


async def save(out: Path, report: dict[str, Any]) -> None:
    await asyncio.to_thread(write, out, report, render(report))


def write(out: Path, report: dict[str, Any], markdown: str) -> None:
    out.mkdir(parents=True, exist_ok=True)
    stem = out / f"search-{datetime.now(UTC):%Y-%m-%d}"
    stem.with_suffix(".json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    stem.with_suffix(".md").write_text(markdown, encoding="utf-8")


def render(report: dict[str, Any]) -> str:
    lines = [
        f"# Search latency, {report['when']}",
        "",
        "Generated by `make bench-search` (scripts/bench_search.py). One process, real models"
        " and database, no HTTP, response cache off. Milliseconds.",
        "",
        f"- Hardware: {report['hardware']['cpus_visible']} CPUs visible to the container,"
        f" {report['hardware']['platform']}, Python {report['hardware']['python']}",
        f"- Pool: {report['pool']['jobs']} jobs; BM25 index {report['pool']['bm25_version']}",
        f"- Settings: {json.dumps(report['settings'])}",
        f"- Requests: {report['queries']} queries x {len(report['rule_sets'])} rule sets"
        f" ({', '.join(report['rule_sets'])}), each with the same profile",
        "",
        "## Sequential, per stage (default settings)",
        "",
        "| stage | searches | p50 | p95 |",
        "|---|---:|---:|---:|",
    ]
    lines += [
        f"| {k} | {v['n']} | {v['p50']} | {v['p95']} |"
        for k, v in report.get("sequential", {}).items()
    ]
    lines += [
        "",
        "## Rerank sweep (sequential)",
        "",
        "| setting | rerank p50 | rerank p95 | total p50 | total p95 |",
        "|---|---:|---:|---:|---:|",
    ]
    lines += [
        f"| {k} | {v['rerank']['p50']} | {v['rerank']['p95']} | {v['total']['p50']} |"
        f" {v['total']['p95']} |"
        for k, v in report.get("rerank_sweep", {}).items()
    ]
    lines += [
        "",
        "## Concurrency (default settings, whole search)",
        "",
        "| in flight | requests | p50 | p95 |",
        "|---:|---:|---:|---:|",
    ]
    lines += [
        f"| {k} | {v['requests']} | {v['p50']} | {v['p95']} |"
        for k, v in report.get("concurrency", {}).items()
    ]
    lines += ["", "## EXPLAIN ANALYZE, vector query (top 100)", ""]
    for name, plan in report["explain"].items():
        lines += [f"### {name}", "", "```", plan, "```", ""]
    return "\n".join(lines)


def cli() -> int:
    parser = argparse.ArgumentParser(prog="python -m scripts.bench_search")
    parser.add_argument("--out", default="/app/bench-out", type=Path)
    parser.add_argument("--explain-only", action="store_true")
    args = parser.parse_args()

    async def run() -> int:
        try:
            return await main(args.out, args.explain_only)
        finally:
            await engine.dispose()
            await redis.aclose()

    return asyncio.run(run())


if __name__ == "__main__":
    raise SystemExit(cli())
