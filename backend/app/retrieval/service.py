"""The search pipeline (PLAN.md §2.1):

  dealbreakers (SQL) -> allowed ids
  BM25 top N (masked to allowed ids)  and  vector top N (HNSW, same WHERE)
  -> RRF -> cross-encoder rerank of the top M -> personalised re-score -> top `limit`

plus the "ruled out" list (postings that match the query but a dealbreaker excluded,
labelled by the same rule expressions the filter used) and pool counts.

Both models run on one dedicated thread per process: concurrent searches queue for it
rather than each spawning onnxruntime threads (see the 2026-11-21 decision on the
embedder's thread). BM25 runs in the default thread pool; it is numpy and short.
"""

import asyncio
import functools
import hashlib
import json
import logging
import time
import uuid
from collections import OrderedDict
from collections.abc import Callable, Iterator
from collections.abc import Set as AbstractSet
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.metrics import BM25_DOCUMENTS, SEARCH_STAGE_DURATION, SEARCHES
from app.ingest.freshness import cached_freshness
from app.models import Company, Job
from app.retrieval.bm25 import Bm25Holder, Bm25Index
from app.retrieval.filters import PoolCounts, RuleResult, allowed_ids, outcomes, pool_counts
from app.retrieval.rules import Rule, WorkEligibility, allowed, base_pool, needs_company
from app.retrieval.schemas import (
    JobSummary,
    PoolSummary,
    RuleBreach,
    RuledOut,
    Salary,
    Scores,
    SearchRequest,
    SearchResponse,
    SearchResult,
    StageRanks,
)
from app.retrieval.scoring import JobFacts, RuleFlag, Weights, explain, final_score, rrf
from app.retrieval.vector import vector_search

logger = logging.getLogger(__name__)

# Characters of search_text handed to the reranker's tokenizer; it truncates to
# RERANK_MAX_TOKENS anyway, this only avoids tokenising whole long postings.
_PASSAGE_CHARS = 2000
_CACHE_PREFIX = "search:v1:"
# Distinct dealbreaker sets whose allowed ids and counts each process keeps.
_POOL_CACHE_SIZE = 64


class QueryEmbedder(Protocol):
    def embed_query(self, query: str) -> list[float]: ...


class PassageReranker(Protocol):
    def score(self, query: str, passages: list[str], max_tokens: int) -> list[float]: ...


@dataclass(frozen=True)
class RerankProfile:
    """How much of the fused list the cross-encoder scores (ADR 0003). top 0 = no rerank."""

    name: str
    top: int
    tokens: int


def rerank_profile(settings: Settings, name: str) -> RerankProfile:
    if name == "interactive":
        return RerankProfile(
            name, settings.rerank_interactive_top, settings.rerank_interactive_tokens
        )
    if name == "digest":
        return RerankProfile(name, settings.rerank_digest_top, settings.rerank_digest_tokens)
    raise ValueError(f"unknown rerank profile {name!r}")


class SearchEngine:
    """What a search needs besides the database: the two models and the BM25 index."""

    def __init__(
        self,
        embedder: QueryEmbedder,
        reranker: PassageReranker,
        bm25: Bm25Holder | None,
    ) -> None:
        self.embedder = embedder
        self.reranker = reranker
        self.bm25 = bm25
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="models")
        self._pool_cache: OrderedDict[tuple[str, str], tuple[frozenset[uuid.UUID], PoolCounts]]
        self._pool_cache = OrderedDict()

    async def pool_view(
        self, session: AsyncSession, rules: list[Rule], version: str | None
    ) -> tuple[frozenset[uuid.UUID], PoolCounts, bool]:
        """(allowed ids, pool counts, from cache). Both depend only on the dealbreakers
        and the pool, and the pool changes only at an ingest, which publishes a new BM25
        version; so they are cached per (version, rules) in this process. Without an
        index there is no version to key on, and nothing is cached."""
        key = None
        if version is not None:
            # The UTC date too: a rule like posted_within_days changes with the clock
            # even when the pool does not.
            day = datetime.now(UTC).date().isoformat()
            rules_key = json.dumps([r.model_dump() for r in rules], sort_keys=True)
            key = (f"{version}|{day}", rules_key)
            if (hit := self._pool_cache.get(key)) is not None:
                self._pool_cache.move_to_end(key)
                return (*hit, True)
        ids = frozenset(await allowed_ids(session, rules))
        counts = await pool_counts(session, rules)
        if key is not None:
            self._pool_cache[key] = (ids, counts)
            while len(self._pool_cache) > _POOL_CACHE_SIZE:
                self._pool_cache.popitem(last=False)
        return ids, counts, False

    async def on_model_thread[T](self, fn: Callable[..., T], *args: Any) -> T:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._executor, functools.partial(fn, *args))

    async def bm25_index(self) -> Bm25Index | None:
        if self.bm25 is None:
            return None
        index = await self.bm25.current()
        if index is not None:
            BM25_DOCUMENTS.set(len(index.job_ids))
        return index

    def close(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)


