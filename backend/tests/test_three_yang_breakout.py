from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import polars as pl

from app.backtest.matrix import build_market_data_matrix
from app.strategy.engine import StrategyEngine
from tests.strategy_plugin_test_support import load_plugin_module

three_yang_breakout = load_plugin_module("three_yang_breakout")


def _market(*, symbol: str = "000001.SZ", volume: float = 220.0, third_close: float = 10.72):
    rows = []
    start = date(2024, 1, 2)
    for index in range(36):
        close = 9.2 + index * 0.04
        if 25 <= index <= 27:
            close = 10.10
        open_, high, low, current_volume = close - 0.01, close + 0.08, close - 0.08, 100.0
        if index == 24:
            open_, high, low, close = 10.05, 10.58, 9.40, 10.50
        elif index == 28:
            open_, high, low, close = 10.00, 10.52, 9.60, 10.45
        elif index == 32:
            open_, high, low, close, current_volume = 10.20, 10.80, 9.85, third_close, volume
        rows.append(
            {
                "symbol": symbol,
                "date": start + timedelta(days=index),
                "open": open_,
                "high": high,
                "low": low,
                "close": close,
                "raw_close": close,
                "raw_high": high,
                "volume": current_volume,
                "amount": current_volume * close,
            }
        )
    return build_market_data_matrix(pl.DataFrame(rows), field_columns={"amount"})


def _entry(**kwargs) -> bool:
    market = _market(**kwargs)
    signals = three_yang_breakout.MATRIX_STRATEGY.compute_signals(market, {})
    return bool(signals.entry[32, 0])


def test_matches_three_yang_formula_sequence():
    assert _entry()


def test_yang_three_requires_double_volume_and_five_percent_body():
    assert not _entry(volume=199.9)
    assert not _entry(third_close=10.70)


def test_excludes_beijing_exchange_codes():
    assert not _entry(symbol="920001.BJ")


def test_is_private_and_exposes_optimizer_parameters():
    meta = three_yang_breakout.META
    assert meta["visibility_group"] == "private"
    assert meta["asset_types"] == ["stock"]
    assert {param["id"] for param in meta["params"]} >= {
        "yang1_body_pct",
        "yang12_overlap_pct",
        "yang23_overlap_pct",
        "spacing_min_days",
        "spacing_max_days",
        "yang3_body_pct",
        "yang3_volume_ratio",
    }


def test_builtin_strategy_engine_discovers_three_yang():
    engine = StrategyEngine(
        strategy_dirs=[Path(three_yang_breakout.__file__).resolve().parent]
    )
    strategy = engine.get("three_yang_breakout")
    assert strategy.meta["visibility_group"] == "private"
    assert strategy.execution_backend == "matrix_native"
    assert strategy.matrix_strategy is not None
