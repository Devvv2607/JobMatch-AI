import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import security
from app.core.config import get_settings
from app.core.errors import ConflictError, UnauthorizedError
from app.models import RefreshToken, User

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class IssuedSession:
    user: User
    access_token: str
    expires_in: int
    refresh_token: str


async def register(session: AsyncSession, email: str, password: str) -> IssuedSession:
    user = User(email=email.lower(), password_hash=security.hash_password(password))
    session.add(user)
    try:
        await session.flush()
    except IntegrityError as exc:
        raise ConflictError("An account with this email already exists") from exc
    return await _issue(session, user, family_id=uuid.uuid4())


async def login(session: AsyncSession, email: str, password: str) -> IssuedSession:
    user = await session.scalar(select(User).where(User.email == email.lower()))
    if not security.verify_password(password, user.password_hash if user else None):
        raise UnauthorizedError("Email or password is incorrect")
    assert user is not None  # noqa: S101  # verify_password is False for an unknown user
    if security.password_needs_rehash(user.password_hash):
        user.password_hash = security.hash_password(password)
    return await _issue(session, user, family_id=uuid.uuid4())


async def refresh(session: AsyncSession, refresh_token: str) -> IssuedSession:
    """Rotates a refresh token.

    Raises RefreshTokenReuseError, after revoking the family, if the token was already
    rotated. The caller must commit in that case so the revocation is kept.
    """
    now = datetime.now(UTC)
    row = await session.scalar(
        select(RefreshToken)
        .where(RefreshToken.token_hash == security.hash_refresh_token(refresh_token))
        .with_for_update()
    )
    if row is None or row.revoked_at is not None or row.expires_at <= now:
        raise UnauthorizedError("Session expired. Sign in again.")
    if row.rotated_at is not None:
        await _revoke_family(session, row.family_id)
        logger.warning(
            "refresh token reuse detected, family revoked",
            extra={"user_id": str(row.user_id), "family_id": str(row.family_id)},
        )
        raise RefreshTokenReuseError("Session expired. Sign in again.")

    row.rotated_at = now
    user = await session.get(User, row.user_id)
    assert user is not None  # noqa: S101  # FK with ON DELETE CASCADE
    return await _issue(session, user, family_id=row.family_id)


async def logout(session: AsyncSession, refresh_token: str) -> None:
    row = await session.scalar(
        select(RefreshToken).where(
            RefreshToken.token_hash == security.hash_refresh_token(refresh_token)
        )
    )
    if row is not None:
        await _revoke_family(session, row.family_id)


async def purge_expired_refresh_tokens(session: AsyncSession) -> int:
    result = await session.execute(
        delete(RefreshToken).where(RefreshToken.expires_at < datetime.now(UTC))
    )
    return result.rowcount or 0  # type: ignore[attr-defined]


class RefreshTokenReuseError(UnauthorizedError):
    pass


async def _revoke_family(session: AsyncSession, family_id: uuid.UUID) -> None:
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )


async def _issue(session: AsyncSession, user: User, family_id: uuid.UUID) -> IssuedSession:
    token, token_hash = security.new_refresh_token()
    ttl = timedelta(seconds=get_settings().refresh_token_ttl_seconds)
    session.add(
        RefreshToken(
            user_id=user.id,
            family_id=family_id,
            token_hash=token_hash,
            expires_at=datetime.now(UTC) + ttl,
        )
    )
    await session.flush()
    access_token, expires_in = security.create_access_token(user.id)
    return IssuedSession(user, access_token, expires_in, token)
