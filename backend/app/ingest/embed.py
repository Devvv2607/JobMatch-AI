"""Incremental embedding: only jobs whose content changed since they were last embedded.

Memory: only the ids of pending jobs are held; each small batch is loaded, embedded and
written back on its own. Batches are ordered by description length so sequences in a
batch pad to similar lengths.

Each batch is committed, so an interrupted run loses at most one batch, and progress is
logged so a long first run can be followed.
"""

import asyncio
import logging
from typing import Protocol

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Job

logger = logging.getLogger(__name__)

# Attention memory grows with batch x tokens^2; 8 x 512 tokens keeps the peak modest.
BATCH_SIZE = 8
PROGRESS_EVERY = 500


class Embedder(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...


def job_card(title: str, seniority: str, skills: list[str], description: str) -> str:
    """The text embedded for a job. The tokenizer truncates at the model's limit, so the
    title, level and skills always fit and the description fills the rest."""
    skill_line = f"Skills: {', '.join(skills)}\n" if skills else ""
    return f"{title}\nLevel: {seniority}\n{skill_line}{description}"


async def embed_pending(session: AsyncSession, embedder: Embedder) -> int:
    """Embeds every non-expired job whose embedding is missing or out of date.
    Returns how many were embedded."""
    pending = (
        await session.scalars(
            select(Job.id)
            .where(
                Job.status != "expired",
                Job.embedded_hash.is_distinct_from(Job.content_hash),
            )
            .order_by(func.length(Job.description), Job.id)
        )
    ).all()
    for start in range(0, len(pending), BATCH_SIZE):
        ids = pending[start : start + BATCH_SIZE]
        rows = (
            await session.execute(
                select(
                    Job.id, Job.title, Job.seniority, Job.skills, Job.description, Job.content_hash
                ).where(Job.id.in_(ids))
            )
        ).all()
        cards = [job_card(r.title, r.seniority, r.skills, r.description) for r in rows]
        vectors = await asyncio.to_thread(embedder.embed, cards)
        for row, vector in zip(rows, vectors, strict=True):
            await session.execute(
                update(Job)
                .where(Job.id == row.id)
                .values(embedding=vector, embedded_hash=row.content_hash)
                .execution_options(synchronize_session=False)
            )
        await session.commit()
        done = start + len(ids)
        if done % PROGRESS_EVERY < BATCH_SIZE or done == len(pending):
            logger.info("embedding progress", extra={"done": done, "pending": len(pending)})
    logger.info("embedded jobs", extra={"embedded": len(pending)})
    return len(pending)
