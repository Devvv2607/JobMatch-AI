"""Evergreen postings and openings per merged job (owner review 2026-11-25).

- is_evergreen: a standing pipeline rather than an opening ("Talent Community",
  "Expression of Interest", "join our global talent network"). Deterministic
  (app/ingest/tags.py); filled for existing rows by `python -m app.ingest.cli retag`.
- openings_count: how many postings of one role a merged job stands for at one place:
  the largest number of its postings (itself and its duplicates) from one source at one
  normalised location, e.g. two requisitions with the same text in Bengaluru = 2.
  Recomputed by dedup.

Revision ID: 0008
Revises: 0007
"""

import sqlalchemy as sa

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "jobs",
        sa.Column("is_evergreen", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "jobs",
        sa.Column("openings_count", sa.Integer(), nullable=False, server_default="1"),
    )


def downgrade() -> None:
    op.drop_column("jobs", "openings_count")
    op.drop_column("jobs", "is_evergreen")
