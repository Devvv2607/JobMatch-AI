"""Jobs: boilerplate-stripped search text and a versioned embedding-input hash.

embedded_hash used to hold the content_hash an embedding came from; it now holds the
embed_input_hash. Existing values therefore never match, so every job is re-embedded with
the new recipe on the next ingest or `ingest embed`.

Revision ID: 0004
Revises: 0003
"""

import sqlalchemy as sa

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("search_text", sa.Text(), nullable=True))
    op.add_column("jobs", sa.Column("embed_input_hash", sa.String(64), nullable=True))


def downgrade() -> None:
    op.drop_column("jobs", "embed_input_hash")
    op.drop_column("jobs", "search_text")
