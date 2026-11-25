"""Pooling (Phase 4 brief, item 3): which (profile, job) pairs get judged and labelled.

Every variant is run on the frozen snapshot for every profile, in two modes:
- `query`: the profile's query plus its profile (what a user typing a search gets);
- `profile`: the profile alone (the retrievers read its skills).
Variants per mode, from four searches (ADR 0003 rerank candidates):
- bm25, vector, fused (RRF): the stage ranks of the no-rerank search;
- rescore: the personalised re-score without rerank (top 0);
- rerank_10_128, rerank_20_128, rerank_30_256: cross-encoder on the fused top N.
Every ranking (top 30, the API's limit) is kept in runs.jsonl.

Selection, per profile, `per_profile` pairs (20): candidates are the jobs in any
variant's top `depth` (10), best first by (best rank in any variant, then the number of
variants that put it in their top 10, then id), so each variant's rank 1 comes before
any rank 2. Stratified: at most half from one source and at most `max_gig` freelance
gigs and `max_agency` staffing-agency postings, so Himalayas, gig work and agencies
cannot dominate; if a profile runs out of other candidates, the caps are relaxed
(recorded per pair as strata["over_cap"] = "yes"). If the top-`depth` union has fewer
than `per_profile` jobs, deeper ranks are added.
"""

import uuid
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.eval.profiles import EvalProfile
from app.retrieval.bm25 import Bm25Holder, Bm25Index, load_index
from app.retrieval.service import RerankProfile, SearchEngine, search

RERANKS = (
    RerankProfile("rescore", 0, 128),
    RerankProfile("rerank_10_128", 10, 128),
    RerankProfile("rerank_20_128", 20, 128),
    RerankProfile("rerank_30_256", 30, 256),
)
STAGES = ("bm25", "vector", "fused")
LIMIT = 30


class FixedBm25(Bm25Holder):
    """A BM25 holder that always returns one index (the snapshot's), never swapping."""

    def __init__(self, directory: Path) -> None:  # no Redis: nothing to check
        self._index = load_index(directory)

    async def current(self) -> Bm25Index | None:
        return self._index


@dataclass(frozen=True)
class JobFacts:
    source: str
    engagement: str
    poster: str


@dataclass
class Candidate:
    job_id: str
    variants: dict[str, int] = field(default_factory=dict)

    def key(self, depth: int) -> tuple[int, int, str]:
        best = min(self.variants.values())
        in_top = sum(1 for r in self.variants.values() if r <= depth)
        return (best, -in_top, self.job_id)


async def run_variants(
    session: AsyncSession, engine: SearchEngine, profile: EvalProfile, settings: Settings
) -> dict[str, list[str]]:
    """variant name ("query:bm25", "profile:rerank_10_128", ...) -> job ids, best first."""
    rankings: dict[str, list[str]] = {}
    for mode, with_query in (("query", True), ("profile", False)):
        request = profile.search_request(with_query=with_query, limit=LIMIT)
        for rerank in RERANKS:
            response = await search(session, engine, request, settings, rerank)
            rankings[f"{mode}:{rerank.name}"] = [str(r.job.id) for r in response.results]
            if rerank.top == 0:
                for stage in STAGES:
                    ranked = sorted(
                        (r for r in response.results if getattr(r.scores.ranks, stage)),
                        key=lambda r, s=stage: getattr(r.scores.ranks, s),  # type: ignore[misc]
                    )
                    rankings[f"{mode}:{stage}"] = [str(r.job.id) for r in ranked]
    return rankings


def candidates(rankings: dict[str, list[str]]) -> dict[str, Candidate]:
    found: dict[str, Candidate] = {}
    for variant, ids in rankings.items():
        for rank, job_id in enumerate(ids, start=1):
            found.setdefault(job_id, Candidate(job_id)).variants[variant] = rank
    return found


def select_pool(
    rankings: dict[str, list[str]],
    facts: dict[str, JobFacts],
    *,
    per_profile: int = 20,
    depth: int = 10,
    max_gig: int = 3,
    max_agency: int = 3,
) -> list[tuple[Candidate, bool]]:
    """(candidate, over_cap) in selection order. Only jobs in `facts` are eligible (the
    snapshot's searchable jobs)."""
    pool = [c for c in candidates(rankings).values() if c.job_id in facts]
    max_source = per_profile // 2
    chosen: list[tuple[Candidate, bool]] = []
    taken: set[str] = set()
    sources: Counter[str] = Counter()
    gigs = agencies = 0
    # Caps first at every depth; only then, if still short, relax them.
    for relaxed in (False, True):
        for limit_depth in sorted({depth, LIMIT}):
            tier = sorted(
                (c for c in pool if min(c.variants.values()) <= limit_depth),
                key=lambda c: c.key(depth),
            )
            for c in tier:
                if len(chosen) >= per_profile:
                    return chosen
                if c.job_id in taken:
                    continue
                f = facts[c.job_id]
                gig = f.engagement == "freelance_gig"
                agency = f.poster == "staffing_agency"
                over = (
                    sources[f.source] >= max_source
                    or (gig and gigs >= max_gig)
                    or (agency and agencies >= max_agency)
                )
                if over and not relaxed:
                    continue
                chosen.append((c, over))
                taken.add(c.job_id)
                sources[f.source] += 1
                gigs += gig
                agencies += agency
    return chosen


async def job_facts(session: AsyncSession, ids: set[str]) -> dict[str, JobFacts]:
    from app.models import Job

    rows = (
        await session.execute(
            select(Job.id, Job.source, Job.engagement_type, Job.poster_type).where(
                Job.id.in_([uuid.UUID(i) for i in ids]),
                Job.status != "expired",
                Job.duplicate_of.is_(None),
            )
        )
    ).all()
    return {str(r.id): JobFacts(r.source, r.engagement_type, r.poster_type) for r in rows}


def pool_summary(
    chosen: dict[str, list[tuple[Candidate, bool]]], facts: dict[str, JobFacts]
) -> dict[str, Any]:
    flat = [(pid, c, over) for pid, items in chosen.items() for c, over in items]
    by_variant_top10: Counter[str] = Counter()
    for _, c, _ in flat:
        for variant, rank in c.variants.items():
            if rank <= 10:
                by_variant_top10[variant] += 1
    return {
        "pairs": len(flat),
        "profiles": len(chosen),
        "per_profile": {pid: len(items) for pid, items in chosen.items()},
        "by_source": dict(Counter(facts[c.job_id].source for _, c, _ in flat)),
        "by_engagement": dict(Counter(facts[c.job_id].engagement for _, c, _ in flat)),
        "by_poster": dict(Counter(facts[c.job_id].poster for _, c, _ in flat)),
        "over_cap": sum(1 for *_, over in flat if over),
        "pooled_from_top10_of_variant": dict(sorted(by_variant_top10.items())),
    }
