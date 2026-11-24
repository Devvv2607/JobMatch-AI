"""POST /api/v1/search and /search/explanation, end to end through the app, with the
stand-in models (tests/search_helpers.py) and a scripted LLM provider."""

import asyncio
import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.search import get_llm_client, get_search_engine
from app.core.config import get_settings
from app.core.llm.client import LLMClient
from app.core.llm.types import Completion, ProviderError
from app.core.redis import redis
from app.main import app
from app.retrieval.bm25 import Bm25Holder, rebuild
from app.retrieval.filters import allowed_ids
from app.retrieval.rules import WorkEligibility
from app.retrieval.service import SearchEngine
from tests.helpers import bearer, register
from tests.search_helpers import BagEmbedder, OverlapReranker, add_company, add_job
from tests.test_llm_client import MemoryCache, StubProvider


@pytest.fixture
def settings_override(monkeypatch: pytest.MonkeyPatch) -> Callable[..., None]:
    def apply(**values: Any) -> None:
        for name, value in values.items():
            monkeypatch.setattr(get_settings(), name, value)

    return apply


@pytest.fixture
async def pool(session: AsyncSession) -> dict[str, uuid.UUID]:
    shop = await add_company(session, "Shop Co")
    jobs = {
        "python": await add_job(
            session,
            shop,
            "Python Backend Engineer",
            "Build Python APIs with FastAPI and PostgreSQL",
            skills=["Python", "FastAPI", "PostgreSQL"],
            seniority="senior",
        ),
        "python_us": await add_job(
            session,
            shop,
            "Python Engineer (US only)",
            "Python services for US customers",
            skills=["Python"],
            eligibility_scope="listed",
            work_countries=["US"],
        ),
        "python_unknown": await add_job(
            session,
            shop,
            "Python Developer",
            "Python scripting",
            skills=["Python"],
            eligibility_scope="unknown",
        ),
        "chef": await add_job(session, shop, "Pastry Chef", "Croissants and laminated dough"),
        "go": await add_job(
            session, shop, "Go Engineer", "Distributed systems in Go", skills=["Go"]
        ),
    }
    await add_job(session, shop, "Python Engineer (expired)", "Python", status="expired")
    await session.commit()
    return {name: job.id for name, job in jobs.items()}


@pytest.fixture
def reranker() -> OverlapReranker:
    return OverlapReranker()


@pytest.fixture
async def engine(
    session: AsyncSession, pool: dict[str, uuid.UUID], tmp_path: Path, reranker: OverlapReranker
) -> AsyncIterator[SearchEngine]:
    await rebuild(session, redis, tmp_path)
    engine = SearchEngine(BagEmbedder(), reranker, Bm25Holder(tmp_path, redis, 0))
    app.dependency_overrides[get_search_engine] = lambda: engine
    yield engine
    app.dependency_overrides.pop(get_search_engine, None)
    engine.close()


@pytest.fixture
async def auth(client: httpx.AsyncClient) -> dict[str, str]:
    return bearer(await register(client, f"{uuid.uuid4().hex[:8]}@example.com"))


def use_llm(*outcomes: Completion | ProviderError, name: str = "groq") -> StubProvider:
    provider = StubProvider(name, list(outcomes))
    client = LLMClient([provider], MemoryCache(), max_retries=0, repair_attempts=0)
    app.dependency_overrides[get_llm_client] = lambda: client
    return provider


@pytest.fixture(autouse=True)
def _clear_llm_override() -> Iterator[None]:
    yield
    app.dependency_overrides.pop(get_llm_client, None)


def sentence(text: str) -> Completion:
    return Completion(text=f'{{"sentence": "{text}"}}', prompt_tokens=10, completion_tokens=10)


async def post_search(
    client: httpx.AsyncClient, auth: dict[str, str], **body: Any
) -> dict[str, Any]:
    response = await client.post("/api/v1/search", json=body, headers=auth)
    assert response.status_code == 200, response.text
    result: dict[str, Any] = response.json()
    return result


async def test_search_needs_sign_in(client: httpx.AsyncClient, engine: SearchEngine) -> None:
    response = await client.post("/api/v1/search", json={"query": "python"})
    assert response.status_code == 401


async def test_search_needs_a_query_or_profile_skills(
    client: httpx.AsyncClient, auth: dict[str, str], engine: SearchEngine
) -> None:
    response = await client.post("/api/v1/search", json={"limit": 5}, headers=auth)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


