"""Foundation: users, refresh tokens, background tasks, LLM cache, pgvector extension.

Revision ID: 0001
Revises:
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

_UUID = postgresql.UUID(as_uuid=True)
_NOW = sa.text("now()")
_NEW_UUID = sa.text("gen_random_uuid()")


def upgrade() -> None:
    # Enabled here so a database without pgvector fails on day one, not in Phase 2.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "users",
        sa.Column("id", _UUID, server_default=_NEW_UUID, nullable=False),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )

    op.create_table(
        "refresh_tokens",
        sa.Column("id", _UUID, server_default=_NEW_UUID, nullable=False),
        sa.Column("user_id", _UUID, nullable=False),
        sa.Column("family_id", _UUID, nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("rotated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_refresh_tokens"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_refresh_tokens_user_id_users", ondelete="CASCADE"
        ),
        sa.UniqueConstraint("token_hash", name="uq_refresh_tokens_token_hash"),
    )
    op.create_index("ix_refresh_tokens_user_id", "refresh_tokens", ["user_id"])
    op.create_index("ix_refresh_tokens_family_id", "refresh_tokens", ["family_id"])
    op.create_index("ix_refresh_tokens_expires_at", "refresh_tokens", ["expires_at"])

    op.create_table(
        "background_tasks",
        sa.Column("id", _UUID, server_default=_NEW_UUID, nullable=False),
        sa.Column("user_id", _UUID, nullable=False),
        sa.Column("kind", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("result", postgresql.JSONB(), nullable=True),
        sa.Column("error", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_background_tasks"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_background_tasks_user_id_users", ondelete="CASCADE"
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed')",
            name="ck_background_tasks_status",
        ),
    )
    op.create_index("ix_background_tasks_user_id", "background_tasks", ["user_id"])
    op.create_index("ix_background_tasks_status", "background_tasks", ["status"])

    op.create_table(
        "llm_cache",
        sa.Column("key", sa.String(64), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("model", sa.String(128), nullable=False),
        sa.Column("prompt_name", sa.String(64), nullable=False),
        sa.Column("prompt_version", sa.Integer(), nullable=False),
        sa.Column("response", sa.Text(), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False),
        sa.Column("completion_tokens", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.PrimaryKeyConstraint("key", name="pk_llm_cache"),
    )
    op.create_index("ix_llm_cache_prompt_name", "llm_cache", ["prompt_name"])


def downgrade() -> None:
    op.drop_table("llm_cache")
    op.drop_table("background_tasks")
    op.drop_table("refresh_tokens")
    op.drop_table("users")
    op.execute("DROP EXTENSION IF EXISTS vector")
