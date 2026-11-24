"""Board discovery: find more companies' ATS boards, verify each live, and record the ones
that hire in India (or worldwide) in app/ingest/data/companies_discovered.yaml.

    python -m app.ingest.discover yc            # Y Combinator companies (yc-oss dataset)
    python -m app.ingest.discover elevation     # Elevation Capital portfolio
    python -m app.ingest.discover commoncrawl   # board URLs in the Common Crawl URL index
    (each with --limit N to cap how many companies or boards are checked)

Sources and their terms (checked 2026-11-24, see docs/decisions/log.md):
- yc-oss (https://yc-oss.github.io/api/companies/hiring.json): an unofficial dataset built
  daily from YC's public search index. ycombinator.com and workatastartup.com are never
  accessed. Downloaded at most weekly (cached in Redis); only name, website, batch,
  industry, regions and the slug are used. The repository has no licence file.
- Elevation Capital's portfolio page: no robots.txt and no use restriction in its terms.
  Peak XV's terms prohibit scraping; Accel, Lightspeed, a16z, Sequoia and Blume are
  unclear or unreachable, so they are skipped (the owner's rule: only pages that allow
  automated access).
- Common Crawl URL index (CC-MAIN-2026-47): "please do not overload the URL index
  server": a few pages per ATS host, one request every 3 seconds.
- A company's own website: one robots.txt check and one homepage request, only when no
  board was found from its name; links to known ATS hosts are read from the page.
- Boards are probed and verified only through the ATS public endpoints JobMatch already
  ingests from. Keka, Darwinbox and greytHR are not probed: none documents a public
  endpoint, so there is no adapter.

A board is accepted when it lists jobs open to a candidate in India (eligibility
"eligible" for IN, which includes worldwide-remote jobs): at least 5% of its jobs or at
least 20 of them.
"""

import argparse
import asyncio
import json
import logging
import re
import sys
import time
import urllib.robotparser
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
import yaml

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.core.redis import redis
from app.ingest.companies import (
    ATS_SOURCES,
    COMPANIES_FILE,
    DISCOVERED_FILE,
    company_slug,
    load_companies,
    match_key,
)
from app.ingest.normalise import normalise
from app.ingest.runner import ADAPTERS, build_http_client
from app.ingest.sources.base import SourceError, get_json
from app.ingest.sources.smartrecruiters import LIST_URL as SR_LIST_URL
from app.ingest.types import RawPosting

logger = logging.getLogger(__name__)

YC_URL = "https://yc-oss.github.io/api/companies/hiring.json"
YC_CACHE_KEY = "discover:yc-oss:hiring"
YC_CACHE_SECONDS = 7 * 86400
ELEVATION_URL = "https://elevationcapital.com/portfolio"
CC_INDEX = "https://index.commoncrawl.org/CC-MAIN-2026-47-index"
CC_DELAY_SECONDS = 3.0
# A board is worth ingesting when India hiring is a real part of it: at least this share
# of its jobs eligible for a candidate in India, or at least this many such jobs. On the
# 2026-11-24 run this kept 945 of 998 India-eligible jobs from 4,442 jobs instead of 7,772.
MIN_INDIA_SHARE = 0.05
MIN_INDIA_JOBS = 20

# Where each ATS's public board lives, for reading links on company sites and URLs in
# the crawl index: (ats, regex with the board token as group 1).
BOARD_URLS: list[tuple[str, re.Pattern[str]]] = [
    (
        "greenhouse",
        re.compile(r"(?:job-)?boards(?:-api)?\.greenhouse\.io/(?:v1/boards/)?([\w-]+)", re.I),
    ),
    ("lever", re.compile(r"jobs\.(?:eu\.)?lever\.co/([\w-]+)", re.I)),
    ("ashby", re.compile(r"jobs\.ashbyhq\.com/([\w.-]+)", re.I)),
    ("smartrecruiters", re.compile(r"(?:jobs|careers)\.smartrecruiters\.com/([\w-]+)", re.I)),
    ("workable", re.compile(r"apply\.workable\.com/([\w-]+)", re.I)),
    ("recruitee", re.compile(r"([\w-]+)\.recruitee\.com", re.I)),
]
_NOT_TOKENS = {"embed", "api", "v1", "jobs", "careers", "o", "j", "en", "www", "app", "static"}
CC_PREFIXES = {
    "greenhouse": ["boards.greenhouse.io/*", "job-boards.greenhouse.io/*"],
    "lever": ["jobs.lever.co/*"],
    "ashby": ["jobs.ashbyhq.com/*"],
    "smartrecruiters": ["jobs.smartrecruiters.com/*"],
    "workable": ["apply.workable.com/*"],
    "recruitee": ["*.recruitee.com"],
}


