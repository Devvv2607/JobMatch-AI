import uuid
from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAt, UserOwned, UuidPk


class User(Base, UuidPk, CreatedAt):
    __tablename__ = "users"

    # Stored lower-cased; uniqueness is therefore case-insensitive.
    email: Mapped[str] = mapped_column(String(320), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))


class RefreshToken(Base, UuidPk, CreatedAt, UserOwned):
    """One row per issued refresh token. Only the SHA-256 of the token is stored.

    Tokens issued from the same login share a family. Presenting a token that was
    already rotated means it was copied, so the whole family is revoked.
    """

    __tablename__ = "refresh_tokens"

    family_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    rotated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
