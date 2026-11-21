"""Ingest runs: per-stage embed counts, error, and a status constraint.

Revision ID: 0003
Revises: 0002
"""

import sqlalchemy as sa

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ingest_runs", sa.Column("embedded", sa.Integer(), nullable=True))
    op.add_column("ingest_runs", sa.Column("embed_pending", sa.Integer(), nullable=True))
    op.add_column("ingest_runs", sa.Column("error", sa.String(1000), nullable=True))
    op.create_check_constraint(
        "ck_ingest_runs_status",
        "ingest_runs",
        "status IN ('running', 'succeeded', 'partial', 'failed', 'skipped')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_ingest_runs_status", "ingest_runs", type_="check")
    op.drop_column("ingest_runs", "error")
    op.drop_column("ingest_runs", "embed_pending")
    op.drop_column("ingest_runs", "embedded")
