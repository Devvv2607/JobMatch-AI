"""The only way user-owned rows are read.

Every query for a user-owned table starts from `scoped()` or `get_owned()`, so the
user filter cannot be forgotten at a call site. A row that belongs to someone else is
reported as not found, never as forbidden, so ids cannot be probed.
"""

import uuid
from typing import Any

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.models.base import UserOwned


def scoped[T: UserOwned](model: type[T], user_id: uuid.UUID) -> Select[T]:
    return select(model).where(model.user_id == user_id)


async def get_owned[T: UserOwned](
    session: AsyncSession, model: type[T], row_id: uuid.UUID, user_id: uuid.UUID
) -> T:
    id_column: Any = model.id  # type: ignore[attr-defined]  # every model has a UuidPk
    row = await session.scalar(scoped(model, user_id).where(id_column == row_id))
    if row is None:
        raise NotFoundError("Not found")
    return row
