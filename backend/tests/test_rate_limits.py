"""Rate limits on the auth endpoints.

- login and register: per IP (every request) and per email (failures only)
- refresh: per token family, never per IP
- logout: not limited
"""

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

import httpx
import pytest
from starlette.requests import Request

from app.api.auth import REFRESH_COOKIE
from app.api.deps import client_ip
from app.core.config import get_settings
from app.main import app
from tests.helpers import CSRF, PASSWORD, register

AUTH = "/api/v1/auth"
WRONG = "not-the-right-password"


@asynccontextmanager
async def from_ip(ip: str) -> AsyncIterator[httpx.AsyncClient]:
    """A client whose socket address is `ip`."""
    transport = httpx.ASGITransport(app=app, client=(ip, 40000))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        yield http


async def login(http: httpx.AsyncClient, email: str, password: str) -> httpx.Response:
    return await http.post(f"{AUTH}/login", json={"email": email, "password": password})


@pytest.fixture
def settings_override(monkeypatch: pytest.MonkeyPatch) -> Callable[..., None]:
    def apply(**values: int) -> None:
        for name, value in values.items():
            monkeypatch.setattr(get_settings(), name, value)

    return apply


# --- per IP --------------------------------------------------------------------------


async def test_credentials_are_limited_per_ip_with_retry_after(
    settings_override: Callable[..., None],
) -> None:
    settings_override(rate_limit_credentials_ip_per_minute=3)

    async with from_ip("10.0.0.1") as http:
        # Different emails each time, so only the IP limit can trigger.
        statuses = [(await login(http, f"u{i}@example.com", WRONG)).status_code for i in range(3)]
        blocked = await login(http, "u9@example.com", WRONG)
        blocked_register = await http.post(
            f"{AUTH}/register", json={"email": "new@example.com", "password": PASSWORD}
        )
    async with from_ip("10.0.0.2") as other:
        unaffected = await login(other, "u1@example.com", WRONG)

    assert statuses == [401, 401, 401]
    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "rate_limited"
    assert 1 <= int(blocked.headers["retry-after"]) <= 60
    assert blocked_register.status_code == 429  # login and register share the IP bucket
    assert unaffected.status_code == 401


# --- refresh: per token family, not per IP -------------------------------------------


async def test_ten_refreshes_in_a_minute_are_not_rate_limited(
    settings_override: Callable[..., None],
) -> None:
    # Production defaults: 10/min per IP for credentials, 30/min per family for refresh.
    settings_override(rate_limit_credentials_ip_per_minute=10)

    async with from_ip("10.0.0.1") as http:
        await register(http, "asha@example.com")
        statuses = [
            (await http.post(f"{AUTH}/refresh", headers=CSRF)).status_code for _ in range(10)
        ]
        # Refreshes did not use up the IP's credential allowance either.
        later_login = await login(http, "asha@example.com", PASSWORD)

    assert statuses == [200] * 10
    assert later_login.status_code == 200


async def test_refresh_is_limited_per_token_family(
    settings_override: Callable[..., None],
) -> None:
    settings_override(rate_limit_refresh_per_family_per_minute=3)

    async with from_ip("10.0.0.1") as laptop:
        await register(laptop, "asha@example.com")
        statuses = [
            (await laptop.post(f"{AUTH}/refresh", headers=CSRF)).status_code for _ in range(4)
        ]
    # A second login is a second family, from the same IP, with its own allowance.
    async with from_ip("10.0.0.1") as phone:
        assert (await login(phone, "asha@example.com", PASSWORD)).status_code == 200
        phone_refresh = await phone.post(f"{AUTH}/refresh", headers=CSRF)

    assert statuses == [200, 200, 200, 429]
    assert phone_refresh.status_code == 200


