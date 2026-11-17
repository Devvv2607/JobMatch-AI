import uuid
from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends, Header, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import security
from app.core.config import get_settings
from app.core.db import get_session
from app.core.errors import ForbiddenError, UnauthorizedError
from app.core.ratelimit import enforce_rate_limit
from app.models import User

DbSession = Annotated[AsyncSession, Depends(get_session)]

_bearer = HTTPBearer(auto_error=False, description="Access token from /auth/login")


async def get_current_user(
    session: DbSession,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> User:
    if credentials is None:
        raise UnauthorizedError("Sign in to continue", headers={"WWW-Authenticate": "Bearer"})
    user_id: uuid.UUID = security.decode_access_token(credentials.credentials)
    user = await session.get(User, user_id)
    if user is None:
        raise UnauthorizedError("Sign in to continue", headers={"WWW-Authenticate": "Bearer"})
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def rate_limit_by_ip(bucket: str, per_minute: int) -> Callable[[Request], Awaitable[None]]:
    async def dependency(request: Request) -> None:
        ip = request.client.host if request.client else "unknown"
        await enforce_rate_limit(bucket, ip, per_minute, 60)

    return dependency


async def rate_limit_user(user: CurrentUser) -> None:
    await enforce_rate_limit("user", str(user.id), get_settings().rate_limit_default_per_minute, 60)


async def require_csrf_guard(
    request: Request,
    x_requested_with: Annotated[
        str | None,
        Header(description="Must be `jobmatch`. Required on endpoints that read the cookie."),
    ] = None,
) -> None:
    """CSRF protection for endpoints authenticated by the refresh cookie.

    A cross-site form cannot set a custom header, and a cross-site fetch that sets one
    needs a CORS preflight, which only succeeds for configured origins. The Origin
    header is also checked directly when the browser sends it.
    """
    if x_requested_with != "jobmatch":
        raise ForbiddenError("Missing X-Requested-With header")
    origin = request.headers.get("origin")
    if origin is not None and origin.rstrip("/") not in get_settings().cors_origin_list:
        raise ForbiddenError("Origin not allowed")