def build_engine(settings: Settings, redis: Redis) -> SearchEngine:
    """The production engine: real models and the Redis-tracked index."""
    from app.ml.embedder import OnnxEmbedder
    from app.ml.reranker import OnnxReranker

    embedder = OnnxEmbedder(
        Path(settings.embedding_model_dir),
        settings.embedding_model_file,
        settings.embedding_threads,
    )
    reranker = OnnxReranker(
        Path(settings.reranker_model_dir),
        settings.reranker_model_file,
        threads=settings.reranker_threads,
        batch_size=settings.reranker_batch_size,
    )
    holder = Bm25Holder(Path(settings.bm25_index_dir), redis, settings.bm25_version_check_seconds)
    return SearchEngine(embedder, reranker, holder)


class Timer:
    def __init__(self) -> None:
        self.ms: dict[str, float] = {}
        self._started = time.perf_counter()

    @contextmanager
    def stage(self, name: str) -> Iterator[None]:
        started = time.perf_counter()
        try:
            yield
        finally:
            seconds = time.perf_counter() - started
            self.ms[name] = round(seconds * 1000, 2)
            SEARCH_STAGE_DURATION.labels(name).observe(seconds)

    def finish(self) -> dict[str, float]:
        seconds = time.perf_counter() - self._started
        SEARCH_STAGE_DURATION.labels("total").observe(seconds)
        return {**self.ms, "total": round(seconds * 1000, 2)}


_SUMMARY_COLUMNS = (
    Job.id,
    Job.title,
    Company.name.label("company"),
    Job.location,
    Job.remote_policy,
    Job.seniority,
    Job.employment_type,
    Job.salary_min,
    Job.salary_max,
    Job.salary_currency,
    Job.salary_interval,
    Job.salary_min_usd,
    Job.salary_max_usd,
    Job.skills,
    Job.source,
    Job.source_url,
    Job.posted_at,
    Job.first_seen_at,
    Job.status,
    Job.work_countries,
    Job.all_work_countries,
    Job.all_locations,
    Job.alternate_sources,
    Job.eligibility_scope,
    Job.search_text,
)


@dataclass(frozen=True)
class LoadedJob:
    summary: JobSummary
    facts: JobFacts
    passage: str


def candidate_country(rules: list[Rule]) -> str | None:
    return next((r.country for r in rules if isinstance(r, WorkEligibility)), None)


def primary_location(
    own: str,
    own_scope: str,
    own_countries: list[str],
    alternates: list[dict[str, Any]],
    country: str | None,
) -> str:
    """The job's own location, unless a candidate country is known, the job itself is not
    open to it, and a merged variant is: then that variant's location ("Bengaluru" over
    "New York" for a candidate in India)."""
    if country is None or own_scope == "worldwide" or country in own_countries:
        return own
    for alt in alternates:
        countries = alt.get("work_countries") or []
        if alt.get("location") and (
            alt.get("eligibility_scope") == "worldwide" or country in countries
        ):
            return str(alt["location"])
    return own


async def load_jobs(
    session: AsyncSession, ids: list[uuid.UUID], country: str | None = None
) -> dict[uuid.UUID, LoadedJob]:
    if not ids:
        return {}
    rows = (
        await session.execute(
            select(*_SUMMARY_COLUMNS)
            .join(Company, Company.id == Job.company_id)
            .where(Job.id.in_(ids))
        )
    ).all()
    out: dict[uuid.UUID, LoadedJob] = {}
    for r in rows:
        primary = primary_location(
            r.location, r.eligibility_scope, list(r.work_countries), r.alternate_sources, country
        )
        locations = [primary, *(loc for loc in r.all_locations if loc != primary)]
        summary = JobSummary(
            id=r.id,
            title=r.title,
            company=r.company,
            location=primary,
            locations=[loc for loc in locations if loc],
            remote_policy=r.remote_policy,
            seniority=r.seniority,
            employment_type=r.employment_type,
            salary=Salary(
                min=None if r.salary_min is None else float(r.salary_min),
                max=None if r.salary_max is None else float(r.salary_max),
                currency=r.salary_currency,
                interval=r.salary_interval,
                min_usd=r.salary_min_usd,
                max_usd=r.salary_max_usd,
            ),
            skills=list(r.skills),
            source=r.source,
            source_url=r.source_url,
            posted_at=r.posted_at,
            first_seen_at=r.first_seen_at,
            status=r.status,
        )
        facts = JobFacts(
            skills=list(r.skills),
            seniority=r.seniority,
            remote_policy=r.remote_policy,
            work_countries=list(r.all_work_countries),
            eligibility_scope=r.eligibility_scope,
        )
        out[r.id] = LoadedJob(summary, facts, passage(r.title, r.skills, r.search_text))
    return out


