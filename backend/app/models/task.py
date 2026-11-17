from datetime import datetime
from typing import Any, Literal

from sqlalchemy import CheckConstraint, DateTime, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAt, UserOwned, UuidPk

TaskStatus = Literal["queued", "running", "succeeded", "failed"]


class BackgroundTask(Base, UuidPk, CreatedAt, UserOwned):
    """Status of a worker job, so the UI can poll work it started."""

    __tablename__ = "background_tasks"
    __table_args__ = (
        CheckConstraint("status IN ('queued', 'running', 'succeeded', 'failed')", name="status"),
    )

    kind: Mapped[str] = mapped_column(String(64))
    status: Mapped[TaskStatus] = mapped_column(String(16), default="queued", index=True)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(String(500))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
