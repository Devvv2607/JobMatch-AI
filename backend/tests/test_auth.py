from datetime import UTC, datetime, timedelta

import httpx
import jwt
import pytest
from redis.exceptions import RedisError
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import REFRESH_COOKIE
from app.core import ratelimit
from app.core.config import get_settings
from app.core.errors import RateLimitedError
from app.core.redis import redis
from app.models import RefreshToken, User
from tests.helpers import CSRF, PASSWORD, bearer, register

AUTH = "/api/v1/auth"


async def test_register_starts_a_session(client: httpx.AsyncClient) -> None:
    response = await client.post(
        f"{AUTH}/register", json={"email": "Asha@Example.com", "password": PASSWORD}
    )

    assert response.status_code == 201
    body = response.json()
    assert body["user"]["email"] == "asha@example.com"
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == get_settings().access_token_ttl_seconds
    assert set(body) == {"access_token", "token_type", "expires_in", "user"}
    assert client.cookies[REFRESH_COOKIE] not in response.text

    set_cookie = response.headers["set-cookie"]
    assert set_cookie.startswith(f"{REFRESH_COOKIE}=")
    assert "HttpOnly" in set_cookie
    assert "SameSite=lax" in set_cookie
    assert "Path=/api/v1/auth" in set_cookie

    me = await client.get(f"{AUTH}/me", headers=bearer(body))
    assert me.status_code == 200
    assert me.json()["email"] == "asha@example.com"


