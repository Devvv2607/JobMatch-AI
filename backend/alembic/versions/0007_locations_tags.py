"""Merged-location union and engagement/poster tags.

- all_locations / all_work_countries: a job's own location and countries plus those of
  every duplicate merged into it (recomputed by dedup), so a merged job stays findable
  from every variant's location and eligibility.
- engagement_type: full_time / part_time / contract / internship / freelance_gig.
- poster_type: employer / staffing_agency.
Both tags are deterministic (app/ingest/tags.py, rules in data/tags.yaml) and are filled
for existing rows by `python -m app.ingest.cli retag`.

Revision ID: 0007
Revises: 0006
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "jobs",
        sa.Column(
            "all_locations",
            postgresql.ARRAY(sa.String(1024)),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
    )
    op.add_column(
        "jobs",
        sa.Column(
            "all_work_countries",
            postgresql.ARRAY(sa.String(2)),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
    )
    op.add_column(
        "jobs",
        sa.Column("engagement_type", sa.String(16), nullable=False, server_default="full_time"),
    )
    op.add_column(
        "jobs",
        sa.Column("poster_type", sa.String(16), nullable=False, server_default="employer"),
    )
    op.execute(
        "UPDATE jobs SET all_work_countries = work_countries, "
        "all_locations = CASE WHEN location = '' THEN '{}'::varchar[] ELSE ARRAY[location] END, "
        "engagement_type = employment_type"
    )
    op.create_index(
        "ix_jobs_all_work_countries", "jobs", ["all_work_countries"], postgresql_using="gin"
    )
    op.create_check_constraint(
        "engagement_type",
        "jobs",
        "engagement_type IN ('full_time', 'part_time', 'contract', 'internship', 'freelance_gig')",
    )
    op.create_check_constraint(
        "poster_type", "jobs", "poster_type IN ('employer', 'staffing_agency')"
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_jobs_poster_type"), "jobs", type_="check")
    op.drop_constraint(op.f("ck_jobs_engagement_type"), "jobs", type_="check")
    op.drop_index("ix_jobs_all_work_countries", table_name="jobs")
    op.drop_column("jobs", "poster_type")
    op.drop_column("jobs", "engagement_type")
    op.drop_column("jobs", "all_work_countries")
    op.drop_column("jobs", "all_locations")
