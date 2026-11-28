"""Duplicate detection, recomputed from scratch on every run so it is idempotent and
self-healing (if a canonical posting expires, its duplicates are re-evaluated).

1. Exact, same company: identical content hash (title, description, location, salary).
2. Text near-duplicates, same company and same normalised title (lexical; the approach is
   credited to hireplz, MIT, github.com/nishant-Tiwari24/hireplz; the code is ours):
   - cross_source: postings from different sources whose locations are compatible and
     whose shorter text's words are mostly contained in the longer one (Adzuna gives
     ~500-character snippets, so containment, not overlap);
   - near_duplicate_text: word-set overlap (Jaccard) >= INGEST_NEAR_DUPLICATE_THRESHOLD
     on boilerplate-stripped text - the same posting in another city or reposted.
   Matches chain (A~B, B~C groups A, B, C), but a posting joins a group only if it also
   matches the group's canonical posting with Jaccard >= INGEST_NEAR_DUPLICATE_CANONICAL_MIN
   (0.85; cross-source members need the usual containment). Postings that fail are
   grouped again among themselves under the same rule. Owner review 2026-11-25: a chain
   through an Adzuna snippet merged two different AlphaSense roles (Jaccard 0.447), while
   chained MongoDB city variants (0.88-0.89 against the kept job) are the same role.
   Two postings from the same source at the same normalised location (equal, or one a
   word-prefix of the other: "dublin" / "dublin ireland") need Jaccard >= INGEST_NEAR_
   DUPLICATE_SAME_LOCATION_MIN (0.97): same city, same title and a few sentences apart is
   more often two requisitions than one (owner review 2026-11-25: Stripe, Dublin, 0.935).
   There is no merge on title and location alone: until 2026-11-25 an exact pass merged
   same company + normalised title + normalised location without reading the text, and
   228 of its 423 merges shared less than half their words with the kept posting
   (MongoDB "Software Engineer 3", Gurugram, 0.19: different openings). Those pairs now
   meet the same rule as any other same-location pair (owner decision 2026-11-25).
   Pairs the owner judged different are listed in data/not_duplicates.yaml and never end
   up in one group.
   Both only between postings with the same work eligibility (scope and countries) and,
   for near_duplicate_text, the same remote policy: hiding a duplicate must never hide
   the only copy a candidate in some country can apply to. Buckets of more than
   MAX_BUCKET postings are skipped (bulk roles where pairwise checks cost more than they
   find). This replaces the embedding near-duplicate pass, which hid distinct roles.

The canonical posting prefers the company's own ATS (source_quality ats_direct, then
aggregator_full, then aggregator_snippet), then the earliest seen (then posted_at, id).
The others point to it through duplicate_of, and the canonical lists them in
alternate_sources ("also posted in X"). Expired postings take no part.
"""

import re
import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from functools import cache
from itertools import combinations
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.models import Job

MAX_BUCKET = 200
CROSS_SOURCE_MIN_CONTAINMENT = 0.6
_QUALITY_RANK = (
    "CASE source_quality WHEN 'ats_direct' THEN 0 WHEN 'aggregator_full' THEN 1 ELSE 2 END"
)
_RANK = {"ats_direct": 0, "aggregator_full": 1, "aggregator_snippet": 2}

_EXACT = """
WITH ranked AS (
    SELECT id,
           first_value(id) OVER (
               PARTITION BY company_id, {key}
               ORDER BY {rank}, first_seen_at, posted_at NULLS LAST, id
           ) AS canonical
    FROM jobs
    WHERE status != 'expired' AND duplicate_of IS NULL
)
UPDATE jobs SET duplicate_of = ranked.canonical, duplicate_reason = :reason
FROM ranked
WHERE jobs.id = ranked.id AND ranked.canonical != jobs.id
RETURNING jobs.id
"""

_BUCKETS_SQL = """
WITH candidates AS (
    SELECT * FROM jobs
    WHERE status != 'expired' AND ({unmarked})
),
buckets AS (
    SELECT company_id, title_norm, count(*) AS n
    FROM candidates
    GROUP BY company_id, title_norm
    HAVING count(*) > 1
)
SELECT j.id, j.source_id, j.company_id, j.title_norm, j.source, j.source_quality, j.first_seen_at,
       j.posted_at, j.location, j.location_norm, j.work_countries, j.eligibility_scope,
       j.remote_policy, coalesce(j.search_text, j.description) AS body, b.n
FROM candidates j JOIN buckets b USING (company_id, title_norm)
ORDER BY j.company_id, j.title_norm
"""
_UNMARKED = "duplicate_of IS NULL"
# For review after a run: the text pass's own marks count as unmarked again.
_UNMARKED_OR_TEXT = (
    "duplicate_of IS NULL OR duplicate_reason IN ('cross_source', 'near_duplicate_text')"
)


