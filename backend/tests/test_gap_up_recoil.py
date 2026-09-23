from __future__ import annotations

from datetime import date, timedelta

import polars as pl

from app.backtest.matrix import build_market_data_matrix
from tests.strategy_plugin_test_support import load_plugin_module

gap_up_recoil = load_plugin_module("gap_up_recoil")


def _market(
    *,
    break_limit_low: bool = False,
    gap_after_days: int = 3,
    leave_full_gap: bool = True,
):
    rows = []
    start = date(2024, 1, 2)
    gap_index = 65 + gap_after_days
    for index in range(75):
        close = 9.0 + min(index, 64) * (1.0 / 64.0)
        open_ = close - 0.03
        high, low = close + 0.08, close - 0.08
        volume = 1000.0
        signal_limit_up = False
        if index == 65:
            open_, high, low, close, volume = 10.4, 11.0, 10.35, 11.0, 2200.0
            signal_limit_up = True
        elif 65 < index < gap_index:
            open_, high, low, close, volume = 10.8, 10.9, 10.2, 10.7, 1000.0
            if break_limit_low and index == 66:
                close = 10.3
        elif index == gap_index:
            gap_low = 11.01 if leave_full_gap else 10.9
            open_, high, low, close, volume = 11.05, 11.4, gap_low, 11.3, 1800.0
        rows.append({
            "symbol": "000001.SZ",
            "date": start + timedelta(days=index),
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
            "amount": volume * close,
            "signal_limit_up": signal_limit_up,
        })
    return build_market_data_matrix(pl.DataFrame(rows), field_columns={"amount"})


def test_gap_up_recoil_matches_extracted_rules():
    signals = gap_up_recoil.MATRIX_STRATEGY.compute_signals(_market(), {})
    assert signals.entry[68, 0] == 1
    assert signals.entry[:68, 0].sum() == 0


def test_gap_up_recoil_rejects_close_below_limit_up_low():
    signals = gap_up_recoil.MATRIX_STRATEGY.compute_signals(
        _market(break_limit_low=True),
        {},
    )
    assert not signals.entry.any()


def test_gap_up_recoil_expires_after_ten_trading_bars():
    signals = gap_up_recoil.MATRIX_STRATEGY.compute_signals(
        _market(gap_after_days=11),
        {},
    )
    assert not signals.entry.any()


def test_gap_up_recoil_requires_a_full_unfilled_gap():
    signals = gap_up_recoil.MATRIX_STRATEGY.compute_signals(
        _market(leave_full_gap=False),
        {},
    )
    assert not signals.entry.any()


def test_gap_up_recoil_is_private_and_optimizer_ready():
    assert gap_up_recoil.META["visibility_group"] == "private"
    assert gap_up_recoil.META["asset_types"] == ["stock"]
    assert len(gap_up_recoil.META["params"]) == 8
