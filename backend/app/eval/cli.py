"""Evaluation commands (Phase 4).

python -m app.eval.cli profiles                 validate and list eval/profiles
python -m app.eval.cli demo [--set demo]        a throwaway sample to try the labelling tool
python -m app.eval.cli label --set NAME         the labelling tool (http://127.0.0.1:8765)
python -m app.eval.cli judge --set NAME         LLM-judge every pair not judged yet
python -m app.eval.cli summary --set NAME       label counts by source, kappa on the blind set
"""

import argparse
import asyncio
import random
import shutil
import sys

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


async def cmd_judge(name: str, max_requests: int, tpm: int) -> int:
    from app.core.config import get_settings
    from app.core.db import engine
    from app.core.llm import build_llm_client
    from app.eval.judge import judge_pairs

    folder = LABELS_DIR / name
    pairs = load_pairs(folder / "pairs.jsonl")
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
        return asyncio.run(cmd_judge(args.set, args.max_requests, args.tokens_per_minute))
    if args.command == "summary":
        return cmd_summary(args.set)
    return 2


if __name__ == "__main__":
    sys.exit(main())
