from __future__ import annotations

from datetime import date, timedelta

import polars as pl

from app.backtest.matrix import build_market_data_matrix
from tests.strategy_plugin_test_support import load_plugin_module

left_peak_volume_retest = load_plugin_module("left_peak_volume_retest")


def _market(*, break_low: bool = False, early_breakout_only: bool = False):
    start = date(2024, 1, 2)
    rows = []
    for index in range(45):
        close = 15.0
        open_ = close
        high = 15.2
        low = 14.8
        volume = 1000.0
        if index == 20:
            high = 20.0
            close = 19.0
            open_ = 18.5
        if index == 25 and early_breakout_only:
            open_, high, low, close, volume = 19.5, 20.8, 19.4, 20.5, 2500.0
        if index == 35 and not early_breakout_only:
            open_, high, low, close, volume = 19.5, 20.8, 19.4, 20.5, 2500.0
        if index == 36:
            open_, high, low, close, volume = 20.4, 20.6, 19.2 if break_low else 20.2, 20.45, 500.0
        rows.append({
            "symbol": "000001.SZ",
            "date": start + timedelta(days=index),
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
            "amount": volume * close,
        })
    return build_market_data_matrix(pl.DataFrame(rows), field_columns={"amount"})


def test_left_peak_volume_retest_matches_extracted_formula():
    signals = left_peak_volume_retest.MATRIX_STRATEGY.compute_signals(_market(), {})
    assert signals.entry[36, 0] == 1


def test_left_peak_volume_retest_rejects_broken_signal_low():
    signals = left_peak_volume_retest.MATRIX_STRATEGY.compute_signals(
        _market(break_low=True),
        {},
    )
    assert signals.entry[36, 0] == 0


def test_left_peak_is_not_used_before_right_side_confirmation():
    signals = left_peak_volume_retest.MATRIX_STRATEGY.compute_signals(
        _market(early_breakout_only=True),
        {},
    )
    assert not signals.entry.any()


def test_left_peak_volume_retest_is_private():
    assert left_peak_volume_retest.META["visibility_group"] == "private"
