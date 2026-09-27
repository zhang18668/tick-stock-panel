"""Add optional strategy listing sale price and label."""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260822_0013"
down_revision: str | None = "20260822_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("strategy_listings", sa.Column("sale_points_price", sa.BigInteger()))
    op.add_column("strategy_listings", sa.Column("sale_label", sa.String(80)))
    op.create_check_constraint(
        "ck_strategy_listing_sale_points_price",
        "strategy_listings",
        "sale_points_price IS NULL OR sale_points_price >= 0",
    )


def downgrade() -> None:
    op.drop_constraint("ck_strategy_listing_sale_points_price", "strategy_listings", type_="check")
    op.drop_column("strategy_listings", "sale_label")
    op.drop_column("strategy_listings", "sale_points_price")
