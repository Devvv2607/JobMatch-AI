"""Evaluation commands (Phase 4).

python -m app.eval.cli profiles                 validate and list eval/profiles
python -m app.eval.cli demo [--set demo]        a throwaway sample to try the labelling tool
python -m app.eval.cli label --set NAME         the labelling tool (http://127.0.0.1:8765)
python -m app.eval.cli snapshot --id ID --dump FILE --commit SHA   freeze the pool
python -m app.eval.cli pool --set NAME --snapshot ID   run every variant, pool the pairs
python -m app.eval.cli judge --set NAME [--sample N]   LLM-judge every pair not judged yet
python -m app.eval.cli export --set NAME         the committed form (no posting text)
python -m app.eval.cli rebuild-pairs --set NAME  pairs.jsonl again from the snapshot
python -m app.eval.cli summary --set NAME       label counts by source, kappa on the blind set
python -m app.eval.cli agreement --set NAME     judge vs judge: kappa, confusion, themes, majority
python -m app.eval.cli cowork-export --set NAME  Claude Cowork grading sheets (eval/private/cowork)
python -m app.eval.cli cowork-import --set NAME --file F   check and import one filled sheet
"""

import argparse
import asyncio
import random
import shutil
import sys
import uuid
from typing import Any

from sqlalchemy import select

from app.eval import EVAL_DIR
from app.eval.pairs import EvalPair, JudgeRecord, load_judge, load_pairs, pair_id, write_jsonl
from app.eval.profiles import load_profiles

LABELS_DIR = EVAL_DIR / "labels"


def cmd_profiles() -> int:
    profiles = load_profiles()
    print(f"{len(profiles)} profiles in {EVAL_DIR / 'profiles'}")
    for p in profiles.values():
        p.search_request()  # the request must validate as the API would accept it
        rules = ", ".join(r.kind for r in p.rules) or "-"
        print(
            f"{p.id}  {p.region:6} {p.experience_band:7} {p.field:15} "
            f"{p.lives_in:24} q={p.query!r}  rules: {rules}"
        )
    return 0


async def cmd_demo(name: str, per_profile: int, profile_ids: list[str], seed: int) -> int:
    """Random active jobs (not search results) for a few profiles, plus FAKE judge labels
    so the second phase can be tried. Written under eval/labels/<name>/ (gitignored
    when the name starts with "demo")."""
    from app.core.db import SessionLocal, engine
    from app.eval.cards import job_card
    from app.models import Company, Job

    folder = LABELS_DIR / name
    if folder.exists():
        shutil.rmtree(folder)  # a demo is throwaway by definition
    folder.mkdir(parents=True)
    rng = random.Random(seed)  # noqa: S311 - a reproducible sample, not security
    async with SessionLocal() as session:
        rows = (
            await session.execute(
                select(Job, Company)
                .join(Company, Company.id == Job.company_id)
                .where(Job.status != "expired", Job.duplicate_of.is_(None))
                .order_by(Job.id)
            )
        ).all()
    await engine.dispose()
    pairs: list[EvalPair] = []
    for pid in profile_ids:
        for job, company in rng.sample(rows, per_profile):
            card = job_card(job, company)
            pairs.append(
                EvalPair(
                    pair_id=pair_id(pid, card.job_id),
                    profile_id=pid,
                    job=card,
                    variants={"demo_random": 0},
                    strata={"source": card.source},
                )
            )
    write_jsonl(folder / "pairs.jsonl", pairs)
    fake = [
        JudgeRecord(
            pair_id=p.pair_id,
            label=rng.randint(0, 3),
            reason="DEMO: a random label, not a judgement.",
            confidence=rng.choice(["low", "medium", "high"]),
            provider="demo",
            model="random",
            prompt="none",
        )
        for p in pairs
    ]
    write_jsonl(folder / "judge.jsonl", fake)
    print(f"wrote {len(pairs)} demo pairs and fake judge labels to {folder}")
    return 0


def cmd_label(name: str, blind: int, host: str, port: int) -> int:
    import uvicorn

    from app.eval.labelling import create_app, open_session

    session = open_session(LABELS_DIR / name, blind_size=blind)
    p = session.progress()
    print(
        f"set {name}: {p['done']}/{p['total']} labelled, blind {p['blind_done']}/"
        f"{p['blind_total']}; log {session.log}\nopen http://127.0.0.1:{port} "
        "(Ctrl+C to stop; every key press is already saved)",
        flush=True,
    )
    uvicorn.run(create_app(session), host=host, port=port, log_level="warning")
    return 0


async def cmd_snapshot(snapshot_id: str, dump: str, commit: str) -> int:
    """Freeze: restore a `make backup` dump into its own database, copy the current BM25
    index, apply the eval exclusions, write eval/snapshots/<id>/manifest.json."""
    import json
    from pathlib import Path

    from app.core.config import get_settings
    from app.core.redis import redis
    from app.eval.snapshot import create_snapshot
    from app.retrieval.bm25 import VERSION_KEY

    settings = get_settings()
    version = await redis.get(VERSION_KEY)
    await redis.aclose()
    if isinstance(version, bytes):
        version = version.decode()
    if not version:
        print("no current BM25 version in Redis", file=sys.stderr)
        return 1
    snapshot = await create_snapshot(
        snapshot_id,
        Path(dump),
        settings.database_url,
        Path(settings.bm25_index_dir),
        str(version),
        commit,
    )
    print(json.dumps(snapshot.manifest, indent=2))
    return 0


