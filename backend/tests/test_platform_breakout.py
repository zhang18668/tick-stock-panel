from __future__ import annotations

from datetime import date, timedelta

import polars as pl

from app.backtest.matrix import build_market_data_matrix
from tests.strategy_plugin_test_support import load_plugin_module

platform_breakout = load_plugin_module("platform_breakout")


def _market(*, breakout_volume=180.0, breakout_body_pct=6.0, pullback_low=10.15, pullback_close=10.50):
    rows = []
    for index in range(76):
        open_, high, low, close, volume = 10.0, 10.08, 9.92, 10.0, 100.0
        if index == 74:
            open_ = 10.0
            close = open_ * (1.0 + breakout_body_pct / 100.0)
            high, low, volume = close + 0.04, 9.95, breakout_volume
        elif index == 75:
            open_, high, low, close, volume = 10.55, 10.58, pullback_low, pullback_close, 110.0
        rows.append({
            "symbol": "000001.SZ",
            "date": date(2024, 1, 2) + timedelta(days=index),
            "open": open_, "high": high, "low": low, "close": close,
            "volume": volume, "amount": volume * close,
        })
    return build_market_data_matrix(pl.DataFrame(rows), field_columns={"amount"})


def _entry(**kwargs) -> bool:
    signals = platform_breakout.MATRIX_STRATEGY.compute_signals(_market(**kwargs), {})
    return bool(signals.entry[75, 0])


def test_platform_breakout_matches_screenshot_sequence():
    assert _entry()


def test_requires_five_percent_body_and_expanded_volume():
    assert not _entry(breakout_body_pct=4.9)
    assert not _entry(breakout_volume=149.9)


def test_requires_next_day_ma5_support_to_hold():
    assert not _entry(pullback_low=10.55, pullback_close=10.56)
    assert not _entry(pullback_low=9.8, pullback_close=9.9)


def test_is_private_and_optimizer_ready():
    meta = platform_breakout.META
    assert meta["name"] == "平台突破"
    assert meta["visibility_group"] == "private"
    assert {param["id"] for param in meta["params"]} >= {
        "platform_days", "ma_cluster_max_pct", "ma60_angle_max_deg",
        "breakout_body_min_pct", "breakout_volume_ratio",
        "pullback_body_max_pct", "ma5_support_tolerance_pct",
    }
