from pathlib import Path
from typing import Any

import httpx
from alembic.config import Config

BACKEND_DIR = Path(__file__).resolve().parents[1]
CSRF = {"X-Requested-With": "jobmatch"}
PASSWORD = "a-long-password"


def alembic_config() -> Config:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    return config


async def register(
    client: httpx.AsyncClient, email: str, password: str = PASSWORD
) -> dict[str, Any]:
    response = await client.post(
        "/api/v1/auth/register", json={"email": email, "password": password}
    )
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


def bearer(session_body: dict[str, Any]) -> dict[str, str]:
    return {"Authorization": f"Bearer {session_body['access_token']}"}
