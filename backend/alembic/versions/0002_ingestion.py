"""Ingestion: companies, jobs, ingest_runs.

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

_UUID = postgresql.UUID(as_uuid=True)
_NOW = sa.text("now()")
_NEW_UUID = sa.text("gen_random_uuid()")
_TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "companies",
        sa.Column("id", _UUID, server_default=_NEW_UUID, nullable=False),
        sa.Column("slug", sa.String(128), nullable=False),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("ats", sa.String(16), nullable=True),
        sa.Column("board_token", sa.String(128), nullable=True),
        sa.Column("industries", postgresql.ARRAY(sa.String(64)), nullable=False),
        sa.Column("created_at", _TS, server_default=_NOW, nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_companies"),
        sa.UniqueConstraint("slug", name="uq_companies_slug"),
    )

    op.create_table(
        "jobs",
        sa.Column("id", _UUID, server_default=_NEW_UUID, nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("source_id", sa.String(128), nullable=False),
        sa.Column("company_id", _UUID, nullable=False),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("title_norm", sa.String(512), nullable=False),
        sa.Column("location", sa.String(1024), nullable=False),
        sa.Column("location_norm", sa.String(1024), nullable=False),
        sa.Column("remote_policy", sa.String(8), nullable=False),
        sa.Column("employment_type", sa.String(16), nullable=False),
        sa.Column("seniority", sa.String(16), nullable=False),
        sa.Column("work_countries", postgresql.ARRAY(sa.String(2)), nullable=False),
        sa.Column("eligibility_scope", sa.String(10), nullable=False),
        sa.Column("eligibility_source", sa.String(64), nullable=False),
        sa.Column("salary_min", sa.Numeric(14, 2), nullable=True),
        sa.Column("salary_max", sa.Numeric(14, 2), nullable=True),
        sa.Column("salary_currency", sa.String(3), nullable=True),
        sa.Column("salary_interval", sa.String(8), nullable=True),
        sa.Column("salary_min_usd", sa.Integer(), nullable=True),
        sa.Column("salary_max_usd", sa.Integer(), nullable=True),
        sa.Column("salary_source", sa.String(32), nullable=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("skills", postgresql.ARRAY(sa.String(64)), nullable=False),
        sa.Column("source_url", sa.String(2048), nullable=False),
        sa.Column("posted_at", _TS, nullable=True),
        sa.Column("first_seen_at", _TS, nullable=False),
        sa.Column("last_seen_at", _TS, nullable=False),
        sa.Column("content_changed_at", _TS, nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(8), nullable=False),
        sa.Column("missed_runs", sa.Integer(), nullable=False),
        sa.Column("duplicate_of", _UUID, nullable=True),
        sa.Column("duplicate_reason", sa.String(32), nullable=True),
        sa.Column("embedding", Vector(384), nullable=True),
        sa.Column("embedded_hash", sa.String(64), nullable=True),
        sa.Column("updated_at", _TS, server_default=_NOW, nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_jobs"),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            name="fk_jobs_company_id_companies",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["duplicate_of"], ["jobs.id"], name="fk_jobs_duplicate_of_jobs", ondelete="SET NULL"
        ),
        sa.UniqueConstraint("source", "source_id", name="uq_jobs_source_source_id"),
        sa.CheckConstraint(
            "status IN ('live', 'updated', 'stale', 'expired')", name="ck_jobs_status"
        ),
        sa.CheckConstraint(
            "remote_policy IN ('remote', 'hybrid', 'onsite', 'unknown')",
            name="ck_jobs_remote_policy",
        ),
        sa.CheckConstraint(
            "eligibility_scope IN ('worldwide', 'listed', 'unknown')",
            name="ck_jobs_eligibility_scope",
        ),
    )
    op.create_index("ix_jobs_company_id", "jobs", ["company_id"])
    op.create_index("ix_jobs_seniority", "jobs", ["seniority"])
    op.create_index("ix_jobs_salary_min_usd", "jobs", ["salary_min_usd"])
    op.create_index("ix_jobs_posted_at", "jobs", ["posted_at"])
    op.create_index("ix_jobs_content_hash", "jobs", ["content_hash"])
    op.create_index("ix_jobs_status", "jobs", ["status"])
    op.create_index("ix_jobs_duplicate_of", "jobs", ["duplicate_of"])
    op.create_index(
        "ix_jobs_company_title_location", "jobs", ["company_id", "title_norm", "location_norm"]
    )
    op.create_index("ix_jobs_skills", "jobs", ["skills"], postgresql_using="gin")
    op.create_index("ix_jobs_work_countries", "jobs", ["work_countries"], postgresql_using="gin")
    op.create_index(
        "ix_jobs_embedding_hnsw",
        "jobs",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )

    op.create_table(
        "ingest_runs",
        sa.Column("id", _UUID, server_default=_NEW_UUID, nullable=False),
        sa.Column("run_id", _UUID, nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("started_at", _TS, server_default=_NOW, nullable=False),
        sa.Column("finished_at", _TS, nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("boards_ok", sa.Integer(), nullable=False),
        sa.Column("boards_failed", sa.Integer(), nullable=False),
        sa.Column("fetched", sa.Integer(), nullable=False),
        sa.Column("new", sa.Integer(), nullable=False),
        sa.Column("updated", sa.Integer(), nullable=False),
        sa.Column("unchanged", sa.Integer(), nullable=False),
        sa.Column("expired", sa.Integer(), nullable=False),
        sa.Column("skipped", sa.Integer(), nullable=False),
        sa.Column("failures", postgresql.JSONB(), nullable=False),
        sa.Column("note", sa.String(500), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_ingest_runs"),
    )
    op.create_index("ix_ingest_runs_run_id", "ingest_runs", ["run_id"])


def downgrade() -> None:
    op.drop_table("ingest_runs")
    op.drop_table("jobs")
    op.drop_table("companies")