async def cmd_pool(name: str, snapshot_id: str, per_profile: int, profile_ids: list[str]) -> int:
    """Run every variant for every profile on the snapshot and write the pooled pairs:
    eval/labels/<name>/pairs.jsonl, runs.jsonl (every ranking) and pool.json (summary)."""
    import json
    import time

    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.core.config import get_settings
    from app.core.redis import redis
    from app.eval.cards import job_card
    from app.eval.pooling import FixedBm25, job_facts, pool_summary, run_variants, select_pool
    from app.eval.snapshot import load_snapshot, snapshot_engine
    from app.models import Company, Job
    from app.retrieval.service import build_engine

    folder = LABELS_DIR / name
    if (folder / "pairs.jsonl").exists():
        print(f"{folder}/pairs.jsonl exists; pick another set name", file=sys.stderr)
        return 1
    settings = get_settings()
    snapshot = load_snapshot(snapshot_id)
    profiles = load_profiles()
    if profile_ids:
        profiles = {pid: profiles[pid] for pid in profile_ids}
    search_engine = build_engine(settings, redis)
    search_engine.bm25 = FixedBm25(snapshot.bm25_dir)
    db = snapshot_engine(snapshot, settings.database_url)
    runs: dict[str, dict[str, list[str]]] = {}
    seconds: dict[str, float] = {}
    async with async_sessionmaker(db)() as session:
        for pid, profile in profiles.items():
            started = time.perf_counter()
            runs[pid] = await run_variants(session, search_engine, profile, settings)
            seconds[pid] = round(time.perf_counter() - started, 2)
            print(f"{pid}: {len(runs[pid])} variants in {seconds[pid]} s", flush=True)
        every_id = {j for rankings in runs.values() for ids in rankings.values() for j in ids}
        facts = await job_facts(session, every_id)
        chosen = {pid: select_pool(runs[pid], facts, per_profile=per_profile) for pid in runs}
        wanted = [uuid.UUID(c.job_id) for items in chosen.values() for c, _ in items]
        rows = (
            await session.execute(
                select(Job, Company)
                .join(Company, Company.id == Job.company_id)
                .where(Job.id.in_(wanted))
            )
        ).all()
    await db.dispose()
    search_engine.close()
    await redis.aclose()
    cards = {str(job.id): job_card(job, company) for job, company in rows}

    pairs: list[EvalPair] = []
    for pid, items in chosen.items():
        for c, over in items:
            f = facts[c.job_id]
            pairs.append(
                EvalPair(
                    pair_id=pair_id(pid, c.job_id),
                    profile_id=pid,
                    job=cards[c.job_id],
                    variants=dict(sorted(c.variants.items())),
                    strata={
                        "source": f.source,
                        "employment": f.engagement,
                        "poster": f.poster,
                        "best_rank": str(min(c.variants.values())),
                        "over_cap": "yes" if over else "no",
                    },
                )
            )
    folder.mkdir(parents=True, exist_ok=True)
    write_jsonl(folder / "pairs.jsonl", pairs)
    with (folder / "runs.jsonl").open("w", encoding="utf-8") as out:
        for pid, rankings in runs.items():
            for variant, ids in rankings.items():
                out.write(
                    json.dumps({"profile_id": pid, "variant": variant, "job_ids": ids}) + "\n"
                )
    summary = {
        "snapshot": snapshot_id,
        "corpus_sha256": snapshot.manifest["corpus_sha256"],
        "bm25_version": snapshot.manifest["bm25"]["version"],
        "search_candidates": settings.search_candidates,
        "rrf_k": settings.search_rrf_k,
        "seconds_per_profile": seconds,
        **pool_summary(chosen, facts),
    }
    (folder / "pool.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps({k: v for k, v in summary.items() if k != "seconds_per_profile"}, indent=2))
    return 0


async def cmd_fill(name: str, depth: int) -> int:
    """Owner decision 2026-11-27: judge every variant's top `depth` completely. Adds a pair
    for each job some variant ranked in its top `depth` that the pool left out, built from
    the snapshot exactly as pooling built the others (strata["pool"] = "fill-depth<N>"),
    after copying pairs.jsonl aside. Then `make judge SET=<name>` judges only the new ones."""
    import json
    import shutil as sh
    from datetime import UTC, datetime

    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.core.config import get_settings
    from app.eval.cards import job_card
    from app.eval.evaluate import load_runs
    from app.eval.pooling import candidates, job_facts
    from app.eval.snapshot import load_snapshot, snapshot_engine
    from app.models import Company, Job

    folder = LABELS_DIR / name
    pairs = load_pairs(folder / "pairs.jsonl")
    have = {p.pair_id for p in pairs}
    runs = load_runs(folder / "runs.jsonl")
    by_profile: dict[str, dict[str, list[str]]] = {}
    for variant, per_profile in runs.items():
        for pid, ranked in per_profile.items():
            by_profile.setdefault(pid, {})[variant] = ranked
    wanted: dict[str, list[tuple[str, dict[str, int]]]] = {}
    for pid, rankings in sorted(by_profile.items()):
        for job_id, c in candidates(rankings).items():
            if min(c.variants.values()) <= depth and pair_id(pid, job_id) not in have:
                wanted.setdefault(pid, []).append((job_id, dict(sorted(c.variants.items()))))
    total = sum(len(v) for v in wanted.values())
    if not total:
        print(f"every variant's top {depth} is already in {name}")
        return 0
    pool_meta = json.loads((folder / "pool.json").read_text(encoding="utf-8"))
    snapshot = load_snapshot(pool_meta["snapshot"])
    db = snapshot_engine(snapshot, get_settings().database_url)
    ids = {job for items in wanted.values() for job, _ in items}
    async with async_sessionmaker(db)() as session:
        facts = await job_facts(session, ids)
        rows = (
            await session.execute(
                select(Job, Company)
                .join(Company, Company.id == Job.company_id)
                .where(Job.id.in_([uuid.UUID(i) for i in ids]))
            )
        ).all()
    await db.dispose()
    cards = {str(job.id): job_card(job, company) for job, company in rows}
    missing = sorted(ids - set(facts) - set(cards))
    if missing:
        print(f"{len(missing)} jobs not searchable in the snapshot: {missing[:3]}", file=sys.stderr)
        return 1
    tag = f"fill-depth{depth}"
    added = [
        EvalPair(
            pair_id=pair_id(pid, job_id),
            profile_id=pid,
            job=cards[job_id],
            variants=variants,
            strata={
                "source": facts[job_id].source,
                "employment": facts[job_id].engagement,
                "poster": facts[job_id].poster,
                "best_rank": str(min(variants.values())),
                "over_cap": "no",
                "pool": tag,
            },
        )
        for pid, items in wanted.items()
        for job_id, variants in items
    ]
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    sh.copy2(folder / "pairs.jsonl", folder / f"pairs.before-{tag}-{stamp}.jsonl")
    write_jsonl(folder / "pairs.jsonl", [*pairs, *added])
    pool_meta.setdefault("fills", []).append(
        {
            "tag": tag,
            "depth": depth,
            "added": len(added),
            "at": stamp,
            "pairs_after": len(have) + len(added),
        }
    )
    (folder / "pool.json").write_text(json.dumps(pool_meta, indent=2) + "\n")
    print(f"added {len(added)} pairs ({tag}) to {folder}/pairs.jsonl; now {len(have) + len(added)}")
    return 0


async def cmd_reduce(name: str, distractors: int, seed: int) -> int:
    """The committed reduced corpus (app/eval/reduced.py) from the set's snapshot."""
    import json

    from app.core.config import get_settings
    from app.eval.evaluate import load_runs
    from app.eval.reduced import SEARCHABLE, choose_jobs, export_corpus, sync_url
    from app.eval.snapshot import load_snapshot

    folder = LABELS_DIR / name
    snapshot_id = json.loads((folder / "pool.json").read_text(encoding="utf-8"))["snapshot"]
    snapshot = load_snapshot(snapshot_id)
    url = sync_url(snapshot.database_url(get_settings().database_url))
    import psycopg

    with psycopg.connect(url) as conn:
        rows = conn.execute(f"SELECT id::text, source FROM jobs WHERE {SEARCHABLE}").fetchall()  # noqa: S608 - a constant
    searchable = {job_id: source for job_id, source in rows}
    pooled = {
        j
        for per_profile in load_runs(folder / "runs.jsonl").values()
        for ids in per_profile.values()
        for j in ids
    }
    keep, extra = choose_jobs(pooled, searchable, distractors, seed)
    out = snapshot.folder / "reduced"
    manifest = export_corpus(
        url,
        keep + extra,
        out,
        {
            "snapshot": snapshot_id,
            "corpus_sha256": snapshot.manifest["corpus_sha256"],
            "label_set": name,
            "selection": {
                "pooled": len(keep),
                "pooled_not_searchable": len(pooled) - len(keep),
                "distractors": len(extra),
                "searchable_in_snapshot": len(searchable),
                "seed": seed,
                "rule": "every job in runs.jsonl (any variant, any profile, ranks 1-30) "
                "plus a seeded sample of the other searchable jobs, proportional to source",
            },
        },
    )
    print(json.dumps(manifest, indent=2))
    return 0


async def cmd_gate(name: str, update_baseline: bool) -> int:
    """CI regression gate on the reduced corpus (app/eval/reduced.py)."""
    import json
    import tempfile
    import time
    from datetime import UTC, datetime
    from pathlib import Path

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.core.config import get_settings
    from app.core.redis import redis
    from app.eval.agreement import JUDGES
    from app.eval.evaluate import by_profile, profile_values
    from app.eval.metrics import bootstrap_ci
    from app.eval.pairs import read_jsonl
    from app.eval.pooling import RERANKS, FixedBm25, run_variants
    from app.eval.reduced import BASELINE, GATE_DROP, GATED, gate_check, load_corpus, sha256
    from app.retrieval.bm25 import build_index
    from app.retrieval.service import build_engine

    folder = LABELS_DIR / name
    snapshot_id = json.loads((folder / "pool.json").read_text(encoding="utf-8"))["snapshot"]
    corpus = EVAL_DIR / "snapshots" / snapshot_id / "reduced"
    labels_file = folder / "export" / JUDGES["gemini"].replace("judge", "judge_labels", 1)
    labels = {str(r["pair_id"]): int(r["grade"]) for r in read_jsonl(labels_file)}  # type: ignore[call-overload]
    settings = get_settings()
    started = time.perf_counter()
    url = load_corpus(settings.database_url, corpus)
    db = create_async_engine(url, pool_size=2, max_overflow=0)
    search_engine = build_engine(settings, redis)
    rankings: dict[str, dict[str, list[str]]] = {}
    reranks = tuple(r for r in RERANKS if r.name in ("rescore", "rerank_10_128"))
    with tempfile.TemporaryDirectory() as tmp:
        async with async_sessionmaker(db)() as session:
            version, _ = await build_index(session, Path(tmp))
            search_engine.bm25 = FixedBm25(Path(tmp) / version)
            for pid, profile in load_profiles().items():
                ranked = await run_variants(
                    session, search_engine, profile, settings, modes=("query",), reranks=reranks
                )
                for variant, ids in ranked.items():
                    rankings.setdefault(variant, {})[pid] = ids
    await db.dispose()
    search_engine.close()
    await redis.aclose()
    grades = by_profile(labels)
    scores = {}
    for variant in GATED:
        values = profile_values(rankings[variant], grades, "condensed")["ndcg10"]
        scores[variant] = bootstrap_ci(list(values.values())).mean
    seconds = round(time.perf_counter() - started, 1)
    manifest = json.loads((corpus / "manifest.json").read_text())
    jobs = manifest["files"]["jobs.csv.gz"]["rows"]
    print(f"reduced corpus {snapshot_id}: {jobs} jobs; {seconds} s")
    for variant, score in scores.items():
        print(f"{variant:22} NDCG@10 {score:.4f} (LLM-judged (Gemini), condensed)")
    if update_baseline:
        BASELINE.parent.mkdir(parents=True, exist_ok=True)
        baseline = {
            "label_set": name,
            "labels": labels_file.relative_to(EVAL_DIR).as_posix(),
            "labels_sha256": sha256(labels_file),
            "corpus_manifest_sha256": sha256(corpus / "manifest.json"),
            "metric": "mean NDCG@10 over profiles, condensed lists, LLM-judged (Gemini)",
            "allowed_drop": GATE_DROP,
            "measured_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "ndcg10": {v: round(s, 4) for v, s in scores.items()},
        }
        BASELINE.write_text(json.dumps(baseline, indent=2) + "\n")
        print(f"baseline written to {BASELINE}")
        return 0
    baseline = json.loads(BASELINE.read_text())
    if baseline["labels_sha256"] != sha256(labels_file):
        print("labels changed since the baseline: re-run with --update-baseline", file=sys.stderr)
        return 1
    failures = gate_check(scores, baseline)
    for f in failures:
        print(f"FAIL {f}", file=sys.stderr)
    print("gate passed" if not failures else f"gate failed ({len(failures)})")
    return 1 if failures else 0


def cmd_report(name: str, commit: str, pending: str | None) -> int:
    """eval/reports/<date>-<commit>.json and .md (app/eval/report.py)."""
    import json
    from datetime import UTC, datetime

    from app.eval.report import build, markdown

    folder = LABELS_DIR / name
    report = build(folder, commit, pending)
    out = EVAL_DIR / "reports"
    out.mkdir(parents=True, exist_ok=True)
    stem = f"{datetime.now(UTC):%Y-%m-%d}-{commit}"
    commands = [
        f"make eval FULL=1 SET={name}        # this report",
        "make eval                              # the CI gate on the reduced corpus",
        f"python -m app.eval.cli agreement --set {name}",
        f'make judge SET={name} ARGS="--tokens-per-minute 40000"   # Gemini, primary',
        f'make judge SET={name} ARGS="--provider groq --only blind --out judge-groq-blind.jsonl"',
        f"make cowork-import SET={name} FILE=private/cowork/batch-NN.xlsx",
        f"make eval-fill SET={name}             # every variant's top 10 judged",
    ]
    (out / f"{stem}.json").write_text(json.dumps(report, indent=1) + "\n")
    (out / f"{stem}.md").write_text(markdown(report, commands), encoding="utf-8")
    print(f"wrote {out}/{stem}.json and .md")
    return 0


def spread_sample(pairs: list[EvalPair], n: int, seed: int) -> list[EvalPair]:
    """`n` pairs, one per profile in turn (seeded), so a small judge run sees many profiles."""
    rng = random.Random(seed)  # noqa: S311 - a reproducible sample, not security
    by_profile: dict[str, list[EvalPair]] = {}
    for p in pairs:
        by_profile.setdefault(p.profile_id, []).append(p)
    for items in by_profile.values():
        rng.shuffle(items)
    order = sorted(by_profile)
    rng.shuffle(order)
    picked: list[EvalPair] = []
    while len(picked) < n and any(by_profile.values()):
        for pid in order:
            if by_profile[pid] and len(picked) < n:
                picked.append(by_profile[pid].pop())
    return picked


def token_report(folder_judge: list[JudgeRecord]) -> str:
    measured = [r for r in folder_judge if r.prompt_tokens is not None and not r.cached]
    if not measured:
        return "no token counts recorded"
    totals = sorted((r.prompt_tokens or 0) + (r.completion_tokens or 0) for r in measured)
    prompt = sum(r.prompt_tokens or 0 for r in measured) / len(measured)
    completion = sum(r.completion_tokens or 0 for r in measured) / len(measured)
    return (
        f"{len(measured)} judged calls: tokens per pair mean {sum(totals) / len(totals):.0f} "
        f"(prompt {prompt:.0f}, completion {completion:.0f}), min {totals[0]}, "
        f"max {totals[-1]}; providers {sorted({r.provider + '/' + r.model for r in measured})}"
    )


async def cmd_judge(
    name: str,
    max_requests: int,
    tpm: int,
    sample: int,
    seed: int,
    provider: str,
    out: str,
    only: str,
    rpm: float | None,
    call_timeout: float,
    max_tokens: int,
    use_cache: bool,
) -> int:
    """Judges the set's pairs not yet in `out`. Owner decision 2026-11-26: one model per
    file, so `provider` builds a client with that provider alone (no fallback): the main
    set (judge.jsonl) is Gemini; Groq judges the blind pairs into judge-groq-blind.jsonl."""
    from datetime import UTC, datetime
    from pathlib import Path

    from app.core.config import get_settings
    from app.core.db import SessionLocal, engine
    from app.core.llm import build_providers
    from app.core.llm.cache import PostgresLLMCache
    from app.core.llm.client import LLMClient
    from app.core.redis import redis
    from app.eval.judge import judge_pairs
    from app.eval.labels import Plan
    from app.eval.quota import (
        DAILY_REQUESTS,
        REQUESTS_PER_MINUTE,
        DailyBudget,
        resume_message,
    )

    folder = LABELS_DIR / name
    pairs = load_pairs(folder / "pairs.jsonl")
    if only == "blind":
        plan = Plan.model_validate_json((folder / "plan.json").read_text(encoding="utf-8"))
        blind = set(plan.blind)
        pairs = [p for p in pairs if p.pair_id in blind]
    if sample:
        pairs = spread_sample(pairs, sample, seed)
    # The judge's own client settings: a long per-call timeout, more retries and waits up
    # to two minutes (Retry-After honoured), since it runs unattended in the background.
    settings = get_settings().model_copy(
        update={"llm_timeout_seconds": call_timeout, "llm_max_retries": 4}
    )
    import httpx

    if rpm is None:
        rpm = REQUESTS_PER_MINUTE.get(provider, 0.0)
    limit = DAILY_REQUESTS.get(provider)
    budget = DailyBudget(redis, provider, limit) if limit else None
    async with httpx.AsyncClient() as http:
        providers = build_providers(settings, http)
        if provider != "any":
            providers = [p for p in providers if p.name == provider]
            if not providers:
                print(f"provider {provider} is not configured", file=sys.stderr)
                return 1
        llm = LLMClient(
            providers,
            PostgresLLMCache(SessionLocal),
            max_retries=settings.llm_max_retries,
            repair_attempts=settings.llm_repair_attempts,
            backoff_base_seconds=2.0,  # 503s are server load: back off in seconds
            backoff_cap_seconds=120.0,
        )
        run = await judge_pairs(
            pairs,
            load_profiles(),
            llm,
            folder / out,
            tokens_per_minute=tpm,
            requests_per_minute=rpm,
            max_requests=max_requests,
            sleep=asyncio.sleep,
            failures_out=folder / f"{Path(out).stem}-failures-aside.jsonl",
            max_tokens=max_tokens,
            use_cache=use_cache,
            budget=budget,
        )
    await redis.aclose()
    await engine.dispose()
    print(run)
    print(token_report(list(load_judge(folder / out).values())))
    left = sum(p.pair_id not in load_judge(folder / out) for p in pairs)
    if run.requests_today is not None:
        print(f"{provider} requests this Pacific day: {run.requests_today} of {limit}")
    if run.stopped_at_daily_budget or (run.stopped_at_daily_quota and provider == "gemini"):
        print(
            f"STOPPED: {provider} daily request budget reached; {left} pairs left; "
            f"{resume_message(datetime.now(UTC))} with the same command."
        )
    elif run.stopped_at_daily_quota:
        print(
            f"STOPPED: {provider} daily quota reached; {left} pairs left. Resume tomorrow with "
            "the same command (judged pairs are skipped)."
        )
    elif run.stopped_after_failures:
        print(
            f"STOPPED after consecutive failures ({run.failures}); {left} pairs left. "
            "See the 'llm call failed' lines above for the cause."
        )
    else:
        print(f"{left} pairs left")
    return 0 if not run.failed else 1


def cmd_export(name: str) -> int:
    """Writes the committed form of a label set (app/eval/export.py)."""
    from app.eval.export import export_set

    folder = LABELS_DIR / name
    counts = export_set(folder, load_pairs(folder / "pairs.jsonl"))
    for file, n in counts.items():
        print(f"{folder}/export/{file}: {n}")
    return 0


async def cmd_rebuild_pairs(name: str, out: str) -> int:
    """pairs.jsonl from export/pairs_index.jsonl and the snapshot named in pool.json."""
    import json

    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.core.config import get_settings
    from app.eval.cards import job_card
    from app.eval.pairs import read_jsonl
    from app.eval.snapshot import load_snapshot, snapshot_engine
    from app.models import Company, Job

    folder = LABELS_DIR / name
    target = folder / out
    if target.exists():
        print(f"{target} exists; choose another --out", file=sys.stderr)
        return 1
    index = list(read_jsonl(folder / "export" / "pairs_index.jsonl"))
    snapshot_id = json.loads((folder / "pool.json").read_text())["snapshot"]
    snapshot = load_snapshot(snapshot_id)
    db = snapshot_engine(snapshot, get_settings().database_url)
    ids = [uuid.UUID(str(row["job_id"])) for row in index]
    async with async_sessionmaker(db)() as session:
        rows = (
            await session.execute(
                select(Job, Company)
                .join(Company, Company.id == Job.company_id)
                .where(Job.id.in_(ids))
            )
        ).all()
    await db.dispose()
    cards = {str(job.id): job_card(job, company) for job, company in rows}
    missing = [str(i) for i in ids if str(i) not in cards]
    if missing:
        print(f"{len(missing)} jobs not in snapshot {snapshot_id}: {missing[:3]}", file=sys.stderr)
        return 1
    pairs = [
        EvalPair(
            pair_id=str(row["pair_id"]),
            profile_id=str(row["profile_id"]),
            job=cards[str(row["job_id"])],
            variants=row["variants"],
            strata=row["strata"],
        )
        for row in index
    ]
    write_jsonl(target, pairs)
    print(f"wrote {len(pairs)} pairs to {target} from snapshot {snapshot_id}")
    return 0


def cmd_cowork_export(name: str, per_batch: int) -> int:
    """Grading sheets for Claude Cowork (app/eval/cowork.py) in eval/private/cowork/."""
    from app.core.llm.prompts import PROMPTS_DIR
    from app.eval.cowork import JUDGE_FILE, export_batches
    from app.eval.judge import PROMPT_NAME, PROMPT_VERSION
    from app.eval.labels import Plan

    folder = LABELS_DIR / name
    plan = Plan.model_validate_json((folder / "plan.json").read_text(encoding="utf-8"))
    rubric = (PROMPTS_DIR / PROMPT_NAME / f"v{PROMPT_VERSION}.md").read_text(encoding="utf-8")
    out_dir = EVAL_DIR / "private" / "cowork"
    graded = set(load_judge(folder / JUDGE_FILE))
    try:
        batches = export_batches(
            out_dir,
            load_pairs(folder / "pairs.jsonl"),
            load_profiles(),
            plan.blind,
            graded,
            rubric,
            per_batch=per_batch,
        )
    except FileExistsError as exc:
        print(exc, file=sys.stderr)
        return 1
    print(f"already graded by Claude Cowork: {len(graded)}")
    for batch, ids in batches.items():
        print(f"{out_dir}/{batch}.xlsx: {len(ids)} pairs")
    return 0


def cmd_cowork_import(name: str, file: str) -> int:
    from pathlib import Path

    from app.eval.cowork import JUDGE_FILE, import_sheet

    folder = LABELS_DIR / name
    path = Path(file)
    if not path.is_absolute():
        path = EVAL_DIR / path
    report = import_sheet(path, folder, EVAL_DIR / "private" / "cowork" / "manifest.json")
    total = len(load_judge(folder / JUDGE_FILE))
    print(f"{report.batch}: {report.expected} pairs in the batch")
    print(f"  accepted {len(report.accepted)} (appended to {JUDGE_FILE}, now {total} pairs)")
    print(f"  grades {report.distribution()}  confidence {report.confidences()}")
    print(f"  already imported, unchanged: {report.already}")
    print(f"  left blank: {len(report.ungraded)}; no row at all: {len(report.missing)}")
    print(f"  rejected: {len(report.rejected)}")
    for row, pid, why in report.rejected:
        print(f"    row {row} {pid or '(no pair id)'}: {why}")
    return 1 if report.rejected else 0


def print_agreement(title: str, report: dict[str, Any]) -> None:
    print(f"\n== {title}: {report['pairs']} pairs; graded {report['graded']}")
    for p in report["pairwise"]:
        k = f"{p['weighted_kappa']:.3f}" if p["weighted_kappa"] is not None else "n/a"
        print(
            f"{p['a']} vs {p['b']}: n={p['n']}, weighted kappa {k}, exact "
            f"{p['exact']:.1%}, within one {p['within_one']:.1%}, mean "
            f"{p['a']}-{p['b']} {p['mean_diff_a_minus_b']:+.2f}"
        )
        print(f"  confusion (rows {p['a']} 0-3, columns {p['b']} 0-3):")
        for g, row in enumerate(p["confusion_rows_a_cols_b"]):
            print(f"    {g}: {row}")
        cells = ", ".join(
            f"{c['a']}/{c['b']} x{c['pairs']}" for c in p["most_common_disagreements"]
        )
        print(f"  most common disagreements ({p['a']}/{p['b']}): {cells or '-'}")
        for theme, t in p["themes"].items():
            print(
                f"  {theme:18} {t['disagreements']:3} ({t['share']:.0%} of disagreements);"
                f" {p['a']} higher {t['a_higher']}, {p['b']} higher {t['b_higher']}"
            )
    if "majority" in report:
        print(f"  3-judge majority: {report['majority']}")


def agreement_data(name: str) -> dict[str, Any]:
    """Owner decision 2026-11-27: judge vs judge. The blind pairs for all three judges;
    every pair for Gemini vs Claude Cowork (as its batches come in)."""
    from app.eval.agreement import Facts, agreement_report, load_judges, load_reasons
    from app.eval.labels import Plan
    from app.eval.pairs import read_jsonl

    folder = LABELS_DIR / name
    blind = Plan.model_validate_json((folder / "plan.json").read_text(encoding="utf-8")).blind
    index = list(read_jsonl(folder / "export" / "pairs_index.jsonl"))
    judges = load_judges(folder)
    facts = Facts(
        strata={str(row["pair_id"]): row["strata"] for row in index},  # type: ignore[misc]
        reasons=load_reasons(folder),
    )
    # The 500 pooled pairs (not the depth-10 fill, which Cowork's batches do not cover).
    pooled = [str(r["pair_id"]) for r in index if "pool" not in r["strata"]]  # type: ignore[operator]
    return {
        "blind": agreement_report(blind, judges, facts),
        "pooled_gemini_vs_cowork": agreement_report(
            pooled, {k: judges[k] for k in ("gemini", "cowork")}, facts
        ),
    }


def cmd_agreement(name: str, out: str | None) -> int:
    data = agreement_data(name)
    print_agreement("Blind pairs, three LLM judges", data["blind"])
    print_agreement("Pooled pairs, Gemini vs Claude Cowork", data["pooled_gemini_vs_cowork"])
    if out:
        from pathlib import Path

        from app.eval.report import agreement_lines

        path = Path(out) if Path(out).is_absolute() else EVAL_DIR / out
        path.parent.mkdir(parents=True, exist_ok=True)
        head = [
            f"# Agreement between the LLM judges: {name}",
            "",
            "LLM-judged; no human labels.",
            "",
        ]
        path.write_text("\n".join(head + agreement_lines(data)) + "\n", encoding="utf-8")
        print(f"wrote {path}")
    return 0


def cmd_summary(name: str) -> int:
    from collections import Counter

    from app.eval.labels import Event, LabelState, label_sources
    from app.eval.metrics import weighted_kappa
    from app.eval.pairs import read_jsonl

    folder = LABELS_DIR / name
    pairs = load_pairs(folder / "pairs.jsonl")
    judge = load_judge(folder / "judge.jsonl")
    final = label_sources(pairs, judge, folder / "human.jsonl")
    print(f"pairs {len(pairs)}, judged by the LLM {len(judge)}")
    print("final label sources:", dict(Counter(src for _, src in final.values())))
    state = LabelState()
    for raw in read_jsonl(folder / "human.jsonl"):
        state.apply(Event.model_validate(raw))
    blind = [
        (e.label, judge[pid].label)
        for pid, e in state.labelled().items()
        if e.phase == "blind" and e.label is not None and pid in judge
    ]
    if blind:
        human, llm = zip(*blind, strict=True)
        kappa = weighted_kappa(list(human), list(llm))
        print(f"blind pairs with a judge label: {len(blind)}; quadratic weighted kappa {kappa:.3f}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.eval.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("profiles")
    demo = sub.add_parser("demo")
    demo.add_argument("--set", default="demo")
    demo.add_argument("--per-profile", type=int, default=6)
    demo.add_argument("--profiles", default="p02,p19")
    demo.add_argument("--seed", type=int, default=1)
    label = sub.add_parser("label")
    label.add_argument("--set", required=True)
    label.add_argument("--blind", type=int, default=120)
    label.add_argument("--host", default="127.0.0.1")
    label.add_argument("--port", type=int, default=8765)
    judge = sub.add_parser("judge")
    judge.add_argument("--set", required=True)
    judge.add_argument("--max-requests", type=int, default=800)
    judge.add_argument("--tokens-per-minute", type=int, default=6000)
    judge.add_argument("--sample", type=int, default=0, help="judge only N pairs, spread")
    judge.add_argument("--seed", type=int, default=4)
    judge.add_argument("--provider", default="gemini", choices=["gemini", "groq", "any"])
    judge.add_argument("--out", default="judge.jsonl", help="file in the set folder")
    judge.add_argument("--only", default="all", choices=["all", "blind"])
    judge.add_argument(
        "--rpm", type=float, default=None, help="calls a minute (default: per provider)"
    )
    judge.add_argument("--timeout", type=float, default=120.0, help="seconds per call")
    judge.add_argument("--max-tokens", type=int, default=1024)
    judge.add_argument("--no-cache", action="store_true", help="always call the model")
    snapshot = sub.add_parser("snapshot")
    snapshot.add_argument("--id", required=True)
    snapshot.add_argument("--dump", required=True, help="a `make backup` file")
    snapshot.add_argument("--commit", required=True, help="the git commit of the code")
    pool = sub.add_parser("pool")
    pool.add_argument("--set", required=True)
    pool.add_argument("--snapshot", required=True)
    pool.add_argument("--per-profile", type=int, default=20)
    pool.add_argument("--profiles", default="", help="comma-separated ids (default: all)")
    export = sub.add_parser("export")
    export.add_argument("--set", required=True)
    rebuild = sub.add_parser("rebuild-pairs")
    rebuild.add_argument("--set", required=True)
    rebuild.add_argument("--out", default="pairs.rebuilt.jsonl")
    report = sub.add_parser("report")
    report.add_argument("--set", required=True)
    report.add_argument("--commit", required=True)
    report.add_argument("--pending", default=None, help="text for the Pending line")
    reduce = sub.add_parser("reduce")
    reduce.add_argument("--set", required=True)
    reduce.add_argument("--distractors", type=int, default=3000)
    reduce.add_argument("--seed", type=int, default=25)
    gate = sub.add_parser("gate")
    gate.add_argument("--set", default="eval-2026-11-25")
    gate.add_argument("--update-baseline", action="store_true")
    fill = sub.add_parser("fill")
    fill.add_argument("--set", required=True)
    fill.add_argument("--depth", type=int, default=10)
    cowork_export = sub.add_parser("cowork-export")
    cowork_export.add_argument("--set", required=True)
    cowork_export.add_argument("--per-batch", type=int, default=95)
    cowork_import = sub.add_parser("cowork-import")
    cowork_import.add_argument("--set", required=True)
    cowork_import.add_argument("--file", required=True, help="path under eval/, or absolute")
    agreement = sub.add_parser("agreement")
    agreement.add_argument("--set", required=True)
    agreement.add_argument("--out", default=None, help="markdown file (path under eval/)")
    summary = sub.add_parser("summary")
    summary.add_argument("--set", required=True)
    args = parser.parse_args(argv)
    from app.core.config import get_settings
    from app.core.logging import configure_logging

    configure_logging(get_settings().log_level)

    if args.command == "profiles":
        return cmd_profiles()
    if args.command == "demo":
        ids = [s.strip() for s in args.profiles.split(",") if s.strip()]
        return asyncio.run(cmd_demo(args.set, args.per_profile, ids, args.seed))
    if args.command == "label":
        return cmd_label(args.set, args.blind, args.host, args.port)
    if args.command == "judge":
        return asyncio.run(
            cmd_judge(
                args.set,
                args.max_requests,
                args.tokens_per_minute,
                args.sample,
                args.seed,
                args.provider,
                args.out,
                args.only,
                args.rpm,
                args.timeout,
                args.max_tokens,
                not args.no_cache,
            )
        )
    if args.command == "snapshot":
        return asyncio.run(cmd_snapshot(args.id, args.dump, args.commit))
    if args.command == "pool":
        ids = [s.strip() for s in args.profiles.split(",") if s.strip()]
        return asyncio.run(cmd_pool(args.set, args.snapshot, args.per_profile, ids))
    if args.command == "export":
        return cmd_export(args.set)
    if args.command == "rebuild-pairs":
        return asyncio.run(cmd_rebuild_pairs(args.set, args.out))
    if args.command == "report":
        return cmd_report(args.set, args.commit, args.pending)
    if args.command == "reduce":
        return asyncio.run(cmd_reduce(args.set, args.distractors, args.seed))
    if args.command == "gate":
        return asyncio.run(cmd_gate(args.set, args.update_baseline))
    if args.command == "fill":
        return asyncio.run(cmd_fill(args.set, args.depth))
    if args.command == "cowork-export":
        return cmd_cowork_export(args.set, args.per_batch)
    if args.command == "cowork-import":
        return cmd_cowork_import(args.set, args.file)
    if args.command == "agreement":
        return cmd_agreement(args.set, args.out)
    if args.command == "summary":
        return cmd_summary(args.set)
    return 2


if __name__ == "__main__":
    sys.exit(main())
