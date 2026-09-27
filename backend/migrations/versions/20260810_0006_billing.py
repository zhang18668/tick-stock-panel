"""Add billing plans and user subscriptions."""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260810_0006"
down_revision: str | None = "20260810_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "billing_plans",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("price_cents", sa.Integer(), nullable=False),
        sa.Column("billing_period", sa.String(length=20), nullable=False),
        sa.Column("entitlements", sa.JSON(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
    )
    op.create_table(
        "user_subscriptions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("plan_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("current_period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("current_period_end", sa.DateTime(timezone=True)),
        sa.Column("provider", sa.String(length=30), nullable=False),
        sa.Column("provider_subscription_id", sa.String(length=160)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["plan_id"], ["billing_plans.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id"),
    )
    op.create_index(
        "ix_user_subscriptions_status_end", "user_subscriptions", ["status", "current_period_end"]
    )
    plans = sa.table(
        "billing_plans",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("code", sa.String),
        sa.column("name", sa.String),
        sa.column("price_cents", sa.Integer),
        sa.column("billing_period", sa.String),
        sa.column("entitlements", sa.JSON),
        sa.column("active", sa.Boolean),
    )
    op.bulk_insert(
        plans,
        [
            {
                "id": "00000000-0000-0000-0000-000000000001",
                "code": "free",
                "name": "免费版",
                "price_cents": 0,
                "billing_period": "month",
                "entitlements": {"max_strategies": 3, "max_monitor_rules": 5},
                "active": True,
            },
            {
                "id": "00000000-0000-0000-0000-000000000002",
                "code": "pro",
                "name": "专业版",
                "price_cents": 9900,
                "billing_period": "month",
                "entitlements": {"max_strategies": 100, "max_monitor_rules": 100},
                "active": True,
            },
        ],
    )


def downgrade() -> None:
    op.drop_index("ix_user_subscriptions_status_end", table_name="user_subscriptions")
    op.drop_table("user_subscriptions")
    op.drop_table("billing_plans")