@dataclass
class Candidate:
    name: str
    website: str | None = None
    token_guesses: list[str] = field(default_factory=list)
    yc_batch: str | None = None
    industries: list[str] = field(default_factory=list)
    investors: list[str] = field(default_factory=list)
    discovered_via: str = "unknown"
    board: tuple[str, str] | None = None  # (ats, token) when already known


@dataclass
class Verified:
    name: str
    ats: str
    token: str
    jobs: int
    india_eligible: int
    remote: int
    board_name: str | None = None  # the company name the board itself reports
    # matched | domain_in_postings | linked_from_company_site | board_from_index
    name_check: str = "unchecked"
    text: str = field(default="", repr=False)  # postings' text, for the domain check


@dataclass
class Funnel:
    source: str
    candidates: int = 0
    boards_found: int = 0
    found_by: dict[str, int] = field(default_factory=dict)
    verified_live: int = 0
    accepted_india: int = 0
    already_known: int = 0
    failures: dict[str, int] = field(default_factory=dict)
    seconds: float = 0.0

    def fail(self, reason: str) -> None:
        self.failures[reason] = self.failures.get(reason, 0) + 1


# --- board probing and verification -------------------------------------------------


def _token_variants(*names: str | None) -> list[str]:
    out: list[str] = []
    for name in names:
        if not name:
            continue
        base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
        for variant in (base, base.replace("-", "")):
            if len(variant) >= 2 and variant not in out:
                out.append(variant)
    return out


def _domain_root(website: str | None) -> str | None:
    if not website:
        return None
    host = urlparse(website if "://" in website else f"https://{website}").hostname or ""
    parts = [p for p in host.split(".") if p not in ("www", "careers", "jobs")]
    return parts[0] if parts else None


async def _postings(http: httpx.AsyncClient, ats: str, token: str, name: str) -> list[RawPosting]:
    """The board's postings, cheaply: SmartRecruiters' list (no detail calls)."""
    if ats == "smartrecruiters":
        data = await get_json(http, SR_LIST_URL.format(company=token), limit=100)
        postings = []
        for item in data.get("content") or []:
            loc = item.get("location") or {}
            country = str(loc.get("country") or "").upper()
            postings.append(
                RawPosting(
                    source="smartrecruiters",
                    source_id=str(item.get("id")),
                    company_name=str((item.get("company") or {}).get("name") or name),
                    title=str(item.get("name") or ""),
                    source_url="",
                    description_html="",
                    locations=[", ".join(str(p) for p in (loc.get("city"), country) if p)],
                    structured_countries=[country] if len(country) == 2 else [],
                    structured_country_field="smartrecruiters.location.country",
                    workplace="remote" if loc.get("remote") else None,
                )
            )
        return postings
    return (await ADAPTERS[ats].fetch(http, token, name)).postings


async def verify(http: httpx.AsyncClient, ats: str, token: str, name: str) -> Verified | None:
    """Live check: the board answers and lists jobs. None if it does not."""
    try:
        postings = await _postings(http, ats, token, name)
    except SourceError:
        return None
    if not postings:
        return None
    india = remote = 0
    for posting in postings:
        try:
            job = normalise(posting)
        except Exception:  # noqa: S112 - one bad posting does not decide a board
            continue
        india += job.work.eligibility_for("IN") == "eligible"
        remote += job.remote_policy == "remote"
    reports_name = ats in ("greenhouse", "workable", "recruitee", "smartrecruiters")
    board_name = postings[0].company_name if reports_name else None
    text = " ".join(
        f"{p.title} {p.source_url} {p.description_html[:4000]}" for p in postings[:25]
    ).lower()
    return Verified(name, ats, token, len(postings), india, remote, board_name, text=text)


