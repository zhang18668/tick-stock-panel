"""Replace free with one-day trial and add paid professional plans."""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260811_0007"
down_revision: str | None = "20260810_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "UPDATE billing_plans SET code='trial', name='试用版', billing_period='day' "
        "WHERE code='free'"
    )
    op.execute(
        "UPDATE billing_plans SET code='pro_monthly', name='专业版(月付)', "
        "price_cents=19900, billing_period='month' WHERE code='pro'"
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
    op.bulk_insert(plans, [{
        "id": "00000000-0000-0000-0000-000000000003",
        "code": "pro_yearly",
        "name": "专业版(包年)",
        "price_cents": 199900,
        "billing_period": "year",
        "entitlements": {"max_strategies": 100, "max_monitor_rules": 100},
        "active": True,
    }])
    op.create_table(
        "payment_orders",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("plan_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(30), nullable=False),
        sa.Column("out_trade_no", sa.String(64), nullable=False),
        sa.Column("provider_trade_no", sa.String(160)),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("code_url", sa.String(2048)),
        sa.Column("paid_at", sa.DateTime(timezone=True)),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["plan_id"], ["billing_plans.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("out_trade_no"),
    )
    op.create_index("ix_payment_orders_user_created", "payment_orders", ["user_id", "created_at"])
    op.create_index("ix_payment_orders_status_expires", "payment_orders", ["status", "expires_at"])


def downgrade() -> None:
    op.drop_index("ix_payment_orders_status_expires", table_name="payment_orders")
    op.drop_index("ix_payment_orders_user_created", table_name="payment_orders")
    op.drop_table("payment_orders")
    op.execute("DELETE FROM billing_plans WHERE code='pro_yearly'")
    op.execute("UPDATE billing_plans SET code='pro', name='专业版', price_cents=9900 WHERE code='pro_monthly'")
    op.execute("UPDATE billing_plans SET code='free', name='免费版', billing_period='month' WHERE code='trial'")
