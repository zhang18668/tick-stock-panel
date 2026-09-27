"""Add user-scoped backtest results."""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260810_0005"
down_revision: str | None = "20260810_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_backtest_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", sa.String(length=120), nullable=False),
        sa.Column("run_type", sa.String(length=30), nullable=False),
        sa.Column("strategy_id", sa.String(length=120)),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("request_data", sa.JSON(), nullable=False),
        sa.Column("result_data", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "run_id", name="uq_user_backtest_run"),
    )
    op.create_index(
        "ix_user_backtest_runs_user_created", "user_backtest_runs", ["user_id", "created_at"]
    )
    op.create_index(
        "ix_user_backtest_runs_user_strategy", "user_backtest_runs", ["user_id", "strategy_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_user_backtest_runs_user_strategy", table_name="user_backtest_runs")
    op.drop_index("ix_user_backtest_runs_user_created", table_name="user_backtest_runs")
    op.drop_table("user_backtest_runs")