def same_company(found: Verified, c: "Candidate") -> bool:
    """A board found by guessing a token must belong to this company. Where the board
    names its company (Greenhouse, Workable, Recruitee, SmartRecruiters) the names must
    match; Lever and Ashby name nobody, so the company's website domain must appear in
    the board's postings (an "apollo" board of another Apollo does not mention
    apollofirst.xyz). Without a website, a Lever or Ashby guess is rejected."""
    if found.board_name is None:
        root = (_domain_root(c.website) or "").lower()
        if len(root) >= 4 and root in found.text:
            found.name_check = "domain_in_postings"
            return True
        found.name_check = "no_evidence"
        return False
    keys = {match_key(c.name)}
    if domain := _domain_root(c.website):
        keys.add(match_key(domain))
    # Exact after stripping legal suffixes: "Apollo.io" is not "Apollo".
    ok = match_key(found.board_name) in keys
    found.name_check = "matched" if ok else "mismatch"
    return ok


async def probe_tokens(http: httpx.AsyncClient, c: "Candidate") -> Verified | None:
    """The first (ats, token) among the guesses that is a live board of this company."""
    for token in c.token_guesses:
        for ats in ATS_SOURCES:
            found = await verify(http, ats, token, c.name)
            if found is not None and same_company(found, c):
                return found
    return None


async def boards_on_site(http: httpx.AsyncClient, website: str) -> list[tuple[str, str]]:
    """ATS board links on the company's homepage, if robots.txt allows reading it."""
    url = website if "://" in website else f"https://{website}"
    parsed = urlparse(url)
    robots = urllib.robotparser.RobotFileParser()
    try:
        response = await http.get(f"{parsed.scheme}://{parsed.netloc}/robots.txt")
        robots.parse(response.text.splitlines() if response.status_code == 200 else [])
    except httpx.HTTPError:
        robots.parse([])
    agent = http.headers.get("User-Agent", "*")
    if not robots.can_fetch(agent, url):
        return []
    try:
        response = await http.get(url)
    except httpx.HTTPError:
        return []
    if response.status_code != 200:
        return []
    return boards_in(response.text)


def boards_in(text: str) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for ats, pattern in BOARD_URLS:
        for token in pattern.findall(text):
            token = token.strip(".").lower() if ats != "ashby" else token.strip(".")
            if token.lower() not in _NOT_TOKENS and (ats, token) not in found:
                found.append((ats, token))
    return found


async def resolve(http: httpx.AsyncClient, c: Candidate, funnel: Funnel) -> Verified | None:
    if c.board is not None:
        found = await verify(http, *c.board, c.name)
        if found:
            found.name_check = "board_from_index"
            funnel.found_by["index"] = funnel.found_by.get("index", 0) + 1
        return found
    found = await probe_tokens(http, c)
    if found:
        funnel.found_by["name"] = funnel.found_by.get("name", 0) + 1
        return found
    if c.website:
        for ats, token in await boards_on_site(http, c.website):
            found = await verify(http, ats, token, c.name)
            if found:
                found.name_check = "linked_from_company_site"
                funnel.found_by["website"] = funnel.found_by.get("website", 0) + 1
                return found
    return None


# --- candidates per source ----------------------------------------------------------


async def yc_candidates(http: httpx.AsyncClient) -> list[Candidate]:
    cached = await redis.get(YC_CACHE_KEY)
    if cached is None:
        response = await http.get(YC_URL)
        response.raise_for_status()
        cached = response.content
        await redis.set(YC_CACHE_KEY, cached, ex=YC_CACHE_SECONDS)
        logger.info("yc-oss downloaded", extra={"bytes": len(cached)})
    companies = json.loads(cached)

    def priority(c: dict[str, Any]) -> int:
        regions = c.get("regions") or []
        if any("India" in r for r in regions):
            return 0
        if "Remote" in regions or "Partly Remote" in regions:
            return 1
        return 2

    out = []
    for c in sorted(companies, key=lambda c: (priority(c), str(c.get("name")))):
        if priority(c) == 2:
            continue  # neither India nor remote-friendly: not worth probing
        name = str(c.get("name") or "").strip()
        if not name:
            continue
        industry = str(c.get("industry") or "").strip()
        out.append(
            Candidate(
                name=name,
                website=c.get("website"),
                token_guesses=_token_variants(c.get("slug"), name, _domain_root(c.get("website"))),
                yc_batch=c.get("batch"),
                industries=[re.sub(r"[^a-z0-9]+", "-", industry.lower()).strip("-")]
                if industry
                else [],
                discovered_via="yc-oss",
            )
        )
    return out


