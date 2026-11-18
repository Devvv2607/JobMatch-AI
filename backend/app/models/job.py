"""Job postings and where they came from. Shared data: no user_id."""

import uuid
from datetime import datetime
from typing import Any, Literal

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAt, UuidPk

EMBEDDING_DIM = 384

Source = Literal["greenhouse", "lever", "ashby", "remotive"]
JobStatus = Literal["live", "updated", "stale", "expired"]
RemotePolicy = Literal["remote", "hybrid", "onsite", "unknown"]
EligibilityScope = Literal["worldwide", "listed", "unknown"]


class Company(Base, UuidPk, CreatedAt):
    __tablename__ = "companies"

    # Normalised company name; the join key across sources.
    slug: Mapped[str] = mapped_column(String(128), unique=True)
    name: Mapped[str] = mapped_column(String(256))
    # Set for companies from companies.yaml; null for companies only seen on Remotive.
    ats: Mapped[str | None] = mapped_column(String(16))
    board_token: Mapped[str | None] = mapped_column(String(128))
    industries: Mapped[list[str]] = mapped_column(ARRAY(String(64)), default=list)


class Job(Base, UuidPk):
    __tablename__ = "jobs"
    __table_args__ = (
        UniqueConstraint("source", "source_id", name="uq_jobs_source_source_id"),
        CheckConstraint("status IN ('live', 'updated', 'stale', 'expired')", name="status"),
        CheckConstraint(
            "remote_policy IN ('remote', 'hybrid', 'onsite', 'unknown')", name="remote_policy"
        ),
        CheckConstraint(
            "eligibility_scope IN ('worldwide', 'listed', 'unknown')", name="eligibility_scope"
        ),
        Index("ix_jobs_company_title_location", "company_id", "title_norm", "location_norm"),
        Index("ix_jobs_skills", "skills", postgresql_using="gin"),
        Index("ix_jobs_work_countries", "work_countries", postgresql_using="gin"),
        Index(
            "ix_jobs_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    source: Mapped[Source] = mapped_column(String(16))
    source_id: Mapped[str] = mapped_column(String(128))
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )

    title: Mapped[str] = mapped_column(String(512))
    title_norm: Mapped[str] = mapped_column(String(512))
    location: Mapped[str] = mapped_column(String(1024))
    location_norm: Mapped[str] = mapped_column(String(1024))
    remote_policy: Mapped[RemotePolicy] = mapped_column(String(8))
    employment_type: Mapped[str] = mapped_column(String(16))
    seniority: Mapped[str] = mapped_column(String(16), index=True)

    # Where the job can legally be done from: ISO 3166-1 alpha-2 codes. Empty when
    # eligibility_scope is "worldwide" or "unknown".
    work_countries: Mapped[list[str]] = mapped_column(ARRAY(String(2)), default=list)
    eligibility_scope: Mapped[EligibilityScope] = mapped_column(String(10))
    # Which field or rule decided the eligibility, e.g. "lever.country" or
    # "location:region:apac". Reported as rule coverage.
    eligibility_source: Mapped[str] = mapped_column(String(64))

    salary_min: Mapped[float | None] = mapped_column(Numeric(14, 2))
    salary_max: Mapped[float | None] = mapped_column(Numeric(14, 2))
    salary_currency: Mapped[str | None] = mapped_column(String(3))
    salary_interval: Mapped[str | None] = mapped_column(String(8))
    # Annualised and converted with the dated table in app/ingest/data/fx_rates.yaml.
    salary_min_usd: Mapped[int | None] = mapped_column(Integer, index=True)
    salary_max_usd: Mapped[int | None] = mapped_column(Integer)
    salary_source: Mapped[str | None] = mapped_column(String(32))

    description: Mapped[str] = mapped_column(Text)
    skills: Mapped[list[str]] = mapped_column(ARRAY(String(64)), default=list)
    source_url: Mapped[str] = mapped_column(String(2048))

    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    content_changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[JobStatus] = mapped_column(String(8), index=True)
    missed_runs: Mapped[int] = mapped_column(Integer, default=0)
    duplicate_of: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="SET NULL"), index=True
    )
    duplicate_reason: Mapped[str | None] = mapped_column(String(32))

    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))
    # The content_hash the embedding was computed from; differs when re-embedding is due.
    embedded_hash: Mapped[str | None] = mapped_column(String(64))

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class IngestRun(Base, UuidPk):
    """One row per source per run."""

    __tablename__ = "ingest_runs"

    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    source: Mapped[str] = mapped_column(String(16))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), default="running")
    boards_ok: Mapped[int] = mapped_column(Integer, default=0)
    boards_failed: Mapped[int] = mapped_column(Integer, default=0)
    fetched: Mapped[int] = mapped_column(Integer, default=0)
    new: Mapped[int] = mapped_column(Integer, default=0)
    updated: Mapped[int] = mapped_column(Integer, default=0)
    unchanged: Mapped[int] = mapped_column(Integer, default=0)
    expired: Mapped[int] = mapped_column(Integer, default=0)
    skipped: Mapped[int] = mapped_column(Integer, default=0)
    # [{"board": "...", "error": "..."}] for boards that could not be fetched or parsed.
    failures: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    note: Mapped[str | None] = mapped_column(String(500))
