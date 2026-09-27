"""Publish the double-volume bullish breakout strategy for 100 points."""
from collections.abc import Sequence

from alembic import op

revision: str = "20260822_0015"
down_revision: str | None = "20260822_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        INSERT INTO strategy_listings (
            strategy_id, title, description, points_price, status, published_at, updated_at
        ) VALUES (
            'double_volume_bullish_breakout',
            '倍量阳·缩量破线',
            '连阳爬坡途中出现倍量阳, 以其收盘价为基准; 次一交易日缩量站上基准线时, 于尾盘确认介入, 持仓至炸板或风控条件触发。',
            100,
            'published',
            now(),
            now()
        )
        ON CONFLICT (strategy_id) DO UPDATE SET
            title = EXCLUDED.title,
            description = EXCLUDED.description,
            points_price = EXCLUDED.points_price,
            sale_points_price = NULL,
            sale_label = NULL,
            status = 'published',
            published_at = COALESCE(strategy_listings.published_at, now()),
            updated_at = now()
    """)


def downgrade() -> None:
    op.execute(
        "DELETE FROM strategy_listings "
        "WHERE strategy_id = 'double_volume_bullish_breakout'"
    )
