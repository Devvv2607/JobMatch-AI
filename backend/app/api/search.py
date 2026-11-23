import asyncio
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession, rate_limit_user
from app.core.config import get_settings
from app.core.errors import ErrorEnvelope, NotFoundError
from app.core.llm import build_llm_client
from app.core.llm.client import LLMClient
from app.core.ratelimit import enforce_rate_limit
from app.core.redis import redis
from app.models import Job
from app.retrieval.filters import outcomes
from app.retrieval.rules import Rule, base_pool
from app.retrieval.schemas import (
    ExplanationRequest,
    ExplanationSentence,
    SearchRequest,
    SearchResponse,
)
from app.retrieval.scoring import explain
from app.retrieval.sentence import take_quota, write_sentence
from app.retrieval.service import SearchEngine, build_engine, cached_search, flags_for, load_jobs

router = APIRouter(prefix="/search", tags=["search"])

# Built on first use, not at import or startup: loading two ONNX models takes a few
# seconds and ~150 MB, and the auth endpoints and tests that never search should not pay
# for it. Closed in the app lifespan.
_engine: SearchEngine | None = None
_llm: tuple[LLMClient, httpx.AsyncClient] | None = None


_engine_lock = asyncio.Lock()


async def get_search_engine() -> SearchEngine:
    """Async on purpose. As a plain `def`, FastAPI ran it in its thread pool, and the
    first concurrent searches each saw `_engine is None` and built their own engine:
    measured 2026-11-23, one worker grew to 1.8 GB with 61 threads instead of ~400 MB."""
    global _engine
    if _engine is None:
        async with _engine_lock:
            if _engine is None:
                _engine = await asyncio.to_thread(build_engine, get_settings(), redis)
    return _engine


async def get_llm_client() -> LLMClient:
    # No await between the check and the assignment, so no race on the event loop.
    global _llm
    if _llm is None:
        settings = get_settings()
        http = httpx.AsyncClient(timeout=settings.llm_timeout_seconds)
        _llm = (build_llm_client(settings, http), http)
    return _llm[0]


async def close_search_resources() -> None:
    global _engine, _llm
    if _engine is not None:
        _engine.close()
        _engine = None
    if _llm is not None:
        await _llm[1].aclose()
        _llm = None


async def rate_limit_search(user: CurrentUser) -> None:
    await enforce_rate_limit(
        "search", str(user.id), get_settings().rate_limit_search_per_minute, 60
    )


Engine = Annotated[SearchEngine, Depends(get_search_engine)]
Llm = Annotated[LLMClient, Depends(get_llm_client)]


@router.post(
    "",
    dependencies=[Depends(rate_limit_search)],
    responses={
        401: {"model": ErrorEnvelope},
        422: {"model": ErrorEnvelope},
        429: {"model": ErrorEnvelope},
    },
)
async def search_jobs(
    body: SearchRequest, user: CurrentUser, session: DbSession, engine: Engine
) -> SearchResponse:
    """Jobs that fit the query and profile, after the dealbreakers, each with its scores
    and a computed explanation; plus the postings the dealbreakers ruled out, and why."""
    return await cached_search(session, engine, body, get_settings(), redis, user.id)


@router.post(
    "/explanation",
    dependencies=[Depends(rate_limit_user)],
    responses={
        401: {"model": ErrorEnvelope},
        404: {"model": ErrorEnvelope},
        429: {"model": ErrorEnvelope},
    },
)
async def explain_match(
    body: ExplanationRequest, user: CurrentUser, session: DbSession, llm: Llm
) -> ExplanationSentence:
    """One AI-written sentence for a match, generated from the computed explanation only.
    Counts against the daily AI quota. If the sentence names a skill that is not in the
    explanation it is withheld (`status: dropped`)."""
    in_pool = await session.scalar(select(Job.id).where(Job.id == body.job_id, base_pool()))
    if in_pool is None:
        raise NotFoundError("Job not found")
    jobs = await load_jobs(session, [body.job_id])
    rules: list[Rule] = list(body.rules)
    results = (await outcomes(session, rules, [body.job_id])).get(body.job_id, []) if rules else []
    explanation, _ = explain(body.profile, jobs[body.job_id].facts, None, flags_for(results))
    remaining = await take_quota(redis, user.id, get_settings().llm_daily_quota_per_user)
    sentence, status, detail = await write_sentence(llm, explanation)
    return ExplanationSentence(
        job_id=body.job_id,
        explanation=explanation,
        sentence=sentence,
        status=status,
        detail=detail,
        quota_remaining=remaining,
    )