_WORD = re.compile(r"[a-z0-9][a-z0-9+#.]*", re.IGNORECASE)


_NOT_DUPLICATES = Path(__file__).resolve().parent / "data" / "not_duplicates.yaml"


@cache
def not_duplicates() -> frozenset[frozenset[str]]:
    """Owner verdicts "different": pairs of "source:source_id" keys kept apart."""
    raw = yaml.safe_load(_NOT_DUPLICATES.read_text(encoding="utf-8")) or {}
    return frozenset(frozenset(entry["pair"]) for entry in raw.get("pairs", []))


@dataclass(frozen=True)
class TextRules:
    """The text pass's thresholds (see the module docstring)."""

    threshold: float
    canonical_min: float | None = None
    same_location_min: float | None = None
    apart: frozenset[frozenset[str]] = field(default_factory=frozenset)


@dataclass(frozen=True)
class Posting:
    id: uuid.UUID
    source: str
    quality: str
    first_seen: datetime
    posted_at: datetime | None
    location: str
    location_norm: str
    eligibility: tuple[str, tuple[str, ...]]
    remote_policy: str
    words: frozenset[str]
    source_id: str = ""

    @property
    def key(self) -> str:
        return f"{self.source}:{self.source_id}"

    def order(self) -> tuple[int, datetime, float, str]:
        posted = self.posted_at.timestamp() if self.posted_at else float("inf")
        return (_RANK.get(self.quality, 3), self.first_seen, posted, str(self.id))


@dataclass(frozen=True)
class Pair:
    canonical: Posting
    duplicate: Posting
    reason: str  # cross_source | near_duplicate_text
    similarity: float


def words(body: str) -> frozenset[str]:
    return frozenset(w.lower().rstrip(".") for w in _WORD.findall(body) if len(w) > 1)


def jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def containment(a: frozenset[str], b: frozenset[str]) -> float:
    """Share of the smaller set's words found in the larger one."""
    small, large = (a, b) if len(a) <= len(b) else (b, a)
    return len(small & large) / len(small) if small else 0.0


def same_location(a: Posting, b: Posting) -> bool:
    """Equal normalised locations, or one a word-prefix of the other."""
    x, y = a.location_norm, b.location_norm
    return x == y or (bool(x and y) and (x.startswith(y + " ") or y.startswith(x + " ")))


def match(
    a: Posting, b: Posting, threshold: float, same_location_min: float | None = None
) -> tuple[str, float] | None:
    if a.eligibility != b.eligibility:
        return None
    if a.source != b.source:
        score = containment(a.words, b.words)
        return ("cross_source", score) if score >= CROSS_SOURCE_MIN_CONTAINMENT else None
    if a.remote_policy != b.remote_policy:
        return None
    if same_location_min is not None and same_location(a, b):
        threshold = max(threshold, same_location_min)
    score = jaccard(a.words, b.words)
    return ("near_duplicate_text", score) if score >= threshold else None


@dataclass
class TextDuplicates:
    pairs: list[Pair]  # every matching pair (for review)
    canonical_of: dict[uuid.UUID, tuple[uuid.UUID, str]]  # duplicate -> (canonical, reason)
    skipped_buckets: int
    skipped_postings: int


async def find_text_duplicates(
    session: AsyncSession, rules: TextRules, *, include_text_marked: bool = False
) -> TextDuplicates:
    """Read-only: the near-duplicate groups the next dedup pass would mark.
    `include_text_marked` re-finds the pairs the last pass already marked (for review)."""
    unmarked = _UNMARKED_OR_TEXT if include_text_marked else _UNMARKED
    rows = (await session.execute(text(_BUCKETS_SQL.format(unmarked=unmarked)))).all()
    buckets: dict[tuple[Any, str], list[Posting]] = {}
    skipped_buckets = skipped_postings = 0
    seen_big: set[tuple[Any, str]] = set()
    for r in rows:
        key = (r.company_id, r.title_norm)
        if r.n > MAX_BUCKET:
            if key not in seen_big:
                seen_big.add(key)
                skipped_buckets += 1
                skipped_postings += r.n
            continue
        buckets.setdefault(key, []).append(
            Posting(
                id=r.id,
                source=r.source,
                quality=r.source_quality,
                first_seen=r.first_seen_at,
                posted_at=r.posted_at,
                location=r.location,
                location_norm=r.location_norm,
                eligibility=(r.eligibility_scope, tuple(sorted(r.work_countries))),
                remote_policy=r.remote_policy,
                words=words(r.body or ""),
                source_id=r.source_id,
            )
        )
    pairs: list[Pair] = []
    canonical_of: dict[uuid.UUID, tuple[uuid.UUID, str]] = {}
    for members in buckets.values():
        edges = []
        for a, b in combinations(members, 2):
            found = match(a, b, rules.threshold, rules.same_location_min)
            if found is not None and frozenset((a.key, b.key)) not in rules.apart:
                first, second = sorted((a, b), key=Posting.order)
                pairs.append(Pair(first, second, found[0], found[1]))
                edges.append((a, b))
        for member, canonical in assign_groups(edges, rules).items():
            reason = "cross_source" if member.source != canonical.source else "near_duplicate_text"
            canonical_of[member.id] = (canonical.id, reason)
    return TextDuplicates(pairs, canonical_of, skipped_buckets, skipped_postings)


