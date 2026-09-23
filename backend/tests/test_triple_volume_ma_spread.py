from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import polars as pl

from app.backtest.matrix import build_market_data_matrix
from app.strategy.engine import StrategyEngine
from tests.strategy_plugin_test_support import load_plugin_module

strategy = load_plugin_module("triple_volume_ma_spread")

BASE_CLOSES = [
    15.0, 14.7812, 14.5625, 14.3438, 14.125, 13.9062, 13.6875, 13.4688,
    13.25, 13.0312, 12.8125, 12.5938, 12.375, 12.1562, 11.9375, 11.7188,
    11.5, 11.2812, 11.0625, 10.8438, 10.625, 10.4062, 10.1875, 9.9688,
    9.75, 9.5312, 9.3125, 9.0938, 8.875, 8.6562, 8.4375, 8.2188, 8.0,
    8.7398, 8.8448, 8.9558, 9.1331, 9.7178, 10.6297, 12.186, 13.8406,
    16.2749, 17.9588, 19.1707, 22.0958,
]


def _market(closes: list[float], *, setup_volume: float = 300.0, entry_volume: float = 200.0):
    volumes = [100.0] * len(closes)
    volumes[-2] = setup_volume
    volumes[-1] = entry_volume
    rows = []
    for index, (close, volume) in enumerate(zip(closes, volumes, strict=True)):
        rows.append({
            "symbol": "000001.SZ",
            "date": date(2024, 1, 2) + timedelta(days=index),
            "open": close - 0.05,
            "high": close + 0.1,
            "low": close - 0.1,
            "close": close,
            "volume": volume,
            "amount": close * volume,
            "turnover_rate": 1.0,
        })
    return build_market_data_matrix(
        pl.DataFrame(rows),
        field_columns={"amount", "turnover_rate"},
    )


def test_entry_requires_triple_volume_next_day_breakout_recent_crosses_and_loose_spread():
    signals = strategy.MATRIX_STRATEGY.compute_signals(_market(BASE_CLOSES), {})

    assert signals.entry[-1, 0] == 1
    assert signals.entry.sum() == 1


def test_equal_setup_and_confirmation_volume_is_not_shrinking():
    signals = strategy.MATRIX_STRATEGY.compute_signals(
        _market(BASE_CLOSES, setup_volume=300.0, entry_volume=300.0),
        {},
    )

    assert signals.entry[-1, 0] == 0


def test_crosses_older_than_configured_window_are_rejected():
    closes = [*BASE_CLOSES, 23.0, 24.0, 25.0, 26.0, 27.0, 28.0]
    signals = strategy.MATRIX_STRATEGY.compute_signals(
        _market(closes),
        {"cross_lookback_days": 5},
    )

    assert signals.entry[-1, 0] == 0


def test_close_breaking_ma10_generates_exit_signal():
    closes = [*BASE_CLOSES, 10.0]
    signals = strategy.MATRIX_STRATEGY.compute_signals(_market(closes), {})

    assert signals.exit[-1, 0] == 1
    assert signals.exit_signal_code[-1, 0] == 0


def test_strategy_has_complete_execution_rules_and_is_discoverable():
    engine = StrategyEngine(
        strategy_dirs=[Path(strategy.__file__).resolve().parent],
    )
    discovered = engine.get("triple_volume_ma_spread")

    assert discovered.matrix_strategy is not None
    assert discovered.meta["visibility_group"] == "diya"
    assert discovered.stop_loss == -0.06
    assert discovered.take_profit == 0.12
    assert discovered.max_hold_days == 10
    assert discovered.exit_signals == [
        "triple_volume_ma10_breakdown",
        "triple_volume_ma5_ma10_dead",
    ]
