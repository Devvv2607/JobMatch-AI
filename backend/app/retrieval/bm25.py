"""BM25 over each job's title, skills and full search_text (bm25s), with hot swap.

Build (worker / ingest process, after an ingest):
  every current, non-duplicate job is tokenised (lower-case, English stopwords, Snowball
  stemmer) and indexed; the index, its vocabulary and the job ids in index order are
  written to a temporary directory under BM25_INDEX_DIR, renamed into place (atomic on
  one filesystem), and the new directory name is published in Redis (`bm25:version`).
  Older directories are pruned, keeping the previous one for API processes still on it.

Serve (API process):
  `Bm25Holder.current()` checks the Redis key at most every few seconds; when it changes,
  the new index is loaded in a thread and swapped in with one assignment. A search that
  already holds the old `Bm25Index` object finishes on it.

Masking: bm25s multiplies scores by `weight_mask`, so excluded jobs score 0. A 0 score can
still be returned when fewer than k jobs match, so zero-score hits are dropped here.

"Incremental" in PLAN.md §4.1 meant incremental tokenising; a full rebuild of ~12k jobs is
fast enough (measured in docs/retrieval.md) that it is not done yet.
"""

import asyncio
import json
import logging
import shutil
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import bm25s
import numpy as np
import Stemmer
from bm25s.tokenization import Tokenizer
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Job
from app.retrieval.rules import base_pool

logger = logging.getLogger(__name__)

VERSION_KEY = "bm25:version"
# Words, keeping + and # inside them so "c++" and "c#" survive as tokens.
_SPLITTER = r"(?u)\b\w[\w+#]*"
_IDS_FILE = "job_ids.json"
_META_FILE = "meta.json"


def document_text(title: str, skills: list[str], search_text: str | None) -> str:
    return "\n".join([title, " ".join(skills), search_text or ""])


def _tokenizer() -> Tokenizer:
    return Tokenizer(
        lower=True, stopwords="en", stemmer=Stemmer.Stemmer("english"), splitter=_SPLITTER
    )


@dataclass
class Bm25Index:
    version: str
    retriever: bm25s.BM25
    tokenizer: Tokenizer
    job_ids: list[uuid.UUID]
    position: dict[uuid.UUID, int]

    def search(
        self, query: str, k: int, allowed: set[uuid.UUID] | None = None
    ) -> list[tuple[uuid.UUID, float]]:
        """Top-k (job id, score), best first. `allowed=None` searches every document."""
        if not self.job_ids or not query.strip():
            return []
        tokens = self.tokenizer.tokenize(
            [query], update_vocab=False, return_as="ids", show_progress=False
        )
        if not tokens or not tokens[0]:
            return []  # no query word is in the index vocabulary
        mask = None
        if allowed is not None:
            mask = np.zeros(len(self.job_ids), dtype=np.float32)
            positions = [self.position[i] for i in allowed if i in self.position]
            if not positions:
                return []
            mask[positions] = 1.0
        documents, scores = self.retriever.retrieve(
            [tokens[0]],
            k=min(k, len(self.job_ids)),
            weight_mask=mask,
            show_progress=False,
            n_threads=0,
        )
        return [
            (self.job_ids[int(doc)], float(score))
            for doc, score in zip(documents[0], scores[0], strict=True)
            if score > 0
        ]


async def build_index(session: AsyncSession, root: Path) -> tuple[str, int]:
    """Builds an index of the current pool under `root` and returns (version, documents).
    Does not publish it: call `publish` after."""
    rows = (
        await session.execute(
            select(Job.id, Job.title, Job.skills, Job.search_text)
            .where(base_pool())
            .order_by(Job.id)
        )
    ).all()
    job_ids = [row.id for row in rows]
    texts = [document_text(row.title, row.skills, row.search_text) for row in rows]
    del rows
    version = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    await asyncio.to_thread(_build_files, root, version, texts, job_ids)
    return version, len(job_ids)


