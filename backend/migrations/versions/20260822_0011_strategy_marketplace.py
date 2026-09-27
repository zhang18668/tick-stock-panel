"""Add account-isolated strategy marketplace purchases and installations."""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260822_0012"
down_revision: str | None = "20260812_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "strategy_listings",
        sa.Column("strategy_id", sa.String(120), primary_key=True),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("points_price", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("points_price >= 0", name="ck_strategy_listing_points_price"),
    )
    op.create_table(
        "user_strategy_purchases",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("strategy_id", sa.String(120), nullable=False),
        sa.Column("amount", sa.BigInteger(), nullable=False),
        sa.Column("purchased_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["strategy_id"], ["strategy_listings.strategy_id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("user_id", "strategy_id", name="uq_user_strategy_purchase"),
    )
    op.create_index("ix_user_strategy_purchases_user", "user_strategy_purchases", ["user_id"])
    op.create_table(
        "user_strategy_installations",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("strategy_id", sa.String(120), nullable=False),
        sa.Column("installed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["strategy_id"], ["strategy_listings.strategy_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "strategy_id"),
    )


def downgrade() -> None:
    op.drop_table("user_strategy_installations")
    op.drop_index("ix_user_strategy_purchases_user", table_name="user_strategy_purchases")
    op.drop_table("user_strategy_purchases")
    op.drop_table("strategy_listings")
