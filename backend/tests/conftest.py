"""Test setup. Tests run against a separate `<database>_test` database and Redis db 15,
so they never touch development data. No test makes a real LLM or network call.

Settings in tests come only from code defaults and the overrides below, never from a
developer's `.env`: `Settings` reads no env file, and `docker compose run api pytest`
copies `.env` values into the container's environment, so every variable that maps to a
`Settings` field is removed here before any settings object exists. Only the two
connection targets survive (they differ between Compose and CI). tests/test_settings_
isolation.py fails if anything else leaks in. (A leaked INGEST_CRON_ENABLED=false once
made a test pass locally and fail in CI.)"""

import os
import socket
import tempfile
from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy.engine import make_url

from app.core.config import Settings

CONNECTION_VARS = frozenset({"DATABASE_URL", "REDIS_URL"})
for _name in Settings.model_fields:
    if _name.upper() not in CONNECTION_VARS:
        os.environ.pop(_name.upper(), None)
        os.environ.pop(_name, None)

_base_url = make_url(
    os.environ.get("DATABASE_URL", "postgresql+psycopg://jobmatch:jobmatch@db:5432/jobmatch")
)
_test_db = _base_url.database or "jobmatch"
if not _test_db.endswith("_test"):
    _test_db += "_test"
_test_url = _base_url.set(database=_test_db)

os.environ["DATABASE_URL"] = _test_url.render_as_string(hide_password=False)
os.environ["REDIS_URL"] = (
    os.environ.get("REDIS_URL", "redis://redis:6379/0").rsplit("/", 1)[0] + "/15"
)
# The only settings tests change from the code defaults (besides the connections).
TEST_OVERRIDES = {
    "ENVIRONMENT": "test",
    "BM25_INDEX_DIR": tempfile.mkdtemp(prefix="bm25-test-"),
    "SEARCH_CACHE_SECONDS": "0",
    "RATE_LIMIT_CREDENTIALS_IP_PER_MINUTE": "1000",
    "CORS_ORIGINS": "http://localhost:3000",
}
os.environ.update(TEST_OVERRIDES)
# Not a Settings field, but read by prometheus_client: tests use the single-process
# metrics registry (the api service sets it for its workers).
os.environ.pop("PROMETHEUS_MULTIPROC_DIR", None)

import httpx  # noqa: E402
import pytest  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from alembic import command  # noqa: E402
from app.core.db import SessionLocal, engine  # noqa: E402
from app.core.redis import redis  # noqa: E402
from app.main import app  # noqa: E402
from tests.helpers import alembic_config  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _database() -> None:
    admin = create_engine(_base_url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        exists = conn.scalar(
            text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": _test_db}
        )
        if not exists:
            conn.execute(text(f'CREATE DATABASE "{_test_db}"'))
    admin.dispose()
    command.upgrade(alembic_config(), "head")


_ALLOWED_HOSTS = {
    host
    for url in (os.environ["DATABASE_URL"], os.environ["REDIS_URL"])
    if (host := make_url(url).host if "://" in url else None)
} | {"localhost", "127.0.0.1", "::1", "test"}


@pytest.fixture(autouse=True)
def _no_internet(monkeypatch: pytest.MonkeyPatch) -> None:
    """No test may reach the internet: a name lookup for anything but the test database,
    Redis or localhost fails at once. (A worker test once fetched the live Himalayas
    API page by page because a new feed adapter was not stubbed.)"""
    real = socket.getaddrinfo

    def guarded(host: Any, *args: Any, **kwargs: Any) -> Any:
        if host is not None and str(host) not in _ALLOWED_HOSTS:
            raise OSError(f"tests may not reach the internet (lookup of {host!r})")
        return real(host, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", guarded)


@pytest.fixture(autouse=True)
async def _clean_state() -> AsyncIterator[None]:
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE users, llm_cache, companies, jobs, ingest_runs CASCADE"))
    await redis.flushdb()
    yield


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        yield http


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as db:
        yield db
