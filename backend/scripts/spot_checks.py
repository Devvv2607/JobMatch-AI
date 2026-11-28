"""Spot-check samples for the owner, written to eval/review/ (gitignored).

    python -m scripts.spot_checks --out /out [--seed 11] [--only base|borderline|tags|all]

1. duplicates.md: 20 random merged text duplicates (near_duplicate_text and cross_source,
   the population the 98% precision figure was measured on), with title, company,
   location, the first 300 characters of each and the overlap score the dedup pass uses.
2. himalayas.md: 30 random active Himalayas jobs we mark eligible for India, with the raw
   restriction fields fetched again from Himalayas' single-job endpoint (we do not store
   them) next to our parsed eligibility. One request a second.
3. duplicates-borderline.md (--only borderline): 10 near-duplicate pairs whose word-set
   overlap with the kept job is 0.90-0.95, one per company, plus every merged pair that
   scores below 0.90 against the kept job (merged through a third posting).
4. tags.md (--only tags): engagement_type and poster_type counts by source, 15 random
   jobs for each non-default value with the rule that decided it, and 20 random Himalayas
   / Adzuna jobs tagged employer (staffing-agency recall).
5. duplicates-all.md (--only all): 20 random merged pairs from every merge reason
   (content_hash, near_duplicate_text, cross_source), after the exact title+location
   pass was removed (2026-11-25).
6. tags-recheck.md (--only recheck): tag counts by source and 10 fresh random contract
   and staffing_agency jobs, leaving out those already in tags.md.
Every sampled pair or job carries its id, so verdicts can be recorded in
eval/review-results.md without quoting postings.
No personal data: job postings only.
"""

import argparse
import asyncio
import random
import re
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import text

from app.core.config import get_settings
from app.core.db import SessionLocal, engine
from app.ingest.dedup import containment, jaccard, words
from app.ingest.runner import build_http_client
from app.ingest.tags import explain_engagement, explain_poster

