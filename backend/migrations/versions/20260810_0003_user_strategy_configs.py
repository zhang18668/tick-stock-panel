"""Add user-scoped strategy override configs."""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260810_0003"
down_revision: str | None = "20260810_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_strategy_configs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("strategy_id", sa.String(length=120), nullable=False),
        sa.Column("overrides", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "strategy_id", name="uq_user_strategy_config"),
    )
    op.create_index(
        "ix_user_strategy_configs_user", "user_strategy_configs", ["user_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_user_strategy_configs_user", table_name="user_strategy_configs")
    op.drop_table("user_strategy_configs")
