from datetime import date, timedelta
from pathlib import Path

import numpy as np
import polars as pl

from app.backtest.matrix import build_market_data_matrix, matrix_feature
from app.strategy.engine import StrategyEngine
from tests.strategy_plugin_test_support import load_plugin_module

strategy_520 = load_plugin_module("strategy_520")


def _market(closes: list[float], *, bearish_index: int = 20):
    rows = []
    for index, close in enumerate(closes):
        open_ = close
        if index == bearish_index:
            open_ = close + 0.8
        rows.append({
            "symbol": "000001.SZ",
            "date": date(2024, 1, 2) + timedelta(days=index),
            "open": open_,
            "high": max(open_, close) + 0.05,
            "low": min(open_, close) - 0.05,
            "close": close,
            "volume": 1000.0,
            "amount": 1000.0 * close,
        })
    return build_market_data_matrix(pl.DataFrame(rows), field_columns={"amount"})


def _setup_closes() -> list[float]:
    # 平稳期后大阴下跌，再由小阴小阳逐步抬高短均线并逼近 MA20。
    return [10.0] * 20 + [9.4, 9.35, 9.38, 9.42, 9.47, 9.52, 9.57, 9.62, 9.67, 9.72, 9.77, 9.82]


def test_520_enters_before_ma5_crosses_ma20_after_bearish_stop_falling():
    market = _market(_setup_closes())
    signals = strategy_520.MATRIX_STRATEGY.compute_signals(market, {})
    entry_rows = signals.entry[:, 0].nonzero()[0]
    assert entry_rows.size > 0
    ma5 = matrix_feature(market, "ma5")[:, 0]
    ma20 = matrix_feature(market, "ma20")[:, 0]
    assert np.all(ma5[entry_rows] <= ma20[entry_rows])


def test_520_requires_recent_big_bearish_and_small_stop_falling_candle():
    closes = _setup_closes()
    no_bearish = strategy_520.MATRIX_STRATEGY.compute_signals(
        _market(closes, bearish_index=-1),
        {},
    )
    assert not no_bearish.entry.any()

    volatile = closes.copy()
    volatile[-1] = closes[-2] * 1.04
    signals = strategy_520.MATRIX_STRATEGY.compute_signals(_market(volatile), {})
    assert signals.entry[-1, 0] == 0


def test_520_exits_when_ma5_first_turns_down_and_exposes_shared_defaults():
    closes = _setup_closes() + [9.76, 9.78, 9.80, 9.78, 9.60, 9.40]
    signals = strategy_520.MATRIX_STRATEGY.compute_signals(_market(closes), {})
    assert signals.exit[:, 0].any()
    assert "strategy_520_ma5_turn_down" in signals.exit_signal_ids
    assert "signal_ma_dead_5_20" in signals.exit_signal_ids

    engine = StrategyEngine(strategy_dirs=[Path(strategy_520.__file__).parent])
    discovered = engine.get("strategy_520")
    assert discovered.execution_backend == "matrix_native"
    assert discovered.meta["visibility_group"] == "douyin"
    assert "抖音主播策略" in discovered.meta["tags"]
    assert discovered.stop_loss == -0.05
    assert discovered.take_profit == 0.10
    assert discovered.max_hold_days == 10
