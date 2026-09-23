from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import polars as pl

from app.backtest.matrix import build_market_data_matrix
from app.strategy.engine import StrategyEngine
from tests.strategy_plugin_test_support import load_plugin_module

strategy = load_plugin_module("triple_volume_pullback_double_bull")


def _signals(
    overrides: dict[int, tuple[float, float, float, float]],
    params: dict | None = None,
    *,
    symbol: str = "000001.SZ",
    name: str = "平安银行",
):
    rows = []
    start = date(2024, 1, 2)
    for index in range(30):
        open_, low, close, volume = overrides.get(index, (10.0, 9.9, 10.0, 100.0))
        rows.append({
            "symbol": symbol,
            "name": name,
            "date": start + timedelta(days=index),
            "open": open_,
            "high": max(open_, close) + 0.1,
            "low": low,
            "close": close,
            "volume": volume,
            "signal_limit_up": index == 20 and close == 11.0,
            "amount": volume * close,
            "turnover_rate": 1.0,
        })
    market = build_market_data_matrix(pl.DataFrame(rows), field_columns={"amount", "turnover_rate"})
    return strategy.MATRIX_STRATEGY.compute_signals(market, params or {})


def _valid_pattern() -> dict[int, tuple[float, float, float, float]]:
    return {
        20: (10.0, 9.9, 11.0, 300.0),
        21: (10.8, 10.4, 10.6, 220.0),
        22: (10.5, 10.05, 10.3, 160.0),
        23: (10.2, 10.1, 10.35, 140.0),
        24: (10.3, 10.2, 10.7, 120.0),
    }


def test_second_shrinking_bull_breaking_ma5_is_entry():
    signals = _signals(_valid_pattern())

    assert signals.entry[24, 0] == 1
    assert signals.entry.sum() == 1


def test_requires_two_declining_price_and_volume_bars():
    pattern = _valid_pattern()
    pattern[22] = (10.5, 10.05, 10.65, 230.0)

    assert not _signals(pattern).entry.any()


def test_second_bull_must_remain_shrinking():
    pattern = _valid_pattern()
    pattern[24] = (10.3, 10.2, 10.7, 150.0)

    assert not _signals(pattern).entry.any()


def test_setup_must_be_a_closed_limit_up():
    pattern = _valid_pattern()
    pattern[20] = (10.0, 9.9, 10.99, 300.0)

    assert not _signals(pattern).entry.any()


def test_excludes_chinext_star_market_and_st():
    pattern = _valid_pattern()

    assert not _signals(pattern, symbol="300001.SZ", name="创业板股票").entry.any()
    assert not _signals(pattern, symbol="688001.SH", name="科创板股票").entry.any()
    assert not _signals(pattern, symbol="000001.SZ", name="ST测试").entry.any()


def test_strategy_is_wuyai_private_builtin_and_discoverable():
    engine = StrategyEngine(strategy_dirs=[Path(strategy.__file__).resolve().parent])
    discovered = engine.get("triple_volume_pullback_double_bull")

    assert discovered.meta["visibility_group"] == "private"
    assert "无涯" in discovered.meta["tags"]
    assert discovered.execution_backend == "matrix_native"
    assert discovered.matrix_strategy is not None
