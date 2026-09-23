from datetime import date, timedelta

import polars as pl

from app.backtest.matrix import build_market_data_matrix
from tests.strategy_plugin_test_support import load_plugin_module

strategy_2560 = load_plugin_module("strategy_2560")


def _market(*, rising=True, volume_cross=True, break_price=True):
    rows = []
    for index in range(80):
        base = 10.0 + (index * 0.01 if rising else 0.0)
        volume = 100.0
        if index >= 77 and volume_cross:
            volume = 300.0
        close = base
        if 77 <= index < 79 and break_price:
            close = base - 0.20
        if index == 79 and break_price:
            close = base + 0.35
        rows.append({
            "symbol": "000001.SZ",
            "date": date(2024, 1, 2) + timedelta(days=index),
            "open": base,
            "high": max(base, close) + 0.03,
            "low": min(base, close) - 0.03,
            "close": close,
            "volume": volume,
            "amount": volume * close,
        })
    return build_market_data_matrix(pl.DataFrame(rows), field_columns={"amount"})


def _last_entry(**kwargs) -> bool:
    signals = strategy_2560.MATRIX_STRATEGY.compute_signals(_market(**kwargs), {})
    return bool(signals.entry[-1, 0])


def test_2560_requires_rising_ma25_and_price_volume_confirmation():
    assert _last_entry()
    assert not _last_entry(rising=False)
    assert not _last_entry(volume_cross=False)
    assert not _last_entry(break_price=False)


def test_2560_is_private_and_optimizer_ready():
    meta = strategy_2560.META
    assert meta["visibility_group"] == "private"
    assert meta["name"] == "2560战法"
    assert {param["id"] for param in meta["params"]} >= {
        "trend_slope_days",
        "cross_sync_days",
        "setup_lookback_days",
        "pullback_tolerance_pct",
        "shrink_volume_ratio",
    }
