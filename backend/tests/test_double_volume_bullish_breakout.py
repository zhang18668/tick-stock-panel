from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import polars as pl

from app.backtest.matrix import build_market_data_matrix
from app.strategy.engine import StrategyEngine
from tests.strategy_plugin_test_support import load_plugin_module

double_volume_bullish_breakout = load_plugin_module("double_volume_bullish_breakout")


def _signals(overrides: dict[int, tuple[float, float, float]], params: dict | None = None):
    rows = []
    start = date(2024, 1, 2)
    for index in range(16):
        open_, close, volume = overrides.get(index, (10.0, 10.0, 100.0))
        rows.append({
            "symbol": "000001.SZ",
            "date": start + timedelta(days=index),
            "open": open_,
            "high": max(open_, close) + 0.1,
            "low": min(open_, close) - 0.1,
            "close": close,
            "volume": volume,
            "amount": volume * close,
            "turnover_rate": 1.0,
        })
    market = build_market_data_matrix(
        pl.DataFrame(rows),
        field_columns={"amount", "turnover_rate"},
    )
    return double_volume_bullish_breakout.MATRIX_STRATEGY.compute_signals(market, params or {})


def _valid_pattern(*, breakout_volume: float = 150.0):
    return {
        5: (10.0, 10.1, 100.0),
        6: (10.1, 10.2, 110.0),
        7: (10.2, 10.3, 120.0),
        8: (10.3, 10.6, 240.0),
        9: (10.55, 10.7, breakout_volume),
    }


def test_next_day_lower_volume_breakout_is_entry():
    signals = _signals(_valid_pattern())

    assert signals.entry[9, 0] == 1
    assert signals.entry.sum() == 1


def test_entry_requires_next_trading_day_and_strictly_lower_volume():
    late = _valid_pattern()
    late[9] = (10.5, 10.5, 100.0)
    late[10] = (10.6, 10.8, 100.0)

    assert not _signals(late).entry.any()
    assert not _signals(_valid_pattern(breakout_volume=240.0)).entry.any()


def test_setup_requires_consecutive_rising_bullish_climb_and_double_volume():
    interrupted = _valid_pattern()
    interrupted[6] = (10.25, 10.2, 110.0)
    insufficient_volume = _valid_pattern()
    insufficient_volume[8] = (10.3, 10.6, 239.9)

    assert not _signals(interrupted).entry.any()
    assert not _signals(insufficient_volume).entry.any()


def test_strategy_has_no_intrinsic_exit_signal():
    signals = _signals(_valid_pattern())

    assert not signals.exit.any()
    assert signals.exit_signal_ids == ()


def test_metadata_is_paid_group_and_uses_close_fill():
    engine = StrategyEngine(
        strategy_dirs=[Path(double_volume_bullish_breakout.__file__).resolve().parent]
    )
    strategy = engine.get("double_volume_bullish_breakout")

    assert strategy.meta["name"] == "倍量阳·缩量破线"
    assert strategy.meta["visibility_group"] == "tianya"
    assert "天涯" in strategy.meta["tags"]
    assert strategy.meta["execution_entry_fill"] == "close_t"
    assert strategy.entry_signals == ["double_volume_bullish_breakout"]
    assert strategy.exit_signals == []
    assert strategy.execution_backend == "matrix_native"
    assert "signal_broken_limit_up" not in strategy.matrix_strategy.required_fields()