_DUPLICATES = text("""
SELECT d.id, k.id AS k_id, d.duplicate_reason, c.name AS company,
       d.title AS d_title, d.location AS d_location, d.source AS d_source,
       coalesce(d.search_text, d.description) AS d_body,
       k.title AS k_title, k.location AS k_location, k.source AS k_source,
       coalesce(k.search_text, k.description) AS k_body
FROM jobs d JOIN jobs k ON k.id = d.duplicate_of JOIN companies c ON c.id = d.company_id
WHERE d.status != 'expired' AND d.duplicate_reason = ANY(:reasons)
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


TEXT_REASONS = ["near_duplicate_text", "cross_source"]
ALL_REASONS = ["content_hash", *TEXT_REASONS]


async def duplicates(rng: random.Random, n: int, reasons: list[str] = TEXT_REASONS) -> str:
    async with SessionLocal() as session:
        rows = (await session.execute(_DUPLICATES, {"reasons": reasons})).all()
    chosen = rng.sample(rows, min(n, len(rows)))
    what = "merges, every reason" if reasons == ALL_REASONS else "text/cross-source merges"
    population = ", ".join(
        f"{reason} {sum(r.duplicate_reason == reason for r in rows)}" for reason in reasons
    )
    sampled = ", ".join(
        f"{reason} {sum(r.duplicate_reason == reason for r in chosen)}" for reason in reasons
    )
    lines = [
        f"# {len(chosen)} random merged duplicate pairs (of {len(rows)} {what})",
        "",
        "Score: word-set overlap (Jaccard) for near_duplicate_text and content_hash, "
        "containment of the shorter text in the longer for cross_source, as the dedup "
        "pass computes them.",
        f"Population: {population}. Sampled: {sampled}.",
        "Verdict column: same / different.",
        "",
    ]
    for i, r in enumerate(chosen, start=1):
        a, b = words(r.k_body or ""), words(r.d_body or "")
        score = containment(a, b) if r.duplicate_reason == "cross_source" else jaccard(a, b)
        lines += [
            f"## {i}. {cell(r.company, 80)}: {r.duplicate_reason}, score {score:.3f}",
            "",
            f"kept `{r.k_id}`, hidden `{r.id}`",
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


_NEAR = text("""
SELECT d.id, k.id AS k_id, c.name AS company,
       d.title AS d_title, d.location AS d_location, d.source AS d_source,
       coalesce(d.search_text, d.description) AS d_body,
       k.title AS k_title, k.location AS k_location, k.source AS k_source,
       coalesce(k.search_text, k.description) AS k_body
FROM jobs d JOIN jobs k ON k.id = d.duplicate_of JOIN companies c ON c.id = d.company_id
WHERE d.status != 'expired' AND d.duplicate_reason = 'near_duplicate_text'
ORDER BY d.id
""")


def _pair(i: int, r: Any, score: float) -> list[str]:
    return [
        f"## {i}. {cell(r.company, 80)}: near_duplicate_text, score {score:.3f}",
        "",
        f"kept `{r.k_id}`, hidden `{r.id}`",
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


async def borderline(rng: random.Random, n: int) -> str:
    async with SessionLocal() as session:
        rows = (await session.execute(_NEAR)).all()
    scored = [(r, jaccard(words(r.k_body or ""), words(r.d_body or ""))) for r in rows]
    band = [(r, s) for r, s in scored if 0.90 <= s < 0.95]
    below = [(r, s) for r, s in scored if s < 0.90]
    by_company: dict[str, list[tuple[Any, float]]] = {}
    for r, s in band:
        by_company.setdefault(r.company, []).append((r, s))
    companies = rng.sample(sorted(by_company), min(n, len(by_company)))
    chosen = [rng.choice(by_company[c]) for c in companies]
    lines = [
        f"# {len(chosen)} near-duplicate pairs scored 0.90-0.95 (one per company)",
        "",
        f"Of {len(scored)} active near_duplicate_text merges: {sum(s >= 0.97 for _, s in scored)}"
        f" score >= 0.97, {sum(0.95 <= s < 0.97 for _, s in scored)} score 0.95-0.97, "
        f"{len(band)} score 0.90-0.95 ({len(by_company)} companies), {len(below)} score "
        "below 0.90 against the kept job.",
        "Score: word-set overlap (Jaccard) of the two texts, as the dedup pass computes it.",
        "Verdict: same / different.",
        "",
    ]
    for i, (r, s) in enumerate(chosen, start=1):
        lines += _pair(i, r, s)
    lines += [
        f"# Also: the {len(below)} merged pairs scoring below 0.90 against the kept job",
        "",
        "Each was merged because it scored >= 0.90 against another posting in the same "
        "group (groups are connected components), not against the one kept.",
        "",
    ]
    for i, (r, s) in enumerate(sorted(below, key=lambda x: x[1]), start=len(chosen) + 1):
        lines += _pair(i, r, s)
    return "\n".join(lines)


_TAG_COUNTS = text("""
SELECT source, engagement_type, poster_type, count(*) AS n
FROM jobs WHERE status != 'expired' AND duplicate_of IS NULL
GROUP BY 1, 2, 3
""")
_TAGGED = text("""
SELECT j.id, j.source, j.title, c.name AS company, j.employment_type, j.engagement_type,
       j.poster_type, j.description
FROM jobs j JOIN companies c ON c.id = j.company_id
WHERE j.status != 'expired' AND j.duplicate_of IS NULL
ORDER BY j.id
""")


def _why_engagement(r: Any) -> str:
    value, why = explain_engagement(r.employment_type, r.title, r.description, r.company)
    return why if value == r.engagement_type else f"stored {r.engagement_type}; rules now: {why}"


def _why_poster(r: Any) -> str:
    value, why = explain_poster(r.company, r.description)
    return cell(why, 200) if value == r.poster_type else f"stored {r.poster_type}; rules now: {why}"


async def tags(rng: random.Random, n: int, recheck: frozenset[str] | None = None) -> str:
    """The tag sheet. `recheck`: only contract and staffing_agency samples, leaving out
    the job ids in that set (those already shown in an earlier sheet)."""
    async with SessionLocal() as session:
        counts = (await session.execute(_TAG_COUNTS)).all()
        rows = (await session.execute(_TAGGED)).all()
    sources = sorted({r.source for r in counts})
    engagements = ["full_time", "part_time", "contract", "internship", "freelance_gig"]
    lines = [
        "# Engagement and poster tags",
        "",
        "Active, unique jobs (duplicates excluded). Rules: backend/app/ingest/data/tags.yaml.",
        "",
        "## engagement_type by source",
        "",
        "| source | " + " | ".join(engagements) + " | total |",
        "|---|" + "---:|" * (len(engagements) + 1),
    ]
    for source in [*sources, "all"]:
        cells = [
            sum(r.n for r in counts if r.engagement_type == e and source in ("all", r.source))
            for e in engagements
        ]
        lines.append(
            f"| {source} | " + " | ".join(f"{c:,}" for c in cells) + f" | {sum(cells):,} |"
        )
    lines += [
        "",
        "## poster_type by source",
        "",
        "| source | employer | staffing_agency | total |",
        "|---|---:|---:|---:|",
    ]
    for source in [*sources, "all"]:
        cells = [
            sum(r.n for r in counts if r.poster_type == p and source in ("all", r.source))
            for p in ("employer", "staffing_agency")
        ]
        lines.append(
            f"| {source} | " + " | ".join(f"{c:,}" for c in cells) + f" | {sum(cells):,} |"
        )

    if recheck is not None:
        rows = [r for r in rows if str(r.id) not in recheck]
    samples: list[tuple[str, str, list[Any], Any]] = [
        (f"engagement_type = {e}", "engagement", [r for r in rows if r.engagement_type == e], None)
        for e in ("freelance_gig", "contract", "part_time", "internship")
    ]
    samples.append(
        (
            "poster_type = staffing_agency",
            "poster",
            [r for r in rows if r.poster_type == "staffing_agency"],
            None,
        )
    )
    if recheck is not None:
        samples = [s for s in samples if s[0].endswith(("contract", "staffing_agency"))]
    else:
        # Recall check for staffing agencies (owner, 2026-11-25): aggregator jobs we call
        # employer.
        samples.append(
            (
                "poster_type = employer, sources himalayas and adzuna",
                "poster",
                [
                    r
                    for r in rows
                    if r.poster_type == "employer" and r.source in ("himalayas", "adzuna")
                ],
                20,
            )
        )
    for heading, kind, population, size in samples:
        chosen = rng.sample(population, min(size or n, len(population)))
        lines += [
            "",
            f"## {len(chosen)} random jobs with {heading} (of {len(population):,})",
            "",
            "| # | id | title | company | source | decided by | start of description | verdict |",
            "|---:|---|---|---|---|---|---|---|",
        ]
        for i, r in enumerate(chosen, start=1):
            why = _why_engagement(r) if kind == "engagement" else _why_poster(r)
            lines.append(
                f"| {i} | `{r.id}` | {cell(r.title, 80)} | {cell(r.company, 40)} | {r.source} | "
                f"{cell(why, 200)} | {cell(r.description, 200)} |  |"
            )
    return "\n".join(lines) + "\n"


async def main(out: Path, seed: int, only: str) -> None:
    rng = random.Random(seed)  # noqa: S311 - a reproducible sample, not security
    files: dict[str, str] = {}
    if only == "base":
        files["duplicates.md"] = await duplicates(rng, 20)
        files["himalayas.md"] = await himalayas(rng, 30)
    elif only == "borderline":
        files["duplicates-borderline.md"] = await borderline(rng, 10)
    elif only == "all":
        files["duplicates-all.md"] = await duplicates(rng, 20, ALL_REASONS)
    elif only == "recheck":
        shown = out / "tags.md"
        seen = set(re.findall(r"`([0-9a-f-]{36})`", shown.read_text(encoding="utf-8")))
        files["tags-recheck.md"] = await tags(rng, 10, frozenset(seen))
    else:
        files["tags.md"] = await tags(rng, 15)
    await asyncio.to_thread(_write, out, files)
    print("wrote " + ", ".join(f"{out}/{name}" for name in files))
    await engine.dispose()


def _write(out: Path, files: dict[str, str]) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        (out / name).write_text(content, encoding="utf-8")


def cli() -> int:
    parser = argparse.ArgumentParser(prog="python -m scripts.spot_checks")
    parser.add_argument("--out", type=Path, default=Path("eval-review"))
    parser.add_argument("--seed", type=int, default=11)
    parser.add_argument(
        "--only", choices=["base", "borderline", "tags", "all", "recheck"], default="base"
    )
    args = parser.parse_args()
    asyncio.run(main(args.out, args.seed, args.only))
    return 0


if __name__ == "__main__":
    raise SystemExit(cli())