async def elevation_candidates(http: httpx.AsyncClient) -> list[Candidate]:
    response = await http.get(ELEVATION_URL)
    response.raise_for_status()
    slugs = sorted(set(re.findall(r'href="/portfolio/([a-z0-9-]+)"', response.text)))
    out = []
    for slug in slugs:
        await asyncio.sleep(1.0)
        try:
            page = await http.get(f"{ELEVATION_URL}/{slug}")
        except httpx.HTTPError:
            continue
        if page.status_code != 200:
            continue
        title = re.search(r"<h1[^>]*>\s*([^<]{2,80}?)\s*</h1>", page.text)
        name = title.group(1).strip() if title else slug.replace("-", " ").title()
        links = [
            u
            for u in re.findall(r'href="(https?://[^"]+)"', page.text)
            if "elevationcapital.com" not in u
            and not re.search(r"linkedin|twitter|x\.com|facebook|instagram|youtube", u)
        ]
        out.append(
            Candidate(
                name=name,
                website=links[0] if links else None,
                token_guesses=_token_variants(
                    slug, name, _domain_root(links[0] if links else None)
                ),
                investors=["elevation"],
                discovered_via="vc:elevation",
            )
        )
    return out


async def commoncrawl_candidates(http: httpx.AsyncClient, pages_per_prefix: int) -> list[Candidate]:
    tokens: dict[tuple[str, str], None] = {}
    for ats, prefixes in CC_PREFIXES.items():
        pattern = dict(BOARD_URLS)[ats]
        for prefix in prefixes:
            for page in range(pages_per_prefix):
                await asyncio.sleep(CC_DELAY_SECONDS)
                try:
                    response = await http.get(
                        CC_INDEX,
                        params={"url": prefix, "output": "json", "fl": "url", "page": page},
                        timeout=60,
                    )
                except httpx.HTTPError:
                    break
                if response.status_code != 200:
                    break
                for line in response.text.splitlines():
                    try:
                        url = json.loads(line)["url"]
                    except (ValueError, KeyError):
                        continue
                    for token in pattern.findall(url):
                        token = token.strip(".")
                        if token.lower() not in _NOT_TOKENS:
                            tokens[(ats, token if ats == "ashby" else token.lower())] = None
    return [
        Candidate(name=token, board=(ats, token), discovered_via="commoncrawl")
        for ats, token in tokens
    ]


# --- writing ----------------------------------------------------------------------------


def _known_boards(
    discovered_path: Path = DISCOVERED_FILE,
) -> tuple[set[str], set[tuple[str, str]]]:
    entries = load_companies(COMPANIES_FILE, discovered_path)
    return {company_slug(e.name) for e in entries}, {(e.ats, e.token) for e in entries}


def merge_discovered(
    accepted: list[tuple[Candidate, Verified]], path: Path = DISCOVERED_FILE
) -> int:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else None
    existing = list((raw or {}).get("companies") or [])
    slugs, boards = _known_boards(path)
    added = 0
    for c, v in accepted:
        name = (c.name if c.discovered_via != "commoncrawl" else v.name).strip()
        if company_slug(name) in slugs or (v.ats, v.token) in boards:
            continue
        slugs.add(company_slug(name))
        boards.add((v.ats, v.token))
        entry: dict[str, Any] = {"name": name, "ats": v.ats, "token": v.token}
        if c.website:
            entry["website"] = c.website
        if c.yc_batch:
            entry["yc_batch"] = c.yc_batch
        if c.investors:
            entry["investors"] = c.investors
        if c.industries:
            entry["industries"] = c.industries
        entry["discovered_via"] = c.discovered_via
        entry["verified"] = {
            "jobs": v.jobs,
            "india_eligible": v.india_eligible,
            "remote": v.remote,
            "name_check": v.name_check,
        }
        existing.append(entry)
        added += 1
    header = (
        "# Boards found by `python -m app.ingest.discover` (yc-oss, Elevation Capital, Common\n"
        "# Crawl), each verified live with at least one job open to a candidate in India.\n"
        "# Generated: edit companies.yaml, not this file, to curate a company by hand.\n"
    )
    body = yaml.safe_dump({"companies": existing}, sort_keys=False, allow_unicode=True, width=100)
    path.write_text(header + body, encoding="utf-8")
    return added