def assign_groups(edges: list[tuple[Posting, Posting]], rules: TextRules) -> dict[Posting, Posting]:
    """Duplicate -> its canonical posting. Groups are connected components of `edges`;
    each keeps its best posting (Posting.order). A member leaves its group when it does
    not also match the canonical posting at `rules.canonical_min` (if set), or when the
    owner keeps it apart from a posting already in the group; the members that left are
    grouped again among themselves (their edges only), until every group passes."""
    assigned: dict[Posting, Posting] = {}
    while edges:
        left: set[uuid.UUID] = set()
        for group in _groups(edges):
            canonical = min(group, key=Posting.order)
            kept = [canonical]
            for member in sorted(group, key=Posting.order):
                if member.id == canonical.id:
                    continue
                fits = rules.canonical_min is None or match(
                    canonical, member, rules.canonical_min, rules.same_location_min
                )
                if fits and not any(frozenset((member.key, k.key)) in rules.apart for k in kept):
                    assigned[member] = canonical
                    kept.append(member)
                else:
                    left.add(member.id)
        edges = [(a, b) for a, b in edges if a.id in left and b.id in left]
    return assigned


def _groups(edges: Iterable[tuple[Posting, Posting]]) -> list[list[Posting]]:
    parent: dict[uuid.UUID, uuid.UUID] = {}
    nodes: dict[uuid.UUID, Posting] = {}

    def root(node: uuid.UUID) -> uuid.UUID:
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    for a, b in edges:
        for p in (a, b):
            nodes[p.id] = p
            parent.setdefault(p.id, p.id)
        ra, rb = root(a.id), root(b.id)
        if ra != rb:
            parent[rb] = ra
    groups: dict[uuid.UUID, list[Posting]] = {}
    for node_id, posting in nodes.items():
        groups.setdefault(root(node_id), []).append(posting)
    return list(groups.values())


def text_rules(settings: Settings) -> TextRules | None:
    """The text pass's rules from settings, or None when the pass is off."""
    if settings.near_duplicate_threshold is None:
        return None
    return TextRules(
        threshold=settings.near_duplicate_threshold,
        canonical_min=settings.ingest_near_duplicate_canonical_min,
        same_location_min=settings.ingest_near_duplicate_same_location_min,
        apart=not_duplicates(),
    )


async def deduplicate(session: AsyncSession, rules: TextRules | None) -> dict[str, int]:
    """Recomputes duplicate_of and alternate_sources for every non-expired job.
    `rules=None` skips the text pass (cross_source and near_duplicate_text)."""
    await session.execute(
        update(Job)
        .where(Job.status != "expired", Job.duplicate_of.is_not(None))
        .values(duplicate_of=None, duplicate_reason=None)
    )
    counts: dict[str, int] = {}
    # A fixed template: the key is a column name, never input.
    sql = _EXACT.format(key="content_hash", rank=_QUALITY_RANK)
    result = await session.execute(text(sql), {"reason": "content_hash"})
    counts["content_hash"] = len(result.all())

    if rules is not None:
        found = await find_text_duplicates(session, rules)
        for duplicate, (canonical, reason) in found.canonical_of.items():
            await session.execute(
                update(Job)
                .where(Job.id == duplicate)
                .values(duplicate_of=canonical, duplicate_reason=reason)
            )
        for reason in ("cross_source", "near_duplicate_text"):
            counts[reason] = sum(1 for _, r in found.canonical_of.values() if r == reason)
        counts["text_buckets_skipped"] = found.skipped_buckets
        await _flatten_chains(session)

    await _alternate_sources(session)
    return counts


