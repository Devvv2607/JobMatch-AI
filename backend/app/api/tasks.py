import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict

from app.api.deps import CurrentUser, DbSession, rate_limit_user
from app.core.errors import ErrorEnvelope
from app.core.scoping import get_owned
from app.models import BackgroundTask
from app.models.task import TaskStatus

router = APIRouter(prefix="/tasks", tags=["tasks"], dependencies=[Depends(rate_limit_user)])


class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: str
    status: TaskStatus
    result: dict[str, Any] | None
    error: str | None
    created_at: datetime
    updated_at: datetime


@router.get(
    "/{task_id}",
    responses={401: {"model": ErrorEnvelope}, 404: {"model": ErrorEnvelope}},
)
async def get_task(task_id: uuid.UUID, user: CurrentUser, session: DbSession) -> TaskOut:
    """Status of a background job the signed-in user started."""
    task = await get_owned(session, BackgroundTask, task_id, user.id)
    return TaskOut.model_validate(task)
