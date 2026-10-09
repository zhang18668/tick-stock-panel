from __future__ import annotations

import calendar
from datetime import date

from app.strategy_library.contracts import BacktestPeriod, BacktestWindow


def _subtract_calendar_months(day: date, months: int) -> date:
    month_index = day.year * 12 + day.month - 1 - months
    year, zero_based_month = divmod(month_index, 12)
    month = zero_based_month + 1
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(day.day, last_day))


def build_rolling_windows(latest_trading_day: date) -> list[BacktestWindow]:
    """Build calendar-month windows sharing the latest available trading day."""
    return [
        BacktestWindow(
            period=period,
            requested_start=_subtract_calendar_months(latest_trading_day, period.months),
            requested_end=latest_trading_day,
        )
        for period in BacktestPeriod
    ]