async def test_search_ranks_relevant_jobs_with_scores_and_explanation(
    client: httpx.AsyncClient,
    auth: dict[str, str],
    engine: SearchEngine,
    pool: dict[str, uuid.UUID],
    reranker: OverlapReranker,
) -> None:
    body = await post_search(
        client,
        auth,
        query="python backend fastapi",
        profile={"skills": ["python", "postgres"], "years_experience": 6},
        limit=3,
    )
    results = body["results"]
    assert [r["rank"] for r in results] == [1, 2, 3]
    top = results[0]
    assert top["job"]["id"] == str(pool["python"])
    assert top["job"]["company"] == "Shop Co"
    assert top["explanation"]["skills"] == {
        "matched": ["Python", "PostgreSQL"],
        "missing": ["FastAPI"],
        "coverage": pytest.approx(2 / 3),
    }
    assert top["explanation"]["experience"]["fit"] == "within"
    assert top["scores"]["ranks"]["bm25"] == 1
    assert top["scores"]["ranks"]["vector"] == 1
    finals = [r["scores"]["final"] for r in results]
    assert finals == sorted(finals, reverse=True)
    assert str(pool["chef"]) not in {r["job"]["id"] for r in results}
    assert body["degraded"] == [] and body["bm25_version"]
    assert body["ruled_out"] == []
    assert body["pool"]["pool"] == 5 and body["pool"]["allowed"] == 5
    assert {"filter", "bm25", "vector", "fuse", "rerank", "rescore", "total"} <= set(
        body["timings_ms"]
    )
    # The interactive profile: only the fused top M reach the cross-encoder.
    settings = get_settings()
    assert body["rerank_profile"] == "interactive"
    assert reranker.calls[-1][1] == body["reranked"] <= settings.rerank_interactive_top
    assert reranker.max_tokens[-1] == settings.rerank_interactive_tokens


async def test_dealbreakers_filter_results_and_label_what_they_ruled_out(
    client: httpx.AsyncClient,
    auth: dict[str, str],
    engine: SearchEngine,
    session: AsyncSession,
    pool: dict[str, uuid.UUID],
) -> None:
    rules = [{"kind": "work_eligibility", "country": "IN"}]
    body = await post_search(client, auth, query="python engineer", rules=rules, limit=10)
    result_ids = {r["job"]["id"] for r in body["results"]}
    allowed = {str(i) for i in await allowed_ids(session, [WorkEligibility(country="IN")])}
    assert result_ids <= allowed
    assert str(pool["python_us"]) not in result_ids

    ruled_out = {r["job"]["id"]: r["rules"] for r in body["ruled_out"]}
    assert ruled_out == {
        str(pool["python_us"]): [
            {
                "kind": "work_eligibility",
                "rule": "Open to candidates in IN",
                "outcome": "violates",
                "reason": None,
            }
        ]
    }
    assert not set(ruled_out) & allowed

    flagged = next(r for r in body["results"] if r["job"]["id"] == str(pool["python_unknown"]))
    assert flagged["explanation"]["flags"] == [
        {
            "kind": "work_eligibility",
            "rule": "Open to candidates in IN",
            "reason": "The posting does not say where the job can be done from",
        }
    ]
    assert body["pool"]["allowed"] == 4
    assert body["pool"]["ruled_out_by_rule"] == {"work_eligibility": 1}
    assert body["pool"]["eligibility"] == {"eligible": 3, "unknown": 1, "ineligible": 1}


async def test_strict_rule_rules_out_unknowns_with_the_reason(
    client: httpx.AsyncClient,
    auth: dict[str, str],
    engine: SearchEngine,
    pool: dict[str, uuid.UUID],
) -> None:
    rules = [{"kind": "work_eligibility", "country": "IN", "strict": True}]
    body = await post_search(client, auth, query="python", rules=rules)
    ruled_out = {r["job"]["id"]: r["rules"][0] for r in body["ruled_out"]}
    assert ruled_out[str(pool["python_unknown"])]["outcome"] == "unknown"
    assert ruled_out[str(pool["python_unknown"])]["reason"]
    assert ruled_out[str(pool["python_us"])]["outcome"] == "violates"


async def test_profile_only_search_uses_the_profile_skills(
    client: httpx.AsyncClient,
    auth: dict[str, str],
    engine: SearchEngine,
    pool: dict[str, uuid.UUID],
) -> None:
    body = await post_search(client, auth, profile={"skills": ["golang"]}, limit=1)
    assert body["query"] == "Go"
    assert body["results"][0]["job"]["id"] == str(pool["go"])


async def test_without_a_bm25_index_search_degrades_to_vector_only(
    client: httpx.AsyncClient,
    auth: dict[str, str],
    engine: SearchEngine,
    pool: dict[str, uuid.UUID],
) -> None:
    await redis.delete("bm25:version")
    engine.bm25 = Bm25Holder(Path("/nonexistent"), redis, 0)
    body = await post_search(client, auth, query="pastry croissants", limit=1)
    assert body["degraded"] == ["bm25_unavailable"]
    assert body["bm25_version"] is None
    assert body["results"][0]["job"]["id"] == str(pool["chef"])
    assert body["results"][0]["scores"]["ranks"]["bm25"] is None