async def test_a_rate_limited_refresh_does_not_rotate_or_revoke(
    settings_override: Callable[..., None],
) -> None:
    settings_override(rate_limit_refresh_per_family_per_minute=1)

    async with from_ip("10.0.0.1") as http:
        await register(http, "asha@example.com")
        assert (await http.post(f"{AUTH}/refresh", headers=CSRF)).status_code == 200
        current = http.cookies[REFRESH_COOKIE]
        assert (await http.post(f"{AUTH}/refresh", headers=CSRF)).status_code == 429
        # The cookie was not consumed, so it works once the window allows it again.
        assert http.cookies[REFRESH_COOKIE] == current

    settings_override(rate_limit_refresh_per_family_per_minute=30)
    async with from_ip("10.0.0.1") as http:
        retry = await http.post(
            f"{AUTH}/refresh", headers={**CSRF, "Cookie": f"{REFRESH_COOKIE}={current}"}
        )
    assert retry.status_code == 200


# --- per email: failures only, across IPs --------------------------------------------


async def test_email_lockout_applies_across_different_ips() -> None:
    async with from_ip("10.0.0.100") as http:
        await register(http, "asha@example.com")

    for i in range(5):
        async with from_ip(f"10.0.1.{i}") as http:
            assert (await login(http, "Asha@Example.com", WRONG)).status_code == 401

    # A sixth IP, with the correct password, is still locked out of this email.
    async with from_ip("10.0.2.1") as http:
        locked = await login(http, "asha@example.com", PASSWORD)
        other_email = await login(http, "someone-else@example.com", WRONG)

    assert locked.status_code == 429
    assert 1 <= int(locked.headers["retry-after"]) <= 900
    assert other_email.status_code == 401  # the lockout is per email, not per IP


async def test_successful_logins_do_not_count_toward_the_email_limit() -> None:
    async with from_ip("10.0.0.1") as http:
        await register(http, "asha@example.com")
        for _ in range(4):
            assert (await login(http, "asha@example.com", WRONG)).status_code == 401
        for _ in range(5):
            assert (await login(http, "asha@example.com", PASSWORD)).status_code == 200

        fifth_failure = await login(http, "asha@example.com", WRONG)
        after_lockout = await login(http, "asha@example.com", PASSWORD)

    assert fifth_failure.status_code == 401
    assert after_lockout.status_code == 429


async def test_lockout_does_not_reveal_whether_the_email_exists() -> None:
    async with from_ip("10.0.0.1") as http:
        await register(http, "asha@example.com")
        for email in ("asha@example.com", "nobody@example.com"):
            for _ in range(5):
                await login(http, email, WRONG)

        existing = await login(http, "asha@example.com", WRONG)
        unknown = await login(http, "nobody@example.com", WRONG)

    assert existing.status_code == unknown.status_code == 429
    existing_error, unknown_error = existing.json()["error"], unknown.json()["error"]
    for error in (existing_error, unknown_error):
        error.pop("request_id")
    assert existing_error == unknown_error
    assert "retry-after" in existing.headers and "retry-after" in unknown.headers


async def test_duplicate_registrations_count_as_failures() -> None:
    async with from_ip("10.0.0.1") as http:
        await register(http, "asha@example.com")
        body = {"email": "asha@example.com", "password": PASSWORD}
        statuses = [(await http.post(f"{AUTH}/register", json=body)).status_code for _ in range(6)]
    assert statuses == [409] * 5 + [429]


# --- logout: not limited -------------------------------------------------------------


async def test_logout_is_not_rate_limited(settings_override: Callable[..., None]) -> None:
    settings_override(
        rate_limit_credentials_ip_per_minute=1, rate_limit_refresh_per_family_per_minute=1
    )
    async with from_ip("10.0.0.1") as http:
        await register(http, "asha@example.com")
        statuses = [(await http.post(f"{AUTH}/logout", headers=CSRF)).status_code for _ in range(5)]
    assert statuses == [204] * 5


# --- client IP -----------------------------------------------------------------------


def _request(socket_ip: str, forwarded_for: str | None) -> Request:
    headers = [(b"x-forwarded-for", forwarded_for.encode())] if forwarded_for else []
    return Request({"type": "http", "headers": headers, "client": (socket_ip, 1)})


