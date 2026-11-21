"""The embedding input ("job card") and incremental embedding.

Two stages, run in this order by every ingest:

1. prepare_embedding_input: per company, strip boilerplate paragraphs from each
   description (app/ingest/boilerplate.py) and store the result as `search_text`; build
   the job card from it and store its hash as `embed_input_hash`. The hash includes
   EMBED_TEXT_VERSION, so changing the recipe marks every job for re-embedding.
2. embed_pending: embeds every non-expired job whose `embedded_hash` (the input hash its
   current vector was computed from) differs from `embed_input_hash`.

`search_text` is also the text Phase 3's BM25 index and reranker read, so search and the
vectors see the same words.

Memory: prepare holds one company's descriptions at a time; embed holds only the ids of
pending jobs and loads each small batch on its own. Batches are ordered by text length so
sequences in a batch pad to similar lengths. Each batch is committed, so an interrupted
run loses at most one batch, and progress is logged so a long run can be followed.
"""

import asyncio
import hashlib
import logging
import uuid
from typing import Any, Protocol

from sqlalchemy import ColumnElement, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.ingest.boilerplate import boilerplate_keys, strip_boilerplate
from app.models import Job

logger = logging.getLogger(__name__)

# The recipe for the embedded text. Bump it whenever job_card() or the stripping rule
# changes meaning; every job is then re-embedded on the next run.
#   1: title, level, skills, full description (Phase 2, until 2026-11-21)
#   2: title, level, skills, location, description without company boilerplate
EMBED_TEXT_VERSION = 2

# Attention memory grows with batch x tokens^2; 8 x 512 tokens keeps the peak modest.
BATCH_SIZE = 8
PROGRESS_EVERY = 500
_UPDATE_CHUNK = 500


class Embedder(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...


def job_card(title: str, seniority: str, skills: list[str], location: str, text: str) -> str:
    """The text embedded for a job: a structured header, then the stripped description.
    The tokenizer truncates at the model's 512-token limit, so the header always fits and
    the description fills the rest."""
    lines = [title, f"Level: {seniority}"]
    if skills:
        lines.append(f"Skills: {', '.join(skills)}")
    if location:
        lines.append(f"Location: {location}")
    header = "\n".join(lines)
    return f"{header}\n{text}" if text else header


def embed_input_hash(card: str) -> str:
    return hashlib.sha256(f"v{EMBED_TEXT_VERSION}\n{card}".encode()).hexdigest()


async def prepare_embedding_input(
    session: AsyncSession, *, min_share: float, min_postings: int
) -> int:
    """Recomputes `search_text` and `embed_input_hash` for every non-expired job, one
    company at a time, and writes the rows that changed. Returns how many changed.
    Boilerplate is judged against the company's current non-expired postings."""
    company_ids = (
        await session.scalars(select(Job.company_id).where(Job.status != "expired").distinct())
    ).all()
    changed = 0
    for company_id in company_ids:
        rows = (
            await session.execute(
                select(
                    Job.id,
                    Job.title,
                    Job.seniority,
                    Job.skills,
                    Job.location,
                    Job.description,
                    Job.search_text,
                    Job.embed_input_hash,
                ).where(Job.company_id == company_id, Job.status != "expired")
            )
        ).all()
        boilerplate = boilerplate_keys(
            (r.description for r in rows), min_share=min_share, min_postings=min_postings
        )
        updates: list[dict[str, Any]] = []
        for r in rows:
            text = strip_boilerplate(r.description, boilerplate)
            digest = embed_input_hash(job_card(r.title, r.seniority, r.skills, r.location, text))
            if text != r.search_text or digest != r.embed_input_hash:
                updates.append({"id": r.id, "search_text": text, "embed_input_hash": digest})
        for start in range(0, len(updates), _UPDATE_CHUNK):
            await session.execute(update(Job), updates[start : start + _UPDATE_CHUNK])
        changed += len(updates)
    await session.commit()
    logger.info("embedding input prepared", extra={"changed": changed})
    return changed


def _pending_filter() -> list[ColumnElement[bool]]:
    return [
        Job.status != "expired",
        or_(
            Job.embed_input_hash.is_(None),
            Job.embedded_hash.is_distinct_from(Job.embed_input_hash),
        ),
    ]


async def pending_by_source(session: AsyncSession) -> dict[str, int]:
    """How many non-expired jobs per source still need an embedding."""
    rows = await session.execute(
        select(Job.source, func.count()).where(*_pending_filter()).group_by(Job.source)
    )
    return {source: count for source, count in rows.all()}


async def embed_pending(
    session: AsyncSession, embedder: Embedder, done_by_source: dict[str, int] | None = None
) -> int:
    """Embeds every prepared, non-expired job whose embedding is missing or out of date,
    committing each batch. Returns how many were embedded; counts per source are added to
    `done_by_source` as batches commit, so they are right even if a later batch fails."""
    pending = (
        await session.execute(
            select(Job.id, Job.source)
            .where(*_pending_filter(), Job.embed_input_hash.is_not(None))
            .order_by(func.length(Job.search_text), Job.id)
        )
    ).all()
    for start in range(0, len(pending), BATCH_SIZE):
        batch = pending[start : start + BATCH_SIZE]
        ids: list[uuid.UUID] = [item.id for item in batch]
        rows = (
            await session.execute(
                select(
                    Job.id,
                    Job.title,
                    Job.seniority,
                    Job.skills,
                    Job.location,
                    Job.search_text,
                    Job.embed_input_hash,
                ).where(Job.id.in_(ids))
            )
        ).all()
        cards = [
            job_card(r.title, r.seniority, r.skills, r.location, r.search_text or "") for r in rows
        ]
        vectors = await asyncio.to_thread(embedder.embed, cards)
        await session.execute(
            update(Job),
            [
                {"id": r.id, "embedding": vector, "embedded_hash": r.embed_input_hash}
                for r, vector in zip(rows, vectors, strict=True)
            ],
        )
        await session.commit()
        if done_by_source is not None:
            for item in batch:
                done_by_source[item.source] = done_by_source.get(item.source, 0) + 1
        done = start + len(ids)
        if done % PROGRESS_EVERY < BATCH_SIZE or done == len(pending):
            logger.info("embedding progress", extra={"done": done, "pending": len(pending)})
    logger.info("embedded jobs", extra={"embedded": len(pending)})
    return len(pending)
