from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.api.deps import CurrentUser, DbSession, rate_limit_user
from app.core.errors import ErrorEnvelope
from app.ingest.freshness import cached_freshness

router = APIRouter(prefix="/jobs", tags=["jobs"], dependencies=[Depends(rate_limit_user)])


class LastRun(BaseModel):
    started_at: datetime | None
    finished_at: datetime | None
    statuses: list[str] = Field(description="Per-source outcomes of the run, e.g. succeeded")
    added: int
    updated: int
    expired: int


class FreshnessOut(BaseModel):
    updated_at: datetime | None = Field(
        description="When the last successful ingest finished; null if none has"
    )
    last_run: LastRun


@router.get("/freshness", responses={401: {"model": ErrorEnvelope}})
async def jobs_freshness(_: CurrentUser, session: DbSession) -> FreshnessOut:
    """How current the job pool is, for an "Updated 3 hours ago" label."""
    f = await cached_freshness(session)
    return FreshnessOut(
        updated_at=f.last_success_at,
        last_run=LastRun(
            started_at=f.last_run_started_at,
            finished_at=f.last_run_finished_at,
            statuses=f.last_run_statuses,
            added=f.added,
            updated=f.updated,
            expired=f.expired,
        ),
    )
