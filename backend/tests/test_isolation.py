"""User A cannot read user B's rows: through the scoping helper, through the API, or
because a new table forgot to be user-owned."""

import uuid

import httpx
import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.core.scoping import get_owned, scoped
from app.models import BackgroundTask, Base, RefreshToken, User
from app.models.base import SHARED_TABLES, UserOwned
from tests.helpers import bearer, register


async def _task_for(session: AsyncSession, user_id: str, kind: str) -> BackgroundTask:
    task = BackgroundTask(user_id=uuid.UUID(user_id), kind=kind, status="succeeded")
    session.add(task)
    await session.commit()
    return task


async def test_scoped_returns_only_the_users_own_rows(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    a = (await register(client, "a@example.com"))["user"]["id"]
    b = (await register(client, "b@example.com"))["user"]["id"]
    task_a = await _task_for(session, a, "parse_resume")
    task_b = await _task_for(session, b, "parse_resume")

    rows_a = (await session.scalars(scoped(BackgroundTask, uuid.UUID(a)))).all()
    rows_b = (await session.scalars(scoped(BackgroundTask, uuid.UUID(b)))).all()

    assert [row.id for row in rows_a] == [task_a.id]
    assert [row.id for row in rows_b] == [task_b.id]


async def test_get_owned_reports_another_users_row_as_not_found(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    a = (await register(client, "a@example.com"))["user"]["id"]
    b = (await register(client, "b@example.com"))["user"]["id"]
    task_b = await _task_for(session, b, "parse_resume")

    owned = await get_owned(session, BackgroundTask, task_b.id, uuid.UUID(b))
    assert owned.id == task_b.id

    with pytest.raises(NotFoundError):
        await get_owned(session, BackgroundTask, task_b.id, uuid.UUID(a))


async def test_api_does_not_reveal_another_users_task(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    session_a = await register(client, "a@example.com")
    session_b = await register(client, "b@example.com")
    task_b = await _task_for(session, session_b["user"]["id"], "tailor")

    as_owner = await client.get(f"/api/v1/tasks/{task_b.id}", headers=bearer(session_b))
    assert as_owner.status_code == 200
    assert as_owner.json()["kind"] == "tailor"

    as_other = await client.get(f"/api/v1/tasks/{task_b.id}", headers=bearer(session_a))
    missing = await client.get(f"/api/v1/tasks/{uuid.uuid4()}", headers=bearer(session_a))
    # Someone else's row and a row that does not exist are indistinguishable.
    assert as_other.status_code == missing.status_code == 404
    assert as_other.json()["error"]["message"] == missing.json()["error"]["message"]

    anonymous = await client.get(f"/api/v1/tasks/{task_b.id}")
    assert anonymous.status_code == 401


def test_every_table_is_either_shared_or_user_owned() -> None:
    """Fails when a new table is added without UserOwned and without being listed as shared."""
    for mapper in Base.registry.mappers:
        table = Base.metadata.tables[mapper.class_.__tablename__]
        if table.name in SHARED_TABLES:
            continue
        assert issubclass(mapper.class_, UserOwned), f"{table.name} must use UserOwned"
        (foreign_key,) = table.c.user_id.foreign_keys
        assert foreign_key.column.table.name == "users"
        assert foreign_key.ondelete == "CASCADE", f"{table.name}.user_id must cascade"
        assert not table.c.user_id.nullable


async def test_deleting_a_user_removes_their_rows_and_nobody_elses(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    a = (await register(client, "a@example.com"))["user"]["id"]
    b = (await register(client, "b@example.com"))["user"]["id"]
    await _task_for(session, a, "parse_resume")
    await _task_for(session, b, "parse_resume")

    await session.execute(delete(User).where(User.id == uuid.UUID(a)))
    await session.commit()

    for model in (BackgroundTask, RefreshToken):
        remaining = (await session.scalars(select(model.user_id))).all()
        assert remaining == [uuid.UUID(b)], model.__tablename__
    assert await session.scalar(select(func.count()).select_from(User)) == 1