async def _company_name(http: httpx.AsyncClient, ats: str, token: str) -> str:
    """A readable name for a board found only by URL."""
    if ats == "greenhouse":
        try:
            data = await get_json(http, f"https://boards-api.greenhouse.io/v1/boards/{token}")
            if data.get("name"):
                return str(data["name"])
        except SourceError:
            pass
    return token.replace("-", " ").replace("_", " ").title()


async def run(source: str, limit: int | None, pages_per_prefix: int, report_dir: Path) -> int:
    settings = get_settings()
    funnel = Funnel(source)
    started = time.perf_counter()
    slugs, boards = _known_boards()
    async with build_http_client(settings) as http:
        if source == "yc":
            candidates = await yc_candidates(http)
        elif source == "elevation":
            candidates = await elevation_candidates(http)
        else:
            candidates = await commoncrawl_candidates(http, pages_per_prefix)
        fresh = [
            c
            for c in candidates
            if company_slug(c.name) not in slugs and (c.board is None or c.board not in boards)
        ]
        funnel.already_known = len(candidates) - len(fresh)
        if limit is not None:
            fresh = fresh[:limit]
        funnel.candidates = len(fresh)

        semaphore = asyncio.Semaphore(4)
        accepted: list[tuple[Candidate, Verified]] = []

        async def one(c: Candidate) -> None:
            async with semaphore:
                try:
                    found = await resolve(http, c, funnel)
                except Exception as exc:
                    funnel.fail(type(exc).__name__)
                    return
            if found is None:
                funnel.fail("no live board found")
                return
            funnel.boards_found += 1
            funnel.verified_live += 1
            if found.india_eligible == 0:
                funnel.fail("board has no India-eligible job")
                return
            if (
                found.india_eligible < MIN_INDIA_JOBS
                and found.india_eligible / found.jobs < MIN_INDIA_SHARE
            ):
                funnel.fail("India-eligible share under 5% and under 20 jobs")
                return
            if c.discovered_via == "commoncrawl":
                found.name = await _company_name(http, found.ats, found.token)
            funnel.accepted_india += 1
            key = f"name_check:{found.name_check}"
            funnel.found_by[key] = funnel.found_by.get(key, 0) + 1
            accepted.append((c, found))

        await asyncio.gather(*(one(c) for c in fresh))
    added = await asyncio.to_thread(merge_discovered, accepted)
    funnel.seconds = round(time.perf_counter() - started, 1)
    report = {**asdict(funnel), "added_to_companies_discovered": added}
    await asyncio.to_thread(_write_report, report_dir, source, report)
    print(json.dumps(report, indent=2))
    return 0


def _write_report(report_dir: Path, source: str, report: dict[str, Any]) -> None:
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / f"discovery-{source}.json").write_text(json.dumps(report, indent=2) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.ingest.discover")
    parser.add_argument("source", choices=["yc", "elevation", "commoncrawl"])
    parser.add_argument("--limit", type=int, default=None, help="check at most N candidates")
    parser.add_argument("--pages-per-prefix", type=int, default=2, help="Common Crawl pages")
    parser.add_argument("--report-dir", type=Path, default=Path("discovery-reports"))
    args = parser.parse_args(argv)
    configure_logging(get_settings().log_level)

    async def go() -> int:
        try:
            return await run(args.source, args.limit, args.pages_per_prefix, args.report_dir)
        finally:
            await redis.aclose()

    return asyncio.run(go())


if __name__ == "__main__":
    sys.exit(main())