_FLATTEN = text("""
UPDATE jobs AS j SET duplicate_of = p.duplicate_of
FROM jobs AS p
WHERE j.duplicate_of = p.id AND p.duplicate_of IS NOT NULL
RETURNING j.id
""")


async def _flatten_chains(session: AsyncSession) -> None:
    """A later pass can mark an earlier pass's original as a duplicate itself (A -> B,
    then B -> C). Repoint every duplicate at the final original (A -> C)."""
    for _ in range(10):  # chains are at most a few links long
        if not (await session.execute(_FLATTEN)).all():
            return


_ALTERNATES = text("""
WITH alts AS (
    SELECT duplicate_of AS id,
           jsonb_agg(jsonb_build_object(
               'source', source,
               'source_url', source_url,
               'source_page_url', source_page_url,
               'location', location,
               'work_countries', to_jsonb(work_countries),
               'eligibility_scope', eligibility_scope,
               'reason', duplicate_reason
           ) ORDER BY first_seen_at, id) AS list
    FROM jobs
    WHERE duplicate_of IS NOT NULL AND status != 'expired'
    GROUP BY duplicate_of
)
UPDATE jobs SET alternate_sources = coalesce(alts.list, '[]'::jsonb)
FROM jobs AS j LEFT JOIN alts ON alts.id = j.id
WHERE jobs.id = j.id AND jobs.status != 'expired'
  AND jobs.alternate_sources IS DISTINCT FROM coalesce(alts.list, '[]'::jsonb)
""")


# Every non-expired job: its own location and countries, plus those of the duplicates
# merged into it (own first, then in first-seen order; locations without repeats).
_UNION = text("""
WITH variants AS (
    SELECT coalesce(duplicate_of, id) AS id, location, work_countries,
           row_number() OVER (
               PARTITION BY coalesce(duplicate_of, id)
               ORDER BY (duplicate_of IS NOT NULL), first_seen_at, id
           ) AS pos
    FROM jobs WHERE status != 'expired'
), locs AS (
    SELECT id, array_agg(location ORDER BY first_pos) AS list
    FROM (
        SELECT id, location, min(pos) AS first_pos
        FROM variants WHERE location != ''
        GROUP BY id, location
    ) distinct_locations
    GROUP BY id
), countries AS (
    SELECT id, array_agg(DISTINCT c ORDER BY c) AS list
    FROM variants, unnest(work_countries) AS c
    GROUP BY id
), merged AS (
    SELECT j.id,
           coalesce(locs.list, '{}'::varchar[]) AS all_locations,
           coalesce(countries.list, '{}'::varchar[]) AS all_work_countries
    FROM jobs j LEFT JOIN locs ON locs.id = j.id LEFT JOIN countries ON countries.id = j.id
    WHERE j.status != 'expired'
)
UPDATE jobs SET all_locations = merged.all_locations,
                all_work_countries = merged.all_work_countries
FROM merged
WHERE jobs.id = merged.id
  AND (jobs.all_locations IS DISTINCT FROM merged.all_locations
       OR jobs.all_work_countries IS DISTINCT FROM merged.all_work_countries)
""")


# Openings: the most postings of the group (a job and its duplicates) from one source at
# one normalised location. Owner review 2026-11-25: two Databricks requisitions with the
# same text in Bengaluru are one role with 2 openings, not two results; city variants
# of a role are one opening in each city, so they do not add up.
_OPENINGS = text("""
WITH cells AS (
    SELECT coalesce(duplicate_of, id) AS id, count(*) AS n
    FROM jobs WHERE status != 'expired'
    GROUP BY coalesce(duplicate_of, id), source, location_norm
), groups AS (
    SELECT id, max(n) AS openings FROM cells GROUP BY id
)
UPDATE jobs SET openings_count = CASE WHEN jobs.duplicate_of IS NULL
                                      THEN coalesce(groups.openings, 1) ELSE 1 END
FROM jobs AS j LEFT JOIN groups ON groups.id = j.id
WHERE jobs.id = j.id AND jobs.status != 'expired'
  AND jobs.openings_count IS DISTINCT FROM
      CASE WHEN jobs.duplicate_of IS NULL THEN coalesce(groups.openings, 1) ELSE 1 END
""")


async def _alternate_sources(session: AsyncSession) -> None:
    """Each canonical job lists its duplicates ("also posted in X" / "also on Adzuna"),
    carries the union of their locations and countries, and its openings count."""
    await session.execute(_ALTERNATES)
    await session.execute(_UNION)
    await session.execute(_OPENINGS)
