"""Jobs and stand-in models for retrieval tests.

The stand-ins are deterministic bag-of-words models: texts sharing words are close, and
the reranker scores a passage by how many query words it contains. They exercise the
pipeline's plumbing (filters, fusion, masking, labels) without the ONNX models, so these
tests also run in CI on the host; the real models are tested in test_reranker.py and
test_embedder.py inside the image.
"""

import hashlib
import math
import re
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.ingest.companies import company_slug
from app.models import Company, Job
from app.models.job import EMBEDDING_DIM

_WORD = re.compile(r"[a-z0-9+#]+")


def words(text: str) -> list[str]:
    return _WORD.findall(text.lower())


def bag_vector(text: str) -> list[float]:
    vector = [0.0] * EMBEDDING_DIM
    for word in words(text):
        slot = int(hashlib.sha256(word.encode()).hexdigest(), 16) % EMBEDDING_DIM
        vector[slot] += 1.0
    if not any(vector):
        vector[0] = 1.0  # cosine distance needs a non-zero vector
        return vector
    norm = math.sqrt(sum(v * v for v in vector))
    return [v / norm for v in vector]


class BagEmbedder:
    def embed_query(self, query: str) -> list[float]:
        return bag_vector(query)


class OverlapReranker:
    """Logit = query words found in the passage, minus 2: no overlap is clearly negative."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []
        self.max_tokens: list[int] = []

    def score(self, query: str, passages: list[str], max_tokens: int) -> list[float]:
        self.calls.append((query, len(passages)))
        self.max_tokens.append(max_tokens)
        wanted = set(words(query))
        return [float(len(wanted & set(words(p)))) - 2.0 for p in passages]


async def add_company(
    session: AsyncSession, name: str, industries: list[str] | None = None
) -> Company:
    company = Company(slug=company_slug(name), name=name, industries=industries or [])
    session.add(company)
    await session.flush()
    return company


def job_text(title: str, skills: list[str], text: str) -> str:
    return "\n".join([title, " ".join(skills), text])


async def add_job(
    session: AsyncSession, company: Company, title: str, text: str = "", **fields: Any
) -> Job:
    now = datetime.now(UTC)
    skills = fields.pop("skills", [])
    values: dict[str, Any] = {
        "source": "greenhouse",
        "source_id": uuid.uuid4().hex,
        "company_id": company.id,
        "title": title,
        "title_norm": title.lower(),
        "location": "Remote",
        "location_norm": "remote",
        "remote_policy": "remote",
        "employment_type": "full_time",
        "seniority": "mid",
        "work_countries": [],
        "eligibility_scope": "worldwide",
        "eligibility_source": "test",
        "description": text,
        "search_text": text,
        "skills": skills,
        "source_url": f"https://example.com/{uuid.uuid4().hex}",
        "first_seen_at": now,
        "last_seen_at": now,
        "content_changed_at": now,
        "content_hash": uuid.uuid4().hex,
        "status": "live",
        "embedding": bag_vector(job_text(title, skills, text)),
    }
    values.update(fields)
    job = Job(**values)
    session.add(job)
    await session.flush()
    return job
