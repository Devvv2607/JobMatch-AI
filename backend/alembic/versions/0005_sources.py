"""Phase 2b: more sources, provenance of companies, cross-source duplicates, salary refusals.

companies: website, yc_batch, investors, discovered_via (manual | yc-oss | vc:<firm> |
    commoncrawl), so the startup_backed dealbreaker and the README can say where a board
    came from.
jobs:
    source_quality      ats_direct | aggregator_full | aggregator_snippet
    description_quality full | snippet (Adzuna returns at most ~500 characters)
    alternate_sources   the same posting elsewhere (other sources, or the same text in
                        other cities): [{source, source_url, location, reason}], kept on
                        the canonical job and recomputed by every dedup pass
    salary_refusal      why salary-looking text was not parsed (e.g. "mixed_periods")
    source_page_url     the job's page on an aggregator, for attribution, when the apply
                        link (source_url) goes elsewhere (Himalayas requires both)

Existing Remotive rows become aggregator_full; every other existing row is ats_direct.

Revision ID: 0005
Revises: 0004
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("companies", sa.Column("website", sa.String(512), nullable=True))
    op.add_column("companies", sa.Column("yc_batch", sa.String(32), nullable=True))
    op.add_column(
        "companies",
        sa.Column(
            "investors",
            postgresql.ARRAY(sa.String(64)),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
    )
    op.add_column(
        "companies",
        sa.Column("discovered_via", sa.String(32), nullable=False, server_default="manual"),
    )
    op.add_column(
        "jobs",
        sa.Column("source_quality", sa.String(24), nullable=False, server_default="ats_direct"),
    )
    op.add_column(
        "jobs",
        sa.Column("description_quality", sa.String(16), nullable=False, server_default="full"),
    )
    op.add_column(
        "jobs",
        sa.Column(
            "alternate_sources",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column("jobs", sa.Column("salary_refusal", sa.String(64), nullable=True))
    op.add_column("jobs", sa.Column("source_page_url", sa.String(2048), nullable=True))
    op.execute("UPDATE jobs SET source_quality = 'aggregator_full' WHERE source = 'remotive'")
    op.create_check_constraint(
        "source_quality",
        "jobs",
        "source_quality IN ('ats_direct', 'aggregator_full', 'aggregator_snippet')",
    )
    op.create_check_constraint(
        "description_quality", "jobs", "description_quality IN ('full', 'snippet')"
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_jobs_description_quality"), "jobs", type_="check")
    op.drop_constraint(op.f("ck_jobs_source_quality"), "jobs", type_="check")
    op.drop_column("jobs", "source_page_url")
    op.drop_column("jobs", "salary_refusal")
    op.drop_column("jobs", "alternate_sources")
    op.drop_column("jobs", "description_quality")
    op.drop_column("jobs", "source_quality")
    op.drop_column("companies", "discovered_via")
    op.drop_column("companies", "investors")
    op.drop_column("companies", "yc_batch")
    op.drop_column("companies", "website")