async def test_responses_are_cached_per_user(
    client: httpx.AsyncClient,
    auth: dict[str, str],
    engine: SearchEngine,
    reranker: OverlapReranker,
    settings_override: Callable[..., None],
) -> None:
    settings_override(search_cache_seconds=60)
    first = await post_search(client, auth, query="python")
    second = await post_search(client, auth, query="python")
    assert (first["cached"], second["cached"]) == (False, True)
    assert second["results"] == first["results"]
    assert len(reranker.calls) == 1
    other = bearer(await register(client, "other@example.com"))
    assert (await post_search(client, other, query="python"))["cached"] is False


async def test_search_is_rate_limited_per_user(
    client: httpx.AsyncClient,
    auth: dict[str, str],
    engine: SearchEngine,
    settings_override: Callable[..., None],
) -> None:
    settings_override(rate_limit_search_per_minute=2)
    for _ in range(2):
        await post_search(client, auth, query="python")
    response = await client.post("/api/v1/search", json={"query": "python"}, headers=auth)
    assert response.status_code == 429
    assert "Retry-After" in response.headers


async def test_explanation_sentence_is_generated_from_the_explanation_only(
    client: httpx.AsyncClient,
    auth: dict[str, str],
    session: AsyncSession,
    pool: dict[str, uuid.UUID],
) -> None:
    provider = use_llm(sentence("You know Python and PostgreSQL; FastAPI is the gap."))
    response = await client.post(
        "/api/v1/search/explanation",
        json={"job_id": str(pool["python"]), "profile": {"skills": ["Python", "Postgres"]}},
        headers=auth,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "ok"
    assert body["sentence"] == "You know Python and PostgreSQL; FastAPI is the gap."
    assert body["explanation"]["skills"]["missing"] == ["FastAPI"]
    assert body["quota_remaining"] == get_settings().llm_daily_quota_per_user - 1
    user_turn = provider.calls[0]["messages"][1]["content"]  # type: ignore[index]
    assert user_turn.startswith("<match>") and "Croissants" not in user_turn
    assert "Build Python APIs" not in user_turn  # never the description text


async def test_a_sentence_naming_a_skill_outside_the_explanation_is_dropped(
    client: httpx.AsyncClient, auth: dict[str, str], pool: dict[str, uuid.UUID]
) -> None:
    use_llm(sentence("Your Kubernetes and Python experience make this a strong fit."))
    response = await client.post(
        "/api/v1/search/explanation",
        json={"job_id": str(pool["python"]), "profile": {"skills": ["Python"]}},
        headers=auth,
    )
    body = response.json()
    assert (body["status"], body["sentence"]) == ("dropped", None)
    assert "Kubernetes" in body["detail"]
    assert body["explanation"]["skills"]["matched"] == ["Python"]


async def test_personal_data_never_goes_to_a_provider_not_allowed_for_it(
    client: httpx.AsyncClient, auth: dict[str, str], pool: dict[str, uuid.UUID]
) -> None:
    provider = use_llm(sentence("unused"), name="gemini")
    response = await client.post(
        "/api/v1/search/explanation", json={"job_id": str(pool["python"])}, headers=auth
    )
    assert response.json()["status"] == "unavailable"
    assert provider.calls == []


async def test_provider_failure_returns_the_computed_explanation_without_a_sentence(
    client: httpx.AsyncClient, auth: dict[str, str], pool: dict[str, uuid.UUID]
) -> None:
    use_llm(ProviderError("bad request", retryable=False))
    response = await client.post(
        "/api/v1/search/explanation", json={"job_id": str(pool["python"])}, headers=auth
    )
    body = response.json()
    assert response.status_code == 200
    assert (body["status"], body["sentence"]) == ("unavailable", None)
    assert body["explanation"]["skills"]["missing"] == ["Python", "FastAPI", "PostgreSQL"]


async def test_daily_quota_limits_explanation_sentences(
    client: httpx.AsyncClient,
    auth: dict[str, str],
    pool: dict[str, uuid.UUID],
    settings_override: Callable[..., None],
) -> None:
    settings_override(llm_daily_quota_per_user=1)
    use_llm(sentence("You know Python."), sentence("You know Python."))
    body = {"job_id": str(pool["python"]), "profile": {"skills": ["Python"]}}
    first = await client.post("/api/v1/search/explanation", json=body, headers=auth)
    assert first.json()["quota_remaining"] == 0
    second = await client.post("/api/v1/search/explanation", json=body, headers=auth)
    assert second.status_code == 429
    assert second.json()["error"]["code"] == "quota_exceeded"


async def test_explaining_a_job_outside_the_pool_is_not_found(
    client: httpx.AsyncClient, auth: dict[str, str], pool: dict[str, uuid.UUID]
) -> None:
    use_llm()
    for job_id in (uuid.uuid4(),):
        response = await client.post(
            "/api/v1/search/explanation", json={"job_id": str(job_id)}, headers=auth
        )
        assert response.status_code == 404


async def test_results_beyond_the_reranked_head_follow_in_fused_order(
    client: httpx.AsyncClient,
    auth: dict[str, str],
    engine: SearchEngine,
    reranker: OverlapReranker,
    settings_override: Callable[..., None],
) -> None:
    settings_override(rerank_interactive_top=2)
    body = await post_search(client, auth, query="engineer python go pastry", limit=5)
    assert body["reranked"] == 2 and reranker.calls[-1][1] == 2
    results = body["results"]
    assert [r["scores"]["rerank_logit"] is None for r in results] == [False, False] + [True] * (
        len(results) - 2
    )
    tail = [r["scores"]["ranks"]["fused"] for r in results[2:]]
    assert tail == sorted(tail) and min(tail) > 2


async def test_top_zero_means_no_rerank(
    client: httpx.AsyncClient,
    auth: dict[str, str],
    engine: SearchEngine,
    reranker: OverlapReranker,
    settings_override: Callable[..., None],
) -> None:
    settings_override(rerank_interactive_top=0)
    body = await post_search(client, auth, query="python", limit=3)
    assert body["reranked"] == 0 and reranker.calls == []
    assert all(r["scores"]["components"]["rerank"] is None for r in body["results"])


async def test_allowed_ids_and_counts_are_cached_per_rules_and_index_version(
    client: httpx.AsyncClient,
    auth: dict[str, str],
    engine: SearchEngine,
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from app.retrieval.filters import allowed_ids as real

    calls: list[int] = []

    async def counted(*args: Any) -> Any:
        calls.append(1)
        return await real(*args)

    monkeypatch.setattr("app.retrieval.service.allowed_ids", counted)
    rules = [{"kind": "work_eligibility", "country": "IN"}]
    first = await post_search(client, auth, query="python", rules=rules)
    await post_search(client, auth, query="go engineer", rules=rules)  # other query, same rules
    assert len(calls) == 1
    await post_search(client, auth, query="python")  # other rules
    assert len(calls) == 2

    await rebuild(session, redis, tmp_path)  # an ingest publishes a new version
    second = await post_search(client, auth, query="python", rules=rules)
    assert len(calls) == 3
    assert second["bm25_version"] != first["bm25_version"]
    assert second["pool"] == first["pool"]


async def test_concurrent_first_searches_build_one_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression: as a sync dependency it ran in a thread pool and raced, building one
    engine (two ONNX models) per concurrent first request."""
    import time

    import app.api.search as search_api

    built: list[int] = []

    def slow_build(*args: Any) -> SearchEngine:
        built.append(1)
        time.sleep(0.2)  # long enough for every caller to arrive while building
        return SearchEngine(BagEmbedder(), OverlapReranker(), None)

    monkeypatch.setattr(search_api, "build_engine", slow_build)
    monkeypatch.setattr(search_api, "_engine", None)
    engines = await asyncio.gather(*(search_api.get_search_engine() for _ in range(8)))
    assert len(built) == 1
    assert all(e is engines[0] for e in engines)
    engines[0].close()
    monkeypatch.setattr(search_api, "_engine", None)


def test_perspective_check_against_the_fixture() -> None:
    import json

    from app.retrieval.sentence import wrong_perspective

    fixture = json.loads(
        (Path(__file__).parent / "fixtures/sentences/perspective.json").read_text(encoding="utf-8")
    )
    assert [s for s in fixture["ok"] if wrong_perspective(s)] == []
    assert [s for s in fixture["wrong"] if not wrong_perspective(s)] == []


async def test_a_sentence_saying_the_job_lacks_a_skill_is_dropped(
    client: httpx.AsyncClient, auth: dict[str, str], pool: dict[str, uuid.UUID]
) -> None:
    provider = use_llm(sentence("You know Python, but it lacks FastAPI and PostgreSQL."))
    response = await client.post(
        "/api/v1/search/explanation",
        json={"job_id": str(pool["python"]), "profile": {"skills": ["Python"]}},
        headers=auth,
    )
    body = response.json()
    assert (body["status"], body["sentence"]) == ("dropped", None)
    assert "not you" in body["detail"]
    system = provider.calls[0]["messages"][0]["content"]  # type: ignore[index]
    assert "you don't have Kubernetes yet" in system  # prompt v2
