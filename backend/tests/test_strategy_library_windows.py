from datetime import date

from app.strategy_library.windows import build_rolling_windows
from app.strategy_library.contracts import BacktestPeriod


def test_windows_share_latest_trading_day_and_use_calendar_months():
    windows = build_rolling_windows(date(2026, 10, 8))

    assert [window.period for window in windows] == [
        BacktestPeriod.THREE_MONTHS,
        BacktestPeriod.SIX_MONTHS,
        BacktestPeriod.TWELVE_MONTHS,
    ]
    assert {window.requested_end for window in windows} == {date(2026, 10, 8)}
    assert [window.requested_start for window in windows] == [
        date(2026, 7, 8),
        date(2026, 4, 8),
        date(2025, 10, 8),
    ]


def test_month_end_clamps_to_last_day_of_target_month():
    windows = build_rolling_windows(date(2026, 5, 31))

    assert [window.requested_start for window in windows] == [
        date(2026, 2, 28),
        date(2025, 11, 30),
        date(2025, 5, 31),
    ]