@pytest.mark.parametrize(
    ("trusted", "forwarded_for", "expected"),
    [
        (0, None, "10.9.9.9"),
        (0, "1.1.1.1", "10.9.9.9"),  # untrusted header is ignored
        (1, None, "10.9.9.9"),
        (1, "1.1.1.1", "1.1.1.1"),
        (1, "6.6.6.6, 1.1.1.1", "1.1.1.1"),  # client-supplied prefix is ignored
        (2, "6.6.6.6, 1.1.1.1, 172.16.0.5", "1.1.1.1"),
        (2, "1.1.1.1", "10.9.9.9"),  # shorter than the proxy chain: not ours
    ],
)
def test_client_ip_trusts_forwarded_for_only_as_configured(
    settings_override: Callable[..., None],
    trusted: int,
    forwarded_for: str | None,
    expected: str,
) -> None:
    settings_override(trusted_proxy_count=trusted)
    assert client_ip(_request("10.9.9.9", forwarded_for)) == expected


async def test_spoofed_forwarded_for_does_not_bypass_the_ip_limit(
    settings_override: Callable[..., None],
) -> None:
    settings_override(rate_limit_credentials_ip_per_minute=2)
    async with from_ip("10.0.0.1") as http:
        statuses = [
            (
                await http.post(
                    f"{AUTH}/login",
                    json={"email": f"u{i}@example.com", "password": WRONG},
                    headers={"X-Forwarded-For": f"203.0.113.{i}"},
                )
            ).status_code
            for i in range(3)
        ]
    assert statuses == [401, 401, 429]


# --- refresh: failed attempts per IP -------------------------------------------------


async def _refresh_with(http: httpx.AsyncClient, token: str) -> httpx.Response:
    return await http.post(
        f"{AUTH}/refresh", headers={**CSRF, "Cookie": f"{REFRESH_COOKIE}={token}"}
    )


async def test_a_burst_of_made_up_refresh_tokens_gets_a_429() -> None:
    async with from_ip("10.0.0.1") as http:
        statuses = [(await _refresh_with(http, f"made-up-{i}")).status_code for i in range(20)]
        blocked = await _refresh_with(http, "made-up-20")
    async with from_ip("10.0.0.2") as other:
        other_ip = await _refresh_with(other, "made-up-21")

    assert statuses == [401] * 20
    assert blocked.status_code == 429
    assert 1 <= int(blocked.headers["retry-after"]) <= 600
    assert other_ip.status_code == 401  # per IP


async def test_normal_refreshes_from_the_same_ip_do_not_count_as_failures() -> None:
    async with from_ip("10.0.0.1") as http:
        await register(http, "asha@example.com")
        failures = [(await _refresh_with(http, f"made-up-{i}")).status_code for i in range(19)]
        # The real session keeps working, and its successes do not add to the count.
        real = [(await http.post(f"{AUTH}/refresh", headers=CSRF)).status_code for _ in range(10)]
        twentieth_failure = await _refresh_with(http, "made-up-19")
        after_limit = await _refresh_with(http, "made-up-20")

    assert failures == [401] * 19
    assert real == [200] * 10
    assert twentieth_failure.status_code == 401
    assert after_limit.status_code == 429


async def test_signed_out_page_loads_without_a_cookie_are_not_failures() -> None:
    async with from_ip("10.0.0.1") as http:
        statuses = [
            (await http.post(f"{AUTH}/refresh", headers=CSRF)).status_code for _ in range(30)
        ]
    assert statuses == [401] * 30


async def test_reusing_a_rotated_token_counts_as_a_failure(
    settings_override: Callable[..., None],
) -> None:
    settings_override(refresh_failure_limit=1)
    async with from_ip("10.0.0.1") as http:
        await register(http, "asha@example.com")
        old = http.cookies[REFRESH_COOKIE]
        assert (await http.post(f"{AUTH}/refresh", headers=CSRF)).status_code == 200
        assert (await _refresh_with(http, old)).status_code == 401
        assert (await _refresh_with(http, "anything")).status_code == 429
