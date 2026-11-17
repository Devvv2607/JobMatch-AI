"""Test setup. Tests run against a separate `<database>_test` database and Redis db 15,
so they never touch development data. No test makes a real LLM or network call."""

import os
from collections.abc import AsyncIterator

from sqlalchemy.engine import make_url

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
os.environ["ENVIRONMENT"] = "test"
os.environ["RATE_LIMIT_AUTH_PER_MINUTE"] = "1000"
os.environ["CORS_ORIGINS"] = "http://localhost:3000"
for _key in ("GROQ_API_KEY", "GEMINI_API_KEY"):
    os.environ[_key] = ""  # a developer's real keys must never reach a test

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


@pytest.fixture(autouse=True)
async def _clean_state() -> AsyncIterator[None]:
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE users, llm_cache CASCADE"))
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
