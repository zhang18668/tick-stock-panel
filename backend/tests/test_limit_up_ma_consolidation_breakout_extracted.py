from __future__ import annotations

from datetime import date, timedelta

import polars as pl

from app.backtest.matrix import build_market_data_matrix
from tests.strategy_plugin_test_support import load_plugin_module

strategy = load_plugin_module("limit_up_ma_consolidation_breakout_extracted")


def _market(*, break_band: bool = False, breakout_day: int = 35):
    rows = []
    for index in range(40):
        open_, high, low, close = 10.0, 10.1, 9.9, 10.0
        if index == 25:
            open_, high, low, close = 10.0, 11.0, 9.9, 11.0
        elif index == 26:
            open_, high, low, close = 11.05, 11.2, 10.9, 11.0
        elif 27 <= index < breakout_day:
            open_, high, low, close = 11.05, 11.2, 10.95, 11.05
            if break_band and index == 30:
                close = 10.9
        elif index == breakout_day:
            open_, high, low, close = 11.1, 11.5, 10.9, 11.45
        rows.append({
            "symbol": "000001.SZ",
            "date": date(2024, 1, 2) + timedelta(days=index),
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "raw_close": close,
            "raw_high": high,
            "signal_limit_up": index == 25,
            "volume": 1000.0,
            "amount": 1000.0 * close,
        })
    return build_market_data_matrix(
        pl.DataFrame(rows),
        field_columns={"amount", "raw_close", "raw_high"},
    )


def test_extracted_formula_breaks_out_after_eight_day_range():
    signals = strategy.MATRIX_STRATEGY.compute_signals(_market(), {})
    assert signals.entry[35, 0] == 1


def test_extracted_formula_rejects_short_or_broken_range():
    early = strategy.MATRIX_STRATEGY.compute_signals(_market(breakout_day=34), {})
    broken = strategy.MATRIX_STRATEGY.compute_signals(_market(break_band=True), {})
    assert early.entry[34, 0] == 0
    assert broken.entry[35, 0] == 0


def test_extracted_strategy_has_requested_private_name():
    assert strategy.META["name"] == "涨停穿线断板整理突破"
    assert strategy.META["visibility_group"] == "private"