def _build_files(root: Path, version: str, texts: list[str], job_ids: list[uuid.UUID]) -> None:
    """Writes the index to a staging directory, then renames it to `root/version`."""
    started = time.perf_counter()
    root.mkdir(parents=True, exist_ok=True)
    directory = root / f".tmp-{version}"
    tokenizer = _tokenizer()
    corpus = tokenizer.tokenize(texts, update_vocab=True, return_as="ids", show_progress=False)
    retriever = bm25s.BM25()
    if texts:
        retriever.index(
            (corpus, tokenizer.get_vocab_dict()), show_progress=False, leave_progress=False
        )
    directory.mkdir(parents=True)
    if texts:
        retriever.save(str(directory), show_progress=False)
    tokenizer.save_vocab(save_dir=str(directory))
    tokenizer.save_stopwords(save_dir=str(directory))
    (directory / _IDS_FILE).write_text(json.dumps([str(i) for i in job_ids]))
    (directory / _META_FILE).write_text(
        json.dumps({"documents": len(job_ids), "seconds": round(time.perf_counter() - started, 2)})
    )
    directory.rename(root / version)


async def publish(redis: Redis, root: Path, version: str, keep: int = 2) -> None:
    """Points every API process at `version` and removes all but the newest `keep`."""
    await redis.set(VERSION_KEY, version)
    await asyncio.to_thread(_prune, root, keep)


def _prune(root: Path, keep: int) -> None:
    versions = sorted(p.name for p in root.iterdir() if p.is_dir() and not p.name.startswith("."))
    for old in versions[:-keep]:
        shutil.rmtree(root / old, ignore_errors=True)
    # Staging directories left by a build that died before its rename. Only old ones: a
    # concurrent build (cron and a manual `make bm25`) may be writing a recent one.
    cutoff = time.time() - 3600
    for staging in root.glob(".tmp-*"):
        if staging.stat().st_mtime < cutoff:
            shutil.rmtree(staging, ignore_errors=True)


async def rebuild(session: AsyncSession, redis: Redis, root: Path) -> tuple[str, int, float]:
    """Build, publish and prune. Returns (version, documents, seconds)."""
    started = time.perf_counter()
    version, documents = await build_index(session, root)
    await publish(redis, root, version)
    seconds = round(time.perf_counter() - started, 2)
    logger.info(
        "bm25 index published",
        extra={"version": version, "documents": documents, "seconds": seconds},
    )
    return version, documents, seconds


def load_index(directory: Path) -> Bm25Index:
    job_ids = [uuid.UUID(i) for i in json.loads((directory / _IDS_FILE).read_text())]
    tokenizer = _tokenizer()
    tokenizer.load_vocab(save_dir=str(directory))
    tokenizer.load_stopwords(save_dir=str(directory))
    retriever = bm25s.BM25.load(str(directory)) if job_ids else bm25s.BM25()
    return Bm25Index(
        version=directory.name,
        retriever=retriever,
        tokenizer=tokenizer,
        job_ids=job_ids,
        position={job_id: i for i, job_id in enumerate(job_ids)},
    )


class Bm25Holder:
    """The API's current index. Swapped, never mutated, so readers need no lock."""

    def __init__(self, root: Path, redis: Redis, check_seconds: float) -> None:
        self._root = root
        self._redis = redis
        self._check_seconds = check_seconds
        self._index: Bm25Index | None = None
        self._checked_at = float("-inf")
        self._lock = asyncio.Lock()

    @property
    def index(self) -> Bm25Index | None:
        return self._index

    async def current(self) -> Bm25Index | None:
        now = time.monotonic()
        if now - self._checked_at >= self._check_seconds:
            self._checked_at = now
            await self._refresh()
        return self._index

    async def _refresh(self) -> None:
        version = await self._redis.get(VERSION_KEY)
        if isinstance(version, bytes):
            version = version.decode()
        if version is None or (self._index is not None and self._index.version == version):
            return
        async with self._lock:
            if self._index is not None and self._index.version == version:
                return
            directory = self._root / version
            if not directory.is_dir():
                logger.warning("bm25 index version not on disk", extra={"version": version})
                return
            loaded = await asyncio.to_thread(load_index, directory)
            previous = self._index.version if self._index else None
            self._index = loaded
            logger.info(
                "bm25 index swapped",
                extra={"version": version, "previous": previous, "documents": len(loaded.job_ids)},
            )
