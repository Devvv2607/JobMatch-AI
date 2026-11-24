"""Companies created from feed postings (Remotive, Himalayas, Adzuna) are labelled
discovered_via = 'aggregator' instead of the column default 'manual'.

Revision ID: 0006
Revises: 0005
"""

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "UPDATE companies SET discovered_via = 'aggregator' "
        "WHERE board_token IS NULL AND discovered_via = 'manual'"
    )


def downgrade() -> None:
    op.execute("UPDATE companies SET discovered_via = 'manual' WHERE discovered_via = 'aggregator'")
