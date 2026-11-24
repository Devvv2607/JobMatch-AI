"""Spot-check samples for the owner, written to eval/review/ (gitignored).

    python -m scripts.spot_checks --out /out [--seed 11]

1. duplicates.md: 20 random merged text duplicates (near_duplicate_text and cross_source,
   the population the 98% precision figure was measured on), with title, company,
   location, the first 300 characters of each and the overlap score the dedup pass uses.
2. himalayas.md: 30 random active Himalayas jobs we mark eligible for India, with the raw
   restriction fields fetched again from Himalayas' single-job endpoint (we do not store
   them) next to our parsed eligibility. One request a second.
No personal data: job postings only.
"""

import argparse
import asyncio
import random
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import text

from app.core.config import get_settings
from app.core.db import SessionLocal, engine
from app.ingest.dedup import containment, jaccard, words
from app.ingest.runner import build_http_client

_DUPLICATES = text("""
SELECT d.id, d.duplicate_reason, c.name AS company,
       d.title AS d_title, d.location AS d_location, d.source AS d_source,
       coalesce(d.search_text, d.description) AS d_body,
       k.title AS k_title, k.location AS k_location, k.source AS k_source,
       coalesce(k.search_text, k.description) AS k_body
FROM jobs d JOIN jobs k ON k.id = d.duplicate_of JOIN companies c ON c.id = d.company_id
WHERE d.status != 'expired' AND d.duplicate_reason IN ('near_duplicate_text', 'cross_source')
ORDER BY d.id  -- a fixed order, so the seeded sample is reproducible
""")
_HIMALAYAS = text("""
SELECT j.id, j.title, c.name AS company, j.source_page_url, j.eligibility_scope,
       j.work_countries, j.eligibility_source
FROM jobs j JOIN companies c ON c.id = j.company_id
WHERE j.source = 'himalayas' AND j.status != 'expired' AND j.duplicate_of IS NULL
  AND (j.eligibility_scope = 'worldwide' OR j.work_countries @> ARRAY['IN']::varchar(2)[])
ORDER BY j.id
""")
SINGLE_JOB = "https://himalayas.app/jobs/api/companies/{company}/jobs/{slug}"


def cell(value: object, limit: int = 300) -> str:
    return " ".join(str(value or "").split())[:limit].replace("|", "/")


async def duplicates(rng: random.Random, n: int) -> str:
    async with SessionLocal() as session:
        rows = (await session.execute(_DUPLICATES)).all()
    chosen = rng.sample(rows, min(n, len(rows)))
    lines = [
        f"# {len(chosen)} random merged duplicate pairs (of {len(rows)} text/cross-source merges)",
        "",
        "Score: word-set overlap (Jaccard) for near_duplicate_text, containment of the "
        "shorter text in the longer for cross_source, as the dedup pass computes them.",
        "Verdict column: same / different.",
        "",
    ]
    for i, r in enumerate(chosen, start=1):
        a, b = words(r.k_body or ""), words(r.d_body or "")
        score = jaccard(a, b) if r.duplicate_reason == "near_duplicate_text" else containment(a, b)
        lines += [
            f"## {i}. {cell(r.company, 80)}: {r.duplicate_reason}, score {score:.3f}",
            "",
            "| | kept | hidden as duplicate |",
            "|---|---|---|",
            f"| title | {cell(r.k_title, 150)} | {cell(r.d_title, 150)} |",
            f"| source / location | {r.k_source}: {cell(r.k_location, 100)} | "
            f"{r.d_source}: {cell(r.d_location, 100)} |",
            f"| first 300 chars | {cell(r.k_body)} | {cell(r.d_body)} |",
            "",
            "Verdict: ",
            "",
        ]
    return "\n".join(lines)


async def himalayas(rng: random.Random, n: int) -> str:
    async with SessionLocal() as session:
        rows = (await session.execute(_HIMALAYAS)).all()
    chosen = rng.sample(rows, min(n, len(rows)))
    lines = [
        f"# {len(chosen)} random Himalayas jobs we mark eligible for India "
        f"(of {len(rows)} active, unique)",
        "",
        "Raw fields fetched again from Himalayas' single-job endpoint today. "
        "Verdict column: right / wrong (our India eligibility).",
        "",
        "| # | title | company | locationRestrictions | timezoneRestrictions | our scope | "
        "our countries | decided by | verdict |",
        "|---:|---|---|---|---|---|---|---|---|",
    ]
    async with build_http_client(get_settings()) as http:
        for i, r in enumerate(chosen, start=1):
            raw: dict[str, Any] = {}
            status = ""
            parts = (r.source_page_url or "").rstrip("/").split("/")
            if len(parts) >= 3:
                company_slug, slug = parts[-3], parts[-1]
                try:
                    response = await http.get(SINGLE_JOB.format(company=company_slug, slug=slug))
                    status = str(response.status_code)
                    if response.status_code == 200:
                        body = response.json()
                        raw = body.get("job") or body
                except (httpx.HTTPError, ValueError) as exc:
                    status = type(exc).__name__
            await asyncio.sleep(1.0)
            loc = raw.get("locationRestrictions") if raw else f"(fetch: {status})"
            tz = raw.get("timezoneRestrictions") if raw else ""
            countries = (
                ",".join(r.work_countries)
                if len(r.work_countries) <= 12
                else (",".join(r.work_countries[:12]) + f" +{len(r.work_countries) - 12}")
            )
            lines.append(
                f"| {i} | {cell(r.title, 70)} | {cell(r.company, 40)} | {cell(loc, 400)} | "
                f"{cell(tz, 400)} | {r.eligibility_scope} | {countries} | "
                f"{cell(r.eligibility_source, 40)} |  |"
            )
    return "\n".join(lines) + "\n"


async def main(out: Path, seed: int) -> None:
    rng = random.Random(seed)  # noqa: S311 - a reproducible sample, not security
    dup = await duplicates(rng, 20)
    him = await himalayas(rng, 30)
    await asyncio.to_thread(_write, out, {"duplicates.md": dup, "himalayas.md": him})
    print(f"wrote {out}/duplicates.md and {out}/himalayas.md")
    await engine.dispose()


def _write(out: Path, files: dict[str, str]) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        (out / name).write_text(content, encoding="utf-8")


def cli() -> int:
    parser = argparse.ArgumentParser(prog="python -m scripts.spot_checks")
    parser.add_argument("--out", type=Path, default=Path("eval-review"))
    parser.add_argument("--seed", type=int, default=11)
    args = parser.parse_args()
    asyncio.run(main(args.out, args.seed))
    return 0


if __name__ == "__main__":
    raise SystemExit(cli())
