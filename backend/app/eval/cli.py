"""Evaluation commands (Phase 4).

python -m app.eval.cli profiles                 validate and list eval/profiles
python -m app.eval.cli demo [--set demo]        a throwaway sample to try the labelling tool
python -m app.eval.cli label --set NAME         the labelling tool (http://127.0.0.1:8765)
python -m app.eval.cli snapshot --id ID --dump FILE --commit SHA   freeze the pool
python -m app.eval.cli pool --set NAME --snapshot ID   run every variant, pool the pairs
python -m app.eval.cli judge --set NAME [--sample N]   LLM-judge every pair not judged yet
python -m app.eval.cli summary --set NAME       label counts by source, kappa on the blind set
"""

import argparse
import asyncio
import random
import shutil
import sys
import uuid

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


async def cmd_judge(name: str, max_requests: int, tpm: int, sample: int, seed: int) -> int:
    from app.core.config import get_settings
    from app.core.db import engine
    from app.core.llm import build_llm_client
    from app.eval.judge import judge_pairs

    folder = LABELS_DIR / name
    pairs = load_pairs(folder / "pairs.jsonl")
    if sample:
        pairs = spread_sample(pairs, sample, seed)
    settings = get_settings()
    import httpx

    async with httpx.AsyncClient() as http:
        run = await judge_pairs(
            pairs,
            load_profiles(),
            build_llm_client(settings, http),
            folder / "judge.jsonl",
            tokens_per_minute=tpm,
            max_requests=max_requests,
            sleep=asyncio.sleep,
        )
    await engine.dispose()
    print(run)
    print(token_report(list(load_judge(folder / "judge.jsonl").values())))
    return 0 if not run.failed else 1


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
    snapshot = sub.add_parser("snapshot")
    snapshot.add_argument("--id", required=True)
    snapshot.add_argument("--dump", required=True, help="a `make backup` file")
    snapshot.add_argument("--commit", required=True, help="the git commit of the code")
    pool = sub.add_parser("pool")
    pool.add_argument("--set", required=True)
    pool.add_argument("--snapshot", required=True)
    pool.add_argument("--per-profile", type=int, default=20)
    pool.add_argument("--profiles", default="", help="comma-separated ids (default: all)")
    summary = sub.add_parser("summary")
    summary.add_argument("--set", required=True)
    args = parser.parse_args(argv)

    if args.command == "profiles":
        return cmd_profiles()
    if args.command == "demo":
        ids = [s.strip() for s in args.profiles.split(",") if s.strip()]
        return asyncio.run(cmd_demo(args.set, args.per_profile, ids, args.seed))
    if args.command == "label":
        return cmd_label(args.set, args.blind, args.host, args.port)
    if args.command == "judge":
        return asyncio.run(
            cmd_judge(args.set, args.max_requests, args.tokens_per_minute, args.sample, args.seed)
        )
    if args.command == "snapshot":
        return asyncio.run(cmd_snapshot(args.id, args.dump, args.commit))
    if args.command == "pool":
        ids = [s.strip() for s in args.profiles.split(",") if s.strip()]
        return asyncio.run(cmd_pool(args.set, args.snapshot, args.per_profile, ids))
    if args.command == "summary":
        return cmd_summary(args.set)
    return 2


if __name__ == "__main__":
    sys.exit(main())
