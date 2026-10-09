from datetime import date

from app.strategy_library.contracts import (
    BacktestPeriod,
    BacktestWindow,
    StrategyLibraryTaskStatus,
)


def test_period_and_task_status_values_are_stable_api_strings():
    assert [item.value for item in BacktestPeriod] == ["3m", "6m", "12m"]
    assert StrategyLibraryTaskStatus.QUEUED.value == "queued"
    assert StrategyLibraryTaskStatus.INTERRUPTED.value == "interrupted"


def test_new_window_starts_without_claiming_data_availability():
    window = BacktestWindow(
        period=BacktestPeriod.THREE_MONTHS,
        requested_start=date(2026, 7, 8),
        requested_end=date(2026, 10, 8),
    )

    assert window.actual_start is None
    assert window.actual_end is None
    assert window.availability == "pending"
    assert window.reason is None
