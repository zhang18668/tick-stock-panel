from datetime import date, timedelta

import polars as pl
import pytest

from app.backtest.matrix import build_market_data_matrix
from app.strategy.engine import StrategyEngine
from tests.strategy_plugin_test_support import PLUGIN_DIR

STRATEGY_PATH = (
    PLUGIN_DIR
    / "limit_up_double_volume_bearish.py"
)


def test_limit_up_double_volume_bearish_is_in_private_group():
    strategy = StrategyEngine._load_file(STRATEGY_PATH)
    assert strategy.meta["visibility_group"] == "private"


def _entry_for(
    *,
    pattern_volume: float = 250.0,
    pattern_open: float = 11.5,
    pattern_high: float | None = None,
    pattern_low: float | None = None,
    pattern_close: float = 10.9,
    current_close: float = 11.6,
    intermediate_close: float = 11.1,
    previous_raw_low: float = 10.5,
    limit_up_close: float = 11.0,
    first_board: bool = True,
    recent_other_limit_up: bool = False,
    prior_20d_high: float | None = None,
    extra_days_after_pattern: int = 1,
    later_limit_up: bool = False,
    current_limit_up: bool = False,
    post_current_close: float | None = None,
    include_intermediate_day: bool = True,
    params: dict | None = None,
) -> tuple[bool, bool]:
    start = date(2026, 1, 5)
    warmup_closes = [8.0 + offset * 0.09 for offset in range(20)]
    values = [
        (close, close, close, close, close, close, 80.0, 800.0, 1.0, False)
        for close in warmup_closes
    ]
    if prior_20d_high is not None:
        peak_index = len(values) // 2
        recent = values[peak_index]
        values[peak_index] = (recent[0], prior_20d_high, *recent[2:])
    setup_day_index = len(values) + 3
    values.extend([
        (9.8, 10.0, 9.7, 9.9, 9.9, 9.7, 80.0, 800.0, 1.0, recent_other_limit_up),
        (10.0, 10.0, 9.8, 10.0, 10.0, 9.8, 90.0, 900.0, 1.0, not first_board),
        (10.5, limit_up_close, previous_raw_low, limit_up_close, limit_up_close, previous_raw_low, 100.0, 1100.0, 2.0, True),
        (
            pattern_open,
            pattern_high if pattern_high is not None else pattern_open,
            pattern_low if pattern_low is not None else pattern_close,
            pattern_close,
            pattern_close,
            pattern_low if pattern_low is not None else pattern_close,
            pattern_volume,
            1200.0,
            3.0,
            False,
        ),
    ])
    if include_intermediate_day:
        values.append(
            (11.0, max(11.2, intermediate_close), 10.8, intermediate_close, intermediate_close, 10.8, 120.0, 1300.0, 2.5, later_limit_up)
        )
    values.extend(
        (11.1, 11.4, 10.9, 11.3, 11.3, 10.9, 120.0, 1300.0, 2.5, False)
        for _ in range(extra_days_after_pattern)
    )
    values.append(
        (11.2, max(11.4, current_close), 11.0, current_close, current_close, 11.0, 130.0, 1400.0, 2.5, current_limit_up)
    )
    if post_current_close is not None:
        values.append(
            (
                11.2,
                max(11.4, post_current_close),
                11.0,
                post_current_close,
                post_current_close,
                11.0,
                130.0,
                1400.0,
                2.5,
                False,
            )
        )
    rows = [
        {
            "symbol": "000001.SZ",
            "date": start + timedelta(days=offset),
            "open": value[0],
            "high": value[1],
            "low": value[2],
            "close": value[3],
            "raw_close": value[4],
            "raw_low": value[5],
            "volume": value[6],
            "amount": value[7],
            "turnover_rate": value[8],
            "signal_limit_up": value[9],
        }
        for offset, value in enumerate(values)
    ]
    market = build_market_data_matrix(
        pl.DataFrame(rows),
        field_columns={"amount", "raw_close", "raw_low", "turnover_rate"},
    )
    strategy = StrategyEngine._load_file(STRATEGY_PATH)
    signals = strategy.matrix_strategy.compute_signals(market, params or {})
    return bool(signals.entry[setup_day_index, 0]), bool(signals.entry[-1, 0])


@pytest.mark.parametrize("pattern_volume", [200.0, 400.0])
def test_matches_volume_ratio_boundaries(pattern_volume: float):
    setup_day_entry, current_entry = _entry_for(pattern_volume=pattern_volume)
    assert not setup_day_entry
    assert current_entry


