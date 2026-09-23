from __future__ import annotations

from datetime import date, timedelta

import polars as pl

from app.backtest.matrix import build_market_data_matrix
from tests.strategy_plugin_test_support import load_plugin_module

limit_up_breakout_retest = load_plugin_module("limit_up_breakout_retest")


def _market(
    *,
    third_day_high: float = 11.9,
    retest_close: float = 11.05,
    retest_high: float = 11.4,
    delayed_retest: bool = False,
    waiting_close: float = 11.4,
    waiting_high: float = 12.1,
    post_entry_close: float = 10.9,
):
    rows = []
    start = date(2024, 1, 2)
    for index in range(30):
        open_ = close = 10.0
        high, low = 10.4, 9.6
        is_limit_up = False
        if index == 20:
            open_, high, low, close = 10.5, 11.0, 10.5, 11.0
            is_limit_up = True
        elif index == 21:
            open_, high, low, close = 11.2, 11.5, 11.1, 11.3
        elif index == 22:
            open_, high, low, close = 11.3, 11.7, 11.2, 11.4
        elif index == 23:
            open_, high, low, close = 11.4, third_day_high, 11.2, 11.5
        elif index == 24:
            if delayed_retest:
                open_, high, low, close = 11.3, waiting_high, 11.1, waiting_close
            else:
                open_, high, low, close = 11.3, retest_high, 10.9, retest_close
        elif index == 25 and delayed_retest:
            open_, high, low, close = 11.2, 11.3, 10.9, 11.05
        elif index == 25:
            open_, high, low, close = 11.0, 11.1, 10.8, post_entry_close
        rows.append({
            "symbol": "000001.SZ",
            "date": start + timedelta(days=index),
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": 1000.0,
            "consecutive_limit_ups": 1 if is_limit_up else 0,
            "amount": close * 1000.0,
        })
    return build_market_data_matrix(
        pl.DataFrame(rows),
        field_columns={"consecutive_limit_ups", "amount"},
    )


def _consecutive_limit_market():
    rows = []
    start = date(2024, 1, 2)
    for index in range(30):
        open_ = close = 10.0
        high, low = 10.4, 9.6
        boards = 0
        if index == 20:
            open_, high, low, close, boards = 10.5, 11.0, 10.5, 11.0, 1
        elif index == 21:
            open_, high, low, close, boards = 13.0, 13.2, 13.0, 13.2, 2
        elif index == 22:
            open_, high, low, close = 13.2, 13.5, 13.1, 13.3
        elif index == 23:
            open_, high, low, close = 13.3, 13.6, 13.2, 13.4
        elif index == 24:
            open_, high, low, close = 13.4, 13.7, 13.3, 13.5
        elif index == 25:
            open_, high, low, close = 13.4, 13.5, 13.1, 13.25
        rows.append({
            "symbol": "300632.SZ",
            "date": start + timedelta(days=index),
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": 1000.0,
            "consecutive_limit_ups": boards,
            "amount": close * 1000.0,
        })
    return build_market_data_matrix(
        pl.DataFrame(rows),
        field_columns={"consecutive_limit_ups", "amount"},
    )


def test_retest_enters_at_close_after_three_day_confirmation():
    signals = limit_up_breakout_retest.MATRIX_STRATEGY.compute_signals(_market(), {})
    assert signals.entry[24, 0] == 1
    assert signals.entry[:24, 0].sum() == 0


def test_confirmation_uses_high_price_for_ten_percent_ceiling():
    signals = limit_up_breakout_retest.MATRIX_STRATEGY.compute_signals(
        _market(third_day_high=12.1),
        {},
    )
    assert not signals.entry.any()


def test_retest_must_close_above_limit_up_close():
    signals = limit_up_breakout_retest.MATRIX_STRATEGY.compute_signals(
        _market(retest_close=11.0),
        {},
    )
    assert not signals.entry.any()


def test_buy_day_must_stay_below_ten_percent_high_ceiling():
    signals = limit_up_breakout_retest.MATRIX_STRATEGY.compute_signals(
        _market(retest_high=12.1),
        {},
    )
    assert not signals.entry.any()


def test_setup_expires_when_waiting_day_breaks_continuation_rules():
    signals = limit_up_breakout_retest.MATRIX_STRATEGY.compute_signals(
        _market(delayed_retest=True),
        {},
    )
    assert not signals.entry.any()


def test_setup_expires_when_waiting_day_does_not_close_above_limit_price():
    signals = limit_up_breakout_retest.MATRIX_STRATEGY.compute_signals(
        _market(delayed_retest=True, waiting_close=11.0, waiting_high=11.5),
        {},
    )
    assert not signals.entry.any()


def test_consecutive_limit_up_resets_to_latest_limit_price():
    signals = limit_up_breakout_retest.MATRIX_STRATEGY.compute_signals(
        _consecutive_limit_market(),
        {},
    )
    assert signals.entry[25, 0] == 1


def test_close_below_limit_up_price_emits_exit_signal():
    signals = limit_up_breakout_retest.MATRIX_STRATEGY.compute_signals(_market(), {})
    assert signals.exit[24, 0] == 0
    assert signals.exit[25, 0] == 1


def test_limit_price_stop_can_be_disabled():
    signals = limit_up_breakout_retest.MATRIX_STRATEGY.compute_signals(
        _market(),
        {"use_limit_price_stop": False},
    )
    assert not signals.exit.any()


def test_close_equal_to_limit_up_price_does_not_stop():
    signals = limit_up_breakout_retest.MATRIX_STRATEGY.compute_signals(
        _market(post_entry_close=11.0),
        {},
    )
    assert signals.exit[25, 0] == 0


def test_breakout_requires_configured_horizontal_range():
    signals = limit_up_breakout_retest.MATRIX_STRATEGY.compute_signals(
        _market(),
        {"use_range_filter": True, "range_max_pct": 5.0},
    )
    assert not signals.entry.any()


def test_horizontal_range_filter_is_disabled_by_default():
    signals = limit_up_breakout_retest.MATRIX_STRATEGY.compute_signals(
        _market(),
        {"range_max_pct": 5.0},
    )
    assert signals.entry[24, 0] == 1


def test_high_ceiling_filter_can_be_disabled():
    signals = limit_up_breakout_retest.MATRIX_STRATEGY.compute_signals(
        _market(retest_high=12.1),
        {"use_high_ceiling_filter": False},
    )
    assert signals.entry[24, 0] == 1


def test_strategy_is_private_and_stock_only():
    assert limit_up_breakout_retest.META["visibility_group"] == "private"
    assert limit_up_breakout_retest.META["asset_types"] == ["stock"]
