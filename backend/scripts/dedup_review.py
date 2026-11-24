"""Sample text near-duplicate pairs for hand review (read-only: nothing is marked).

Usage: python -m scripts.dedup_review [--n 50] [--out /out/dedup-review.md]

Runs the same finder the dedup pass uses (app.ingest.dedup.find_text_duplicates) on the
live pool, samples pairs (cross_source and near_duplicate_text in proportion, at least a
fifth of each kind when both exist; fixed seed), and writes a Markdown sheet with both
postings and the words only one of them has. A reviewer fills in the verdict column:
`same` (one posting) or `different` (distinct roles); precision = same / reviewed.
"""

import argparse
import asyncio
import random
from pathlib import Path

from sqlalchemy import text

from app.core.config import get_settings
from app.core.db import SessionLocal, engine
from app.ingest.dedup import Pair, find_text_duplicates

_DETAILS = text("""
SELECT j.id, c.name AS company, j.title, j.source, j.location, j.source_url
FROM jobs j JOIN companies c ON c.id = j.company_id WHERE j.id = ANY(:ids)
""")


def sample(pairs: list[Pair], n: int, seed: int = 7) -> list[Pair]:
    rng = random.Random(seed)  # noqa: S311 - a reproducible sample, not security
    kinds: dict[str, list[Pair]] = {}
    for pair in pairs:
        kinds.setdefault(pair.reason, []).append(pair)
    if len(kinds) == 1 or len(pairs) <= n:
        return rng.sample(pairs, min(n, len(pairs)))
    floor = n // 5
    chosen: list[Pair] = []
    for kind_pairs in kinds.values():
        share = max(floor, round(n * len(kind_pairs) / len(pairs)))
        chosen += rng.sample(kind_pairs, min(share, len(kind_pairs)))
    rng.shuffle(chosen)
    return chosen[:n]


def diff(a: frozenset[str], b: frozenset[str], k: int = 12) -> tuple[str, str]:
    only_a = sorted(a - b)[:k]
    only_b = sorted(b - a)[:k]
    return " ".join(only_a) or "-", " ".join(only_b) or "-"


async def main(n: int, out: Path) -> None:
    threshold = get_settings().ingest_near_duplicate_threshold
    async with SessionLocal() as session:
        found = await find_text_duplicates(session, threshold, include_text_marked=True)
        chosen = sample(found.pairs, n)
        ids = [p.canonical.id for p in chosen] + [p.duplicate.id for p in chosen]
        rows = {r.id: r for r in (await session.execute(_DETAILS, {"ids": ids})).all()}
    kinds = {
        k: sum(1 for p in found.pairs if p.reason == k)
        for k in ("cross_source", "near_duplicate_text")
    }
    lines = [
        "# Near-duplicate review sample",
        "",
        f"Finder: app.ingest.dedup.find_text_duplicates, Jaccard threshold {threshold}, "
        f"cross-source containment 0.6. Pairs found: {len(found.pairs)} "
        f"({kinds['cross_source']} cross_source, "
        f"{kinds['near_duplicate_text']} near_duplicate_text); buckets skipped "
        f"(over the size cap): {found.skipped_buckets}. Sample: {len(chosen)} pairs, seed 7.",
        "",
        "| # | kind | score | company | title | A (kept) | B (duplicate) "
        "| words only in A | words only in B | verdict |",
        "|---:|---|---:|---|---|---|---|---|---|---|",
    ]
    for i, pair in enumerate(chosen, start=1):
        a, b = rows[pair.canonical.id], rows[pair.duplicate.id]
        only_a, only_b = diff(pair.canonical.words, pair.duplicate.words)
        lines.append(
            f"| {i} | {pair.reason} | {pair.similarity:.3f} | {a.company} | {a.title} | "
            f"{a.source}: {a.location} | {b.source}: {b.location} | {only_a} | {only_b} |  |"
        )
    await asyncio.to_thread(_write, out, "\n".join(lines).replace("\r", "") + "\n")
    print(f"wrote {out}: {len(chosen)} of {len(found.pairs)} pairs")
    await engine.dispose()


def _write(out: Path, content: str) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(content, encoding="utf-8")


def cli() -> int:
    parser = argparse.ArgumentParser(prog="python -m scripts.dedup_review")
    parser.add_argument("--n", type=int, default=50)
    parser.add_argument("--out", type=Path, default=Path("dedup-review.md"))
    args = parser.parse_args()
    asyncio.run(main(args.n, args.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(cli())
