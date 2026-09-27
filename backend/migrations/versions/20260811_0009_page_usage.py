"""Add privacy-minimal per-page usage counters."""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260811_0009"
down_revision: str | None = "20260811_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_page_usage",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("path", sa.String(length=160), nullable=False),
        sa.Column("view_count", sa.Integer(), nullable=False),
        sa.Column("last_viewed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "path", name="uq_user_page_usage_user_path"),
    )
    op.create_index("ix_user_page_usage_path_count", "user_page_usage", ["path", "view_count"])


def downgrade() -> None:
    op.drop_index("ix_user_page_usage_path_count", table_name="user_page_usage")
    op.drop_table("user_page_usage")