def passage(title: str, skills: list[str], search_text: str | None) -> str:
    """What the cross-encoder reads for a job: title, skills, then the start of the text
    the vectors were built from."""
    return "\n".join([title, ", ".join(skills), (search_text or "")[:_PASSAGE_CHARS]])


def flags_for(results: list[RuleResult]) -> list[RuleFlag]:
    return [
        RuleFlag(kind=r.rule.kind, rule=r.rule.describe(), reason=r.rule.unknown_reason())
        for r in results
        if r.flags
    ]


def breaches_for(results: list[RuleResult]) -> list[RuleBreach]:
    return [
        RuleBreach(
            kind=r.rule.kind,
            rule=r.rule.describe(),
            outcome="violates" if r.outcome == "violates" else "unknown",
            reason=r.rule.unknown_reason() if r.outcome == "unknown" else None,
        )
        for r in results
        if r.excludes
    ]


def weights(settings: Settings) -> Weights:
    return Weights(
        rerank=settings.search_weight_rerank,
        skills=settings.search_weight_skills,
        experience=settings.search_weight_experience,
        preferences=settings.search_weight_preferences,
    )


async def search(
    session: AsyncSession,
    engine: SearchEngine,
    request: SearchRequest,
    settings: Settings,
    profile: RerankProfile | None = None,
) -> SearchResponse:
    """Cascade: the cross-encoder scores the fused top `profile.top`, which are ordered by
    the re-score; if `limit` asks for more, the next fused jobs follow in fused order,
    unreranked (`rerank_logit` null). With top 0 every candidate is ordered by the
    re-score without the rerank component."""
    profile = profile or rerank_profile(settings, "interactive")
    timer = Timer()
    query = request.query_text()
    rules: list[Rule] = list(request.rules)
    where = allowed(rules)
    join = needs_company(rules)
    n = settings.search_candidates
    degraded: list[str] = []

    index = await engine.bm25_index()
    if index is None:
        degraded.append("bm25_unavailable")
    with timer.stage("filter"):
        allowed_set, counts, _ = await engine.pool_view(
            session, rules, index.version if index else None
        )
    with timer.stage("embed_query"):
        query_vector = await engine.on_model_thread(engine.embedder.embed_query, query)
    with timer.stage("bm25"):
        bm25_hits = await asyncio.to_thread(index.search, query, n, allowed_set) if index else []
    with timer.stage("vector"):
        vector_hits = await vector_search(
            session,
            query_vector,
            where,
            k=n,
            ef_search=settings.search_hnsw_ef_search,
            join_company=join,
        )
    bm25_ids = [job_id for job_id, _ in bm25_hits]
    vector_ids = [job_id for job_id, _ in vector_hits]
    with timer.stage("fuse"):
        fused = rrf([bm25_ids, vector_ids], settings.search_rrf_k)
    bm25_rank = {job_id: i for i, job_id in enumerate(bm25_ids, start=1)}
    vector_rank = {job_id: i for i, job_id in enumerate(vector_ids, start=1)}
    fused_rank = {job_id: i for i, (job_id, _) in enumerate(fused, start=1)}
    candidates = fused[: max(profile.top, request.limit)]
    candidate_ids = [job_id for job_id, _ in candidates]

    with timer.stage("load"):
        jobs = await load_jobs(session, candidate_ids, candidate_country(rules))
        rule_results = await outcomes(session, rules, candidate_ids) if rules else {}
    candidates = [(job_id, score) for job_id, score in candidates if job_id in jobs]
    head, tail = candidates[: profile.top], candidates[profile.top :]

    with timer.stage("rerank"):
        head_logits = (
            await engine.on_model_thread(
                engine.reranker.score,
                query,
                [jobs[job_id].passage for job_id, _ in head],
                profile.tokens,
            )
            if head
            else []
        )
    logits: list[float | None] = [*head_logits, *([None] * len(tail))]

    with timer.stage("rescore"):
        w = weights(settings)
        scored: list[tuple[float, float, SearchResult]] = []
        for (job_id, rrf_score), logit in zip(candidates, logits, strict=True):
            loaded = jobs[job_id]
            explanation, components = explain(
                request.profile, loaded.facts, logit, flags_for(rule_results.get(job_id, []))
            )
            final = final_score(components, w)
            result = SearchResult(
                rank=0,
                job=loaded.summary,
                scores=Scores(
                    final=round(final, 6),
                    rerank_logit=None if logit is None else round(logit, 4),
                    rrf=round(rrf_score, 6),
                    components=components,
                    ranks=StageRanks(
                        bm25=bm25_rank.get(job_id),
                        vector=vector_rank.get(job_id),
                        fused=fused_rank[job_id],
                    ),
                ),
                explanation=explanation,
            )
            scored.append((final, rrf_score, result))

        def by_score(item: tuple[float, float, SearchResult]) -> tuple[float, float]:
            return (-item[0], -item[1])

        if head:  # the reranked head by score; the unreranked tail keeps fused order
            ordered = sorted(scored[: len(head)], key=by_score) + scored[len(head) :]
        else:
            ordered = sorted(scored, key=by_score)
        results = []
        for rank, (_, _, result) in enumerate(ordered[: request.limit], start=1):
            result.rank = rank
            results.append(result)

    ruled_out: list[RuledOut] = []
    if rules and settings.search_ruled_out_limit:
        with timer.stage("ruled_out"):
            ruled_out = await _ruled_out(
                session, engine, index, query, query_vector, rules, allowed_set, settings
            )

    SEARCHES.labels("degraded" if degraded else "ok").inc()
    return SearchResponse(
        query=query,
        results=results,
        ruled_out=ruled_out,
        pool=PoolSummary(
            pool=counts.pool,
            allowed=counts.allowed,
            ruled_out_by_rule=counts.ruled_out_by_rule,
            flagged_by_rule=counts.flagged_by_rule,
            eligibility=counts.eligibility,
            updated_at=(await cached_freshness(session)).last_success_at,
        ),
        bm25_version=index.version if index else None,
        rerank_profile=profile.name,
        reranked=len(head),
        degraded=degraded,
        timings_ms=timer.finish(),
    )


