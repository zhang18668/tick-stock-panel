from datetime import date, timedelta
from pathlib import Path

import polars as pl

from app.backtest.matrix import build_market_data_matrix
from app.strategy.engine import StrategyEngine
from tests.strategy_plugin_test_support import load_plugin_module

strategy = load_plugin_module("double_line_high_multiple")


def _market(
    *,
    limit_up: bool = True,
    new_high: bool = True,
    close_green: bool = False,
    touch_expma13: bool = True,
):
    rows = []
    closes = [9.0 + index * 0.05 for index in range(12)]
    # 12:涨停但尚未创新高；13:先回调；14:创新高；15:创新高后的阴线回踩。
    closes.extend([9.60, 9.58, 10.50 if new_high else 9.60, 10.30])
    for index, close in enumerate(closes):
        open_ = close - 0.02
        high = close + 0.08
        low = close - 0.08
        signal_limit_up = False
        if index == 12:
            open_, high, low = close - 0.40, close, close - 0.45
            signal_limit_up = limit_up
        elif index == 13:
            open_, high, low = close + 0.05, close + 0.08, close - 0.08
        elif index == 14:
            open_, high, low = close - 0.15, close + 0.05, close - 0.20
        elif index == 15:
            open_ = close - 0.08 if close_green else close + 0.08
            high = max(open_, close) + 0.05
            low = 9.60 if touch_expma13 else 9.80
        rows.append({
            "symbol": "000001.SZ",
            "date": date(2024, 1, 2) + timedelta(days=index),
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": 1000.0,
            "amount": 1000.0 * close,
            "signal_limit_up": signal_limit_up,
        })
    return build_market_data_matrix(pl.DataFrame(rows), field_columns={"amount"})


def test_buys_intraday_pullback_to_expma13_after_limit_up_new_high():
    signals = strategy.MATRIX_STRATEGY.compute_signals(_market(), {})
    assert signals.entry[:, 0].sum() == 1
    assert signals.entry[13, 0] == 0
    assert signals.entry[15, 0] == 1


def test_requires_limit_up_new_high_and_expma13_touch():
    for market in (
        _market(limit_up=False),
        _market(new_high=False),
        _market(touch_expma13=False),
    ):
        assert not strategy.MATRIX_STRATEGY.compute_signals(market, {}).entry.any()


def test_tail_close_may_turn_green_after_intraday_bearish_expma13_touch():
    signals = strategy.MATRIX_STRATEGY.compute_signals(_market(close_green=True), {})
    assert signals.entry[15, 0] == 1


def test_metadata_defaults_and_strategy_discovery():
    assert strategy.META["visibility_group"] == "douyin"
    assert "抖音主播策略" in strategy.META["tags"]
    assert strategy.META["asset_types"] == ["stock"]
    defaults = {item["id"]: item["default"] for item in strategy.META["params"]}
    assert defaults == {
        "fast_expma_days": 13,
        "slow_expma_days": 23,
        "new_high_days": 10,
        "new_high_max_days": 10,
        "pullback_max_days": 10,
    }

    engine = StrategyEngine(strategy_dirs=[Path(strategy.__file__).parent])
    discovered = engine.get("double_line_high_multiple")
    assert discovered.execution_backend == "matrix_native"
    assert discovered.matrix_strategy.__class__.__name__ == "DoubleLineHighMultipleStrategy"
