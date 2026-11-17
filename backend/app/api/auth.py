from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, Response, status

from app.api.deps import CurrentUser, DbSession, rate_limit_by_ip, require_csrf_guard
from app.auth import service
from app.auth.schemas import Credentials, LoginRequest, SessionOut, UserOut
from app.core.config import get_settings
from app.core.errors import ConflictError, ErrorEnvelope, UnauthorizedError
from app.core.ratelimit import ensure_not_locked_out, record_failure

REFRESH_COOKIE = "jm_refresh"
_COOKIE_PATH = "/api/v1/auth"
_EMAIL_FAILURES = "credentials-email"

router = APIRouter(prefix="/auth", tags=["auth"])

# Login and register share one per-IP bucket. Refresh is limited per token family
# inside the service; logout is not limited.
_credentials_ip_limit = Depends(
    rate_limit_by_ip("credentials", lambda: get_settings().rate_limit_credentials_ip_per_minute)
)
_RATE_LIMITED: dict[int | str, dict[str, object]] = {
    429: {"model": ErrorEnvelope, "description": "Too many requests"}
}


async def _check_email_lockout(email: str) -> None:
    """Raises 429 once an email has too many failed attempts. Unknown emails are
    counted the same way, so the 429 does not reveal whether an account exists."""
    await ensure_not_locked_out(_EMAIL_FAILURES, email.lower(), get_settings().login_failure_limit)


async def _record_email_failure(email: str) -> None:
    await record_failure(
        _EMAIL_FAILURES, email.lower(), get_settings().login_failure_window_seconds
    )


def _set_refresh_cookie(response: Response, token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        REFRESH_COOKIE,
        token,
        max_age=settings.refresh_token_ttl_seconds,
        path=_COOKIE_PATH,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
    )


def _clear_refresh_cookie(response: Response) -> None:
    settings = get_settings()
    response.delete_cookie(
        REFRESH_COOKIE,
        path=_COOKIE_PATH,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
    )


def _session_out(issued: service.IssuedSession, response: Response) -> SessionOut:
    _set_refresh_cookie(response, issued.refresh_token)
    return SessionOut(
        access_token=issued.access_token,
        expires_in=issued.expires_in,
        user=UserOut.model_validate(issued.user),
    )


@router.post(
    "/register",
    status_code=status.HTTP_201_CREATED,
    dependencies=[_credentials_ip_limit],
    responses={409: {"model": ErrorEnvelope}, 422: {"model": ErrorEnvelope}, **_RATE_LIMITED},
)
async def register(body: Credentials, response: Response, session: DbSession) -> SessionOut:
    """Create an account and start a session."""
    await _check_email_lockout(body.email)
    try:
        issued = await service.register(session, body.email, body.password)
    except ConflictError:
        await _record_email_failure(body.email)
        raise
    return _session_out(issued, response)


@router.post(
    "/login",
    dependencies=[_credentials_ip_limit],
    responses={401: {"model": ErrorEnvelope}, 422: {"model": ErrorEnvelope}, **_RATE_LIMITED},
)
async def login(body: LoginRequest, response: Response, session: DbSession) -> SessionOut:
    """Start a session. Sets the refresh token as an httpOnly cookie."""
    await _check_email_lockout(body.email)
    try:
        issued = await service.login(session, body.email, body.password)
    except UnauthorizedError:
        await _record_email_failure(body.email)
        raise
    return _session_out(issued, response)


@router.post(
    "/refresh",
    dependencies=[Depends(require_csrf_guard)],
    responses={401: {"model": ErrorEnvelope}, 403: {"model": ErrorEnvelope}, **_RATE_LIMITED},
)
async def refresh(
    response: Response,
    session: DbSession,
    jm_refresh: Annotated[str | None, Cookie()] = None,
) -> SessionOut:
    """Exchange the refresh cookie for a new access token and a new refresh cookie.

    Each refresh token works once. Presenting one that was already used revokes every
    session descended from the same login.
    """
    if jm_refresh is None:
        raise UnauthorizedError("Session expired. Sign in again.")
    try:
        issued = await service.refresh(session, jm_refresh)
    except service.RefreshTokenReuseError:
        # Keep the family revocation; the request dependency would otherwise roll it back.
        await session.commit()
        raise
    return _session_out(issued, response)


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_csrf_guard)],
    responses={403: {"model": ErrorEnvelope}},
)
async def logout(
    response: Response,
    session: DbSession,
    jm_refresh: Annotated[str | None, Cookie()] = None,
) -> None:
    """End this session: revokes every refresh token descended from its login."""
    if jm_refresh is not None:
        await service.logout(session, jm_refresh)
    _clear_refresh_cookie(response)


@router.get("/me", responses={401: {"model": ErrorEnvelope}})
async def me(user: CurrentUser) -> UserOut:
    return UserOut.model_validate(user)
