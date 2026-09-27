"""Remove the unsupported broken-limit exit claim from the store listing."""
from collections.abc import Sequence

from alembic import op

revision: str = "20260822_0016"
down_revision: str | None = "20260822_0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        UPDATE strategy_listings
        SET description = '连阳爬坡途中出现倍量阳, 以其收盘价为基准; 次一交易日缩量站上基准线时, 于尾盘确认介入, 持仓退出由止损、移动止盈和最大持有期控制。',
            updated_at = now()
        WHERE strategy_id = 'double_volume_bullish_breakout'
    """)


def downgrade() -> None:
    op.execute("""
        UPDATE strategy_listings
        SET description = '连阳爬坡途中出现倍量阳, 以其收盘价为基准; 次一交易日缩量站上基准线时, 于尾盘确认介入, 持仓至炸板或风控条件触发。',
            updated_at = now()
        WHERE strategy_id = 'double_volume_bullish_breakout'
    """)
