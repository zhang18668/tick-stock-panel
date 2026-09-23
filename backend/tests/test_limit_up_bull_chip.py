from __future__ import annotations

from datetime import date, timedelta

import polars as pl

from app.backtest.matrix import build_market_data_matrix
from tests.strategy_plugin_test_support import load_plugin_module

limit_up_bull_chip = load_plugin_module("limit_up_bull_chip")


def _market(previous_limit_up: bool = True):
    start = date(2024, 1, 2)
    closes = [10 + i * 0.1 for i in range(70)]
    closes[-2] = 15.0
    closes[-1] = 14.25
    rows = []
    for index, close in enumerate(closes):
        rows.append({
            "symbol": "000001.SZ",
            "date": start + timedelta(days=index),
            "open": close,
            "high": close,
            "low": close,
            "close": close,
            "raw_close": close,
            "volume": 500.0 if index == len(closes) - 1 else 1000.0,
            "consecutive_limit_ups": 1 if previous_limit_up and index == len(closes) - 2 else 0,
        })
    return build_market_data_matrix(
        pl.DataFrame(rows),
        field_columns={"raw_close", "consecutive_limit_ups"},
    )


def _params():
    return {
        "decline_min_pct": 4.5,
        "recent_limit_up_days": 9,
        "profit_proxy_min_pct": 0,
        "profit_proxy_max_pct": 100,
        "chip_window": 60,
        "cost_ratio_min": 0.8,
        "volume_ratio_min": 0.4,
        "volume_ratio_max": 0.7,
        "require_ma_alignment": False,
    }


def test_limit_up_bull_chip_matches_image_conditions_without_future_data():
    signals = limit_up_bull_chip.MATRIX_STRATEGY.compute_signals(_market(), _params())
    assert signals.entry[-1, 0] == 1


def test_limit_up_bull_chip_is_in_private_group():
    assert limit_up_bull_chip.META["visibility_group"] == "private"


def test_limit_up_bull_chip_rejects_decline_below_threshold():
    params = _params()
    params["decline_min_pct"] = 5.5
    signals = limit_up_bull_chip.MATRIX_STRATEGY.compute_signals(_market(), params)
    assert signals.entry[-1, 0] == 0


def test_limit_up_bull_chip_requires_a_prior_limit_up():
    signals = limit_up_bull_chip.MATRIX_STRATEGY.compute_signals(
        _market(previous_limit_up=False),
        _params(),
    )
    assert signals.entry[-1, 0] == 0