async def test_password_is_stored_as_argon2id(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    await register(client, "asha@example.com")
    user = await session.scalar(select(User))
    assert user is not None
    assert user.password_hash.startswith("$argon2id$")
    assert PASSWORD not in user.password_hash


async def test_duplicate_email_is_a_conflict(client: httpx.AsyncClient) -> None:
    await register(client, "asha@example.com")
    response = await client.post(
        f"{AUTH}/register", json={"email": "ASHA@example.com", "password": PASSWORD}
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"


async def test_short_password_is_rejected_without_echoing_it(client: httpx.AsyncClient) -> None:
    response = await client.post(
        f"{AUTH}/register", json={"email": "asha@example.com", "password": "short-pw"}
    )
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert error["details"][0]["field"] == "body.password"
    assert "short-pw" not in response.text


async def test_login_succeeds_and_wrong_credentials_look_identical(
    client: httpx.AsyncClient,
) -> None:
    await register(client, "asha@example.com")

    ok = await client.post(
        f"{AUTH}/login", json={"email": "asha@example.com", "password": PASSWORD}
    )
    assert ok.status_code == 200
    assert ok.json()["access_token"]

    wrong_password = await client.post(
        f"{AUTH}/login", json={"email": "asha@example.com", "password": "not-the-password"}
    )
    unknown_email = await client.post(
        f"{AUTH}/login", json={"email": "nobody@example.com", "password": PASSWORD}
    )
    assert wrong_password.status_code == unknown_email.status_code == 401
    assert wrong_password.json()["error"]["message"] == unknown_email.json()["error"]["message"]


async def test_refresh_rotates_the_token(client: httpx.AsyncClient) -> None:
    await register(client, "asha@example.com")
    first = client.cookies[REFRESH_COOKIE]

    response = await client.post(f"{AUTH}/refresh", headers=CSRF)

    assert response.status_code == 200
    second = client.cookies[REFRESH_COOKIE]
    assert second != first
    me = await client.get(f"{AUTH}/me", headers=bearer(response.json()))
    assert me.status_code == 200


async def test_reusing_a_rotated_refresh_token_revokes_the_whole_family(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    await register(client, "asha@example.com")
    stolen = client.cookies[REFRESH_COOKIE]

    # The legitimate client rotates twice; `stolen` is now two generations old.
    assert (await client.post(f"{AUTH}/refresh", headers=CSRF)).status_code == 200
    assert (await client.post(f"{AUTH}/refresh", headers=CSRF)).status_code == 200
    current = client.cookies[REFRESH_COOKIE]

    # An attacker replays the old token.
    client.cookies.clear()
    replay = await client.post(
        f"{AUTH}/refresh", headers={**CSRF, "Cookie": f"{REFRESH_COOKIE}={stolen}"}
    )
    assert replay.status_code == 401

    # Every token from that login is now revoked, including the newest one.
    rows = (await session.scalars(select(RefreshToken))).all()
    assert len(rows) == 3
    assert len({row.family_id for row in rows}) == 1
    assert all(row.revoked_at is not None for row in rows)

    legitimate = await client.post(
        f"{AUTH}/refresh", headers={**CSRF, "Cookie": f"{REFRESH_COOKIE}={current}"}
    )
    assert legitimate.status_code == 401


async def test_reuse_does_not_revoke_the_users_other_logins(client: httpx.AsyncClient) -> None:
    await register(client, "asha@example.com")
    laptop_old = client.cookies[REFRESH_COOKIE]
    assert (await client.post(f"{AUTH}/refresh", headers=CSRF)).status_code == 200

    client.cookies.clear()
    login = await client.post(
        f"{AUTH}/login", json={"email": "asha@example.com", "password": PASSWORD}
    )
    assert login.status_code == 200
    phone = client.cookies[REFRESH_COOKIE]

    client.cookies.clear()
    replay = await client.post(
        f"{AUTH}/refresh", headers={**CSRF, "Cookie": f"{REFRESH_COOKIE}={laptop_old}"}
    )
    assert replay.status_code == 401

    still_valid = await client.post(
        f"{AUTH}/refresh", headers={**CSRF, "Cookie": f"{REFRESH_COOKIE}={phone}"}
    )
    assert still_valid.status_code == 200


async def test_refresh_requires_the_csrf_header_and_an_allowed_origin(
    client: httpx.AsyncClient,
) -> None:
    await register(client, "asha@example.com")

    no_header = await client.post(f"{AUTH}/refresh")
    assert no_header.status_code == 403

    bad_origin = await client.post(
        f"{AUTH}/refresh", headers={**CSRF, "Origin": "https://evil.example"}
    )
    assert bad_origin.status_code == 403

    good_origin = await client.post(
        f"{AUTH}/refresh", headers={**CSRF, "Origin": "http://localhost:3000"}
    )
    assert good_origin.status_code == 200


async def test_refresh_without_a_cookie_is_unauthorized(client: httpx.AsyncClient) -> None:
    response = await client.post(f"{AUTH}/refresh", headers=CSRF)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


async def test_expired_refresh_token_is_rejected(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    await register(client, "asha@example.com")
    await session.execute(
        update(RefreshToken).values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
    )
    await session.commit()

    response = await client.post(f"{AUTH}/refresh", headers=CSRF)
    assert response.status_code == 401


async def test_logout_ends_the_session(client: httpx.AsyncClient) -> None:
    await register(client, "asha@example.com")
    token = client.cookies[REFRESH_COOKIE]

    response = await client.post(f"{AUTH}/logout", headers=CSRF)
    assert response.status_code == 204
    assert REFRESH_COOKIE not in client.cookies

    replay = await client.post(
        f"{AUTH}/refresh", headers={**CSRF, "Cookie": f"{REFRESH_COOKIE}={token}"}
    )
    assert replay.status_code == 401


async def test_logout_requires_the_csrf_header(client: httpx.AsyncClient) -> None:
    await register(client, "asha@example.com")
    assert (await client.post(f"{AUTH}/logout")).status_code == 403


async def test_me_rejects_missing_malformed_and_expired_tokens(client: httpx.AsyncClient) -> None:
    body = await register(client, "asha@example.com")

    assert (await client.get(f"{AUTH}/me")).status_code == 401
    garbage = await client.get(f"{AUTH}/me", headers={"Authorization": "Bearer not-a-jwt"})
    assert garbage.status_code == 401

    expired = jwt.encode(
        {
            "sub": body["user"]["id"],
            "typ": "access",
            "iat": datetime.now(UTC) - timedelta(hours=2),
            "exp": datetime.now(UTC) - timedelta(hours=1),
        },
        get_settings().jwt_secret,
        algorithm="HS256",
    )
    response = await client.get(f"{AUTH}/me", headers={"Authorization": f"Bearer {expired}"})
    assert response.status_code == 401

    forged = jwt.encode(
        {
            "sub": body["user"]["id"],
            "typ": "access",
            "iat": datetime.now(UTC),
            "exp": datetime.now(UTC) + timedelta(hours=1),
        },
        "a-different-secret-that-is-long-enough-000",
        algorithm="HS256",
    )
    response = await client.get(f"{AUTH}/me", headers={"Authorization": f"Bearer {forged}"})
    assert response.status_code == 401


async def test_rate_limit_blocks_after_the_limit_and_says_when_to_retry() -> None:
    for _ in range(3):
        await ratelimit.enforce_rate_limit("test", "1.2.3.4", limit=3, window_seconds=60)

    with pytest.raises(RateLimitedError) as excinfo:
        await ratelimit.enforce_rate_limit("test", "1.2.3.4", limit=3, window_seconds=60)
    assert excinfo.value.headers is not None
    assert 1 <= int(excinfo.value.headers["Retry-After"]) <= 60

    # A different client is unaffected.
    await ratelimit.enforce_rate_limit("test", "5.6.7.8", limit=3, window_seconds=60)


async def test_rate_limiter_fails_open_when_redis_is_down(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def broken_pipeline(**_: object) -> None:
        raise RedisError("connection refused")

    monkeypatch.setattr(redis, "pipeline", broken_pipeline)
    await ratelimit.enforce_rate_limit("test", "1.2.3.4", limit=0, window_seconds=60)