@pytest.mark.parametrize(
    "overrides",
    [
        {"pattern_volume": 199.9},
        {"pattern_volume": 400.1},
        {"pattern_open": 11.3, "pattern_close": 10.95},
        {"pattern_high": 11.62},
        {"pattern_low": 10.78},
        {"prior_20d_high": 11.51},
        {"pattern_close": 11.2},
        {"pattern_close": 11.1},
        {"pattern_close": 11.18},
        {"first_board": False},
        {
            "limit_up_close": 12.0,
            "pattern_open": 12.5,
            "pattern_close": 12.0,
            "intermediate_close": 12.1,
            "current_close": 12.6,
        },
        {"current_close": 11.19},
    ],
)
def test_rejects_when_any_required_condition_fails(overrides: dict):
    assert not _entry_for(**overrides)[1]


def test_bearish_body_threshold_is_configurable():
    assert _entry_for(
        pattern_open=11.3,
        pattern_close=10.99,
        params={"bearish_body_min_pct": 2.0, "gap_up_min_pct": 2.0},
    )[1]


def test_gap_up_threshold_is_configurable():
    assert _entry_for(
        pattern_open=11.3,
        pattern_close=10.95,
        params={"gap_up_min_pct": 2.0, "bearish_body_min_pct": 3.0},
    )[1]


def test_limit_up_must_remain_inside_latest_ten_trading_days():
    assert _entry_for(extra_days_after_pattern=7)[1]
    assert not _entry_for(extra_days_after_pattern=8)[1]


def test_third_day_limit_up_recovery_invalidates_later_buy_points():
    assert not _entry_for(later_limit_up=True, intermediate_close=11.5)[1]


def test_an_earlier_limit_up_inside_ten_days_is_allowed():
    assert _entry_for(recent_other_limit_up=True)[1]


def test_intermediate_candle_shape_is_not_restricted():
    assert _entry_for(intermediate_close=10.49)[1]


def test_accepts_close_equal_to_bearish_day_open():
    assert _entry_for(current_close=11.5)[1]


def test_open_at_high_tolerance_is_configurable():
    assert _entry_for(
        pattern_high=11.62,
        params={"open_high_tolerance_pct": 2.0},
    )[1]


def test_recent_open_high_filter_is_configurable():
    assert _entry_for(
        prior_20d_high=11.51,
        params={"use_recent_high_filter": False},
    )[1]


def test_recent_open_high_lookback_is_configurable():
    assert _entry_for(
        prior_20d_high=11.51,
        params={"recent_high_days": 5},
    )[1]


def test_uses_twenty_percent_profit_or_ten_day_exit_defaults():
    strategy = StrategyEngine._load_file(STRATEGY_PATH)
    assert strategy.stop_loss is None
    assert strategy.take_profit == pytest.approx(0.20)
    assert strategy.trailing_take_profit_activate is None
    assert strategy.trailing_take_profit_drawdown is None
    assert strategy.max_hold_days == 10


def test_can_select_first_day_after_bearish_pattern():
    assert _entry_for(include_intermediate_day=False, extra_days_after_pattern=0)[1]


def test_bearish_body_defaults_to_at_least_five_percent():
    assert not _entry_for(pattern_open=11.5, pattern_close=10.93)[1]


def test_lower_shadow_threshold_is_configurable():
    assert _entry_for(
        pattern_low=10.78,
        params={"lower_shadow_max_pct": 2.0},
    )[1]


def test_does_not_require_continuous_small_candles():
    assert _entry_for(intermediate_close=10.5)[1]


def test_selection_day_defaults_to_full_bearish_body_recovery():
    assert _entry_for(current_close=11.5)[1]
    assert not _entry_for(current_close=11.49)[1]


def test_recovery_ratio_is_configurable():
    assert _entry_for(
        current_close=11.21,
        params={"body_hold_min_pct": 50.0},
    )[1]


def test_maximum_pattern_distance_is_configurable():
    assert _entry_for(
        extra_days_after_pattern=8,
        params={"max_days_after_limit_up": 11},
    )[1]


def test_rejects_limit_up_recovery_by_default():
    assert not _entry_for(current_limit_up=True)[1]
    assert _entry_for(
        current_limit_up=True,
        params={"reject_limit_up_recovery": False},
    )[1]


def test_later_limit_up_does_not_invalidate_after_non_limit_first_repair():
    assert _entry_for(
        current_limit_up=True,
        post_current_close=11.5,
        params={"body_hold_min_pct": 50.0},
    )[1]
