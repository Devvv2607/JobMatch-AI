import json
import logging
import sys
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from fastapi import FastAPI
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import health
from app.auth.service import purge_expired_refresh_tokens
from app.core.config import DEV_JWT_SECRET, Settings
from app.core.db import engine
from app.core.errors import install_error_handlers
from app.core.logging import JsonFormatter, request_id_var
from app.core.middleware import RequestContextMiddleware
from app.models import Base, RefreshToken
from app.worker import WorkerSettings, purge_refresh_tokens
from tests.helpers import register


async def test_healthz_is_up_without_touching_dependencies(client: httpx.AsyncClient) -> None:
    response = await client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_readyz_checks_postgres_and_redis(client: httpx.AsyncClient) -> None:
    response = await client.get("/readyz")
    assert response.status_code == 200
    assert response.json() == {"status": "ready", "checks": {"database": True, "redis": True}}


async def test_readyz_is_503_when_a_dependency_is_down(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def down() -> bool:
        return False

    monkeypatch.setattr(health, "_redis_ok", down)
    response = await client.get("/readyz")
    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "checks": {"database": True, "redis": False},
    }


async def test_metrics_exposes_request_counts_and_durations_by_route(
    client: httpx.AsyncClient,
) -> None:
    await client.get(f"/api/v1/tasks/{uuid.uuid4()}")  # 401, but still observed

    response = await client.get("/metrics")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    # Labelled by route template, not by raw path, so cardinality stays bounded.
    assert (
        'http_requests_total{method="GET",route="/api/v1/tasks/{task_id}",status="401"}'
        in response.text
    )
    assert "http_request_duration_seconds_bucket" in response.text


async def test_every_response_carries_a_request_id_and_security_headers(
    client: httpx.AsyncClient,
) -> None:
    generated = await client.get("/healthz")
    assert len(generated.headers["x-request-id"]) == 32

    echoed = await client.get("/healthz", headers={"X-Request-ID": "trace-abc-12345"})
    assert echoed.headers["x-request-id"] == "trace-abc-12345"

    # Anything that is not a plain token is replaced, so ids cannot inject into logs.
    hostile = await client.get("/healthz", headers={"X-Request-ID": 'x"}\n{"level":"fake'})
    assert hostile.headers["x-request-id"] != 'x"}\n{"level":"fake'
    assert len(hostile.headers["x-request-id"]) == 32

    assert generated.headers["x-content-type-options"] == "nosniff"
    assert generated.headers["x-frame-options"] == "DENY"
    assert generated.headers["referrer-policy"] == "no-referrer"
    assert "default-src 'none'" in generated.headers["content-security-policy"]
    assert generated.headers["cache-control"] == "no-store"
    assert "server-timing" in generated.headers


async def test_errors_use_one_envelope_with_the_request_id(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/nope", headers={"X-Request-ID": "trace-404-xyz"})
    assert response.status_code == 404
    assert response.json() == {
        "error": {
            "code": "not_found",
            "message": "Not Found",
            "details": [],
            "request_id": "trace-404-xyz",
        }
    }


async def test_unhandled_exceptions_become_a_500_envelope_without_internals() -> None:
    app = FastAPI()
    install_error_handlers(app)
    app.add_middleware(RequestContextMiddleware, hsts=False)

    @app.get("/boom")
    async def boom() -> None:
        raise RuntimeError("database password is hunter2")

    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        response = await http.get("/boom", headers={"X-Request-ID": "trace-500-xyz"})

    assert response.status_code == 500
    error = response.json()["error"]
    assert error["code"] == "internal_error"
    assert error["request_id"] == "trace-500-xyz"
    assert "hunter2" not in response.text


async def test_cors_allows_only_configured_origins(client: httpx.AsyncClient) -> None:
    preflight = {"Access-Control-Request-Method": "POST"}
    allowed = await client.options(
        "/api/v1/auth/login", headers={**preflight, "Origin": "http://localhost:3000"}
    )
    assert allowed.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert allowed.headers["access-control-allow-credentials"] == "true"

    denied = await client.options(
        "/api/v1/auth/login", headers={**preflight, "Origin": "https://evil.example"}
    )
    assert "access-control-allow-origin" not in denied.headers


async def test_requests_are_logged_as_json_with_the_request_id(
    client: httpx.AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger="app.request"):
        await client.get("/api/v1/auth/me", headers={"X-Request-ID": "trace-log-12345"})

    (record,) = [r for r in caplog.records if r.name == "app.request"]
    line = json.loads(JsonFormatter().format(record))

    assert line["msg"] == "request"
    assert line["level"] == "INFO"
    assert line["request_id"] == "trace-log-12345"
    assert line["method"] == "GET"
    assert line["route"] == "/api/v1/auth/me"
    assert line["status"] == 401
    assert isinstance(line["duration_ms"], float)
    assert datetime.fromisoformat(line["ts"]).tzinfo is not None


def test_json_formatter_includes_exceptions_and_survives_odd_values() -> None:
    request_id_var.set("trace-fmt-12345")
    try:
        raise ValueError("bad thing")
    except ValueError:
        record = logging.getLogger("t").makeRecord(
            "t",
            logging.ERROR,
            __file__,
            1,
            "failed %s",
            ("here",),
            exc_info=sys.exc_info(),
            extra={"when": datetime(2026, 1, 1, tzinfo=UTC), "user_id": uuid.UUID(int=1)},
        )

    line = json.loads(JsonFormatter().format(record))
    assert line["msg"] == "failed here"
    assert line["request_id"] == "trace-fmt-12345"
    assert "ValueError: bad thing" in line["exc"]
    assert line["user_id"] == "00000000-0000-0000-0000-000000000001"


def test_production_refuses_the_development_secret_and_insecure_cookies() -> None:
    with pytest.raises(ValidationError, match="JWT_SECRET"):
        Settings(environment="production", jwt_secret=DEV_JWT_SECRET, cookie_secure=True)
    with pytest.raises(ValidationError, match="JWT_SECRET"):
        Settings(environment="production", jwt_secret="too-short", cookie_secure=True)
    with pytest.raises(ValidationError, match="COOKIE_SECURE"):
        Settings(environment="production", jwt_secret="x" * 48, cookie_secure=False)
    Settings(environment="production", jwt_secret="x" * 48, cookie_secure=True)


async def test_migrations_and_models_describe_the_same_schema() -> None:
    def diff(sync_conn):  # type: ignore[no-untyped-def]
        return compare_metadata(MigrationContext.configure(sync_conn), Base.metadata)

    async with engine.connect() as conn:
        differences = await conn.run_sync(diff)
    assert differences == []


async def test_purge_removes_only_expired_refresh_tokens(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    await register(client, "a@example.com")
    await register(client, "b@example.com")
    tokens = (await session.scalars(select(RefreshToken).order_by(RefreshToken.created_at))).all()
    tokens[0].expires_at = datetime.now(UTC) - timedelta(days=1)
    await session.commit()

    assert await purge_expired_refresh_tokens(session) == 1
    await session.commit()

    remaining = (await session.scalars(select(RefreshToken.id))).all()
    assert remaining == [tokens[1].id]


async def test_worker_purge_job_is_registered_and_idempotent(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    await register(client, "a@example.com")
    (token,) = (await session.scalars(select(RefreshToken))).all()
    token.expires_at = datetime.now(UTC) - timedelta(days=1)
    await session.commit()

    assert [job.name for job in WorkerSettings.cron_jobs] == ["cron:purge_refresh_tokens"]
    assert await purge_refresh_tokens({}) == 1
    assert await purge_refresh_tokens({}) == 0