async def _ruled_out(
    session: AsyncSession,
    engine: SearchEngine,
    index: Bm25Index | None,
    query: str,
    query_vector: list[float],
    rules: list[Rule],
    allowed_set: AbstractSet[uuid.UUID],
    settings: Settings,
) -> list[RuledOut]:
    """The same retrieval without the dealbreakers; whatever the filter removed from it,
    best first, with each excluding rule. Labels come from the same rule expressions as
    the filter, so a job is listed here exactly when the filter excluded it."""
    n = settings.search_candidates
    bm25_hits = await asyncio.to_thread(index.search, query, n, None) if index else []
    vector_hits = await vector_search(
        session, query_vector, base_pool(), k=n, ef_search=settings.search_hnsw_ef_search
    )
    fused = rrf(
        [[job_id for job_id, _ in bm25_hits], [job_id for job_id, _ in vector_hits]],
        settings.search_rrf_k,
    )
    excluded = [job_id for job_id, _ in fused if job_id not in allowed_set]
    # outcomes() drops ids outside the pool (e.g. expired since the index was built).
    labels = await outcomes(session, rules, excluded)
    chosen = [job_id for job_id in excluded if job_id in labels][: settings.search_ruled_out_limit]
    jobs = await load_jobs(session, chosen, candidate_country(rules))
    return [
        RuledOut(job=jobs[job_id].summary, rules=breaches_for(labels[job_id]))
        for job_id in chosen
        if job_id in jobs
    ]


async def cached_search(
    session: AsyncSession,
    engine: SearchEngine,
    request: SearchRequest,
    settings: Settings,
    redis: Redis,
    user_id: uuid.UUID,
) -> SearchResponse:
    """`search`, cached per user in Redis. The key includes the BM25 index version, which
    changes after every ingest, so a cached response never outlives the pool it came
    from by more than one ingest. Redis errors fall through to a fresh search."""
    if settings.search_cache_seconds == 0:
        return await search(session, engine, request, settings)
    index = await engine.bm25_index()
    version = index.version if index else "none"
    digest = hashlib.sha256(f"{user_id}|{version}|{request.model_dump_json()}".encode()).hexdigest()
    key = _CACHE_PREFIX + digest
    try:
        hit = await redis.get(key)
    except RedisError:
        logger.warning("search cache unavailable")
        hit = None
    if hit is not None:
        SEARCHES.labels("cached").inc()
        response = SearchResponse.model_validate_json(hit)
        response.cached = True
        return response
    response = await search(session, engine, request, settings)
    try:
        await redis.set(key, response.model_dump_json(), ex=settings.search_cache_seconds)
    except RedisError:
        logger.warning("search cache unavailable")
    return response
