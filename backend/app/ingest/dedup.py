"""Duplicate detection, recomputed from scratch on every run so it is idempotent and
self-healing (if a canonical posting expires, its duplicates are re-evaluated).

1. Exact, same company: identical content hash (which includes title, description,
   location and salary).
2. Exact, same company: same normalised title and normalised location.
3. Near-duplicate, same company: embedding cosine similarity above the threshold, only
   between postings with the same location, work countries, eligibility scope and
   remote policy. This catches reworded reposts; the same role offered in two cities
   stays two postings, so a duplicate never hides one a candidate could prefer or take.

The earliest-seen posting is canonical (ties: earlier posted_at, then id); the others
point to it through duplicate_of.
Expired postings take no part.
"""

import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Job

_EXACT = """
WITH ranked AS (
    SELECT id,
           first_value(id) OVER (
               PARTITION BY company_id, {key}
               ORDER BY first_seen_at, posted_at NULLS LAST, id
           ) AS canonical
    FROM jobs
    WHERE status != 'expired' AND duplicate_of IS NULL
)
UPDATE jobs SET duplicate_of = ranked.canonical, duplicate_reason = :reason
FROM ranked
WHERE jobs.id = ranked.id AND ranked.canonical != jobs.id
RETURNING jobs.id
"""

_NEAR_PAIRS = text("""
SELECT a.id, a.first_seen_at, b.id, b.first_seen_at
FROM jobs a
JOIN jobs b
  ON a.company_id = b.company_id
 AND (a.first_seen_at, a.id) < (b.first_seen_at, b.id)
WHERE a.status != 'expired' AND b.status != 'expired'
  AND a.duplicate_of IS NULL AND b.duplicate_of IS NULL
  AND a.embedding IS NOT NULL AND b.embedding IS NOT NULL
  AND a.location_norm = b.location_norm
  AND a.work_countries = b.work_countries
  AND a.eligibility_scope = b.eligibility_scope
  AND a.remote_policy = b.remote_policy
  AND (a.embedding <=> b.embedding) < :max_distance
""")


async def deduplicate(session: AsyncSession, near_threshold: float) -> dict[str, int]:
    await session.execute(
        update(Job)
        .where(Job.status != "expired", Job.duplicate_of.is_not(None))
        .values(duplicate_of=None, duplicate_reason=None)
    )
    counts = {}
    for reason, key in (
        ("content_hash", "content_hash"),
        ("title_location", "title_norm, location_norm"),
    ):
        result = await session.execute(text(_EXACT.format(key=key)), {"reason": reason})
        counts[reason] = len(result.all())

    await _flatten_chains(session)

    pairs = (await session.execute(_NEAR_PAIRS, {"max_distance": 1 - near_threshold})).all()
    canonical_of = _resolve(pairs)
    for duplicate, canonical in canonical_of.items():
        await session.execute(
            update(Job)
            .where(Job.id == duplicate)
            .values(duplicate_of=canonical, duplicate_reason="near_duplicate")
        )
    counts["near_duplicate"] = len(canonical_of)
    await _flatten_chains(session)
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


def _resolve(pairs: Sequence[Any]) -> dict[uuid.UUID, uuid.UUID]:
    """Groups matching postings (transitively) and points every member at the group's
    earliest-seen posting. Each pair is (id_a, first_seen_a, id_b, first_seen_b)."""
    parent: dict[uuid.UUID, uuid.UUID] = {}
    order: dict[uuid.UUID, tuple[datetime, str]] = {}

    def root(node: uuid.UUID) -> uuid.UUID:
        while parent.get(node, node) != node:
            node = parent[node]
        return node

    for a_id, a_seen, b_id, b_seen in pairs:
        order[a_id] = (a_seen, str(a_id))
        order[b_id] = (b_seen, str(b_id))
        parent.setdefault(a_id, a_id)
        parent.setdefault(b_id, b_id)
        ra, rb = root(a_id), root(b_id)
        if ra != rb:
            parent[rb] = ra

    groups: dict[uuid.UUID, list[uuid.UUID]] = {}
    for node in parent:
        groups.setdefault(root(node), []).append(node)
    canonical_of: dict[uuid.UUID, uuid.UUID] = {}
    for members in groups.values():
        canonical = min(members, key=order.__getitem__)
        canonical_of.update({m: canonical for m in members if m != canonical})
    return canonical_of
