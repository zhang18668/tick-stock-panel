from datetime import date

from app.user_system.admin_api import _daily_counts, _return_ratio


def test_return_ratio_prefers_backtest_stats_contract() -> None:
    assert _return_ratio({"stats": {"total_return": 0.125}}) == 0.125


def test_return_ratio_supports_existing_return_field() -> None:
    assert _return_ratio({"stats": {"return": 0.1}}) == 0.1


def test_return_ratio_rejects_missing_and_boolean_values() -> None:
    assert _return_ratio({"stats": {}}) is None
    assert _return_ratio({"stats": {"return": True}}) is None


def test_daily_counts_fills_missing_calendar_days() -> None:
    assert _daily_counts([(date(2026, 8, 10), 2), (date(2026, 8, 12), 1)], date(2026, 8, 10), 3) == {
        "2026-08-10": 2,
        "2026-08-11": 0,
        "2026-08-12": 1,
    }
