from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import polars as pl
import pytest

from app.api.strategy import _strategy_detail
from app.backtest.engine import BacktestEngine
from app.backtest.matrix import build_market_data_matrix, slice_market_data_matrix
from app.backtest.strategy import (
    BacktestResultPolicy,
    StrategyBacktestConfig,
    StrategyBacktestService,
)
from app.strategy import config as saved_config
from app.strategy.engine import StrategyEngine
from tests.strategy_plugin_test_support import load_plugin_module

strategy = load_plugin_module("double_limit_up_ma5_reclaim")


def _market():
    candles = {
        10: (10.0, 11.0, 10.0, 11.0, 1200.0, True),
        11: (11.0, 12.1, 11.0, 12.1, 1600.0, True),
        12: (12.1, 12.15, 11.7, 11.8, 800.0, False),
        13: (11.8, 11.9, 11.3, 11.4, 600.0, False),
        14: (11.4, 11.9, 11.1, 11.2, 400.0, False),
        15: (11.15, 11.75, 11.1, 11.7, 1300.0, False),
    }
    rows = []
    for i in range(23):
        o, h, lo, c, v, limit = candles.get(i, (10, 10.1, 9.9, 10, 1000, False))
        if i >= 16:
            o, h, lo, c = 11.7, 11.9, 11.6, 11.8
        rows.append({
            "symbol": "000001.SZ", "name": "示例股票",
            "date": date(2025, 1, 1) + timedelta(days=i),
            "open": o, "high": h, "low": lo, "close": c,
            "raw_high": h, "raw_low": lo, "raw_close": c,
            "volume": v, "amount": 50_000_000.0,
            "signal_limit_up": limit, "signal_limit_down": False,
        })
    return build_market_data_matrix(pl.DataFrame(rows), field_columns={"amount", "name"})


def _signals(market=None, **params):
    return strategy.MATRIX_STRATEGY.compute_signals(market or _market(), params)


def test_default_pattern_and_signal_identity():
    signals = _signals()
    assert np.flatnonzero(signals.entry[:, 0]).tolist() == [15]
    assert signals.entry_signal_ids == ("double_limit_up_ma5_reclaim",)
    assert signals.exit_signal_ids == ("close_below_ma10",)


@pytest.mark.parametrize("params", [
    {"pullback_min_days": 4}, {"pullback_max_days": 2},
    {"shrink_ratio": 0.3}, {"rebound_ratio": 3.0}, {"engulf_mode": "high"},
])
def test_factors_reject_pattern_at_boundary(params):
    assert _signals(**params).entry.sum() == 0


@pytest.mark.parametrize("change", ["one_word", "third_board", "gap", "lost_support", "missing_bar"])
def test_rejects_invalid_setups(change):
    market = _market()
    if change == "one_word":
        values = market.open.copy()
        values[10, 0] = market.close[10, 0]
        market = replace(market, open=values)
    elif change == "third_board":
        values = market.limit_up_locked.copy()
        values[12, 0] = 1
        market = replace(market, limit_up_locked=values)
    elif change == "gap":
        values = market.open.copy()
        values[15, 0] = 11.3
        market = replace(market, open=values)
    else:
        values = market.close.copy()
        values[13, 0] = np.nan if change == "missing_bar" else 9.0
        market = replace(market, close=values)
    assert _signals(market).entry.sum() == 0


def test_signal_prefix_unchanged_by_future_prices_or_uniform_adjustment():
    market = _market()
    before = _signals(market).entry
    prefix = slice_market_data_matrix(market, 0, 16)
    np.testing.assert_array_equal(_signals(prefix).entry, before[:16])
    scaled = replace(market, **{key: getattr(market, key) * 0.5 for key in ("open", "high", "low", "close")})
    np.testing.assert_array_equal(_signals(scaled).entry, before)
    changed = market.close.copy()
    changed[16:] *= 5
    np.testing.assert_array_equal(_signals(replace(market, close=changed)).entry[:16], before[:16])


def test_invalid_parameters_and_empty_market():
    with pytest.raises(ValueError, match="回调交易日"):
        _signals(pullback_min_days=5, pullback_max_days=2)
    with pytest.raises(ValueError, match="反包范围"):
        _signals(engulf_mode="unknown")
    assert _signals(slice_market_data_matrix(_market(), 0, 0)).entry.size == 0


def test_discovery_detail_saved_parameters_and_defaults(tmp_path):
    engine = StrategyEngine(strategy_dirs=[Path(strategy.__file__).parent])
    discovered = engine.get(strategy.META["id"])
    assert discovered.execution_backend == "matrix_native"
    detail = _strategy_detail(discovered)
    assert discovered.meta["visibility_group"] == "private"
    assert detail["stop_loss"] == -0.05
    assert detail["take_profit"] == 0.15
    assert detail["max_hold_days"] == 10
    saved_config.save_override(tmp_path, strategy.META["id"], {"params": {"shrink_ratio": 0.5}})
    saved = saved_config.load_override(tmp_path, strategy.META["id"])
    assert _strategy_detail(discovered, saved)["params_defaults"]["shrink_ratio"] == 0.5
    assert _strategy_detail(discovered, saved)["params_defaults"]["rebound_ratio"] == 1.5


def test_shared_backtest_uses_next_open_and_t_plus_one():
    market = _market()

    class FixtureEngine(BacktestEngine):
        def load_market_data_matrix_for_backtest(self, *args, **kwargs):
            return market

    engine = StrategyEngine(strategy_dirs=[Path(strategy.__file__).parent])
    service = StrategyBacktestService(FixtureEngine(SimpleNamespace()), engine)
    result = service.run(StrategyBacktestConfig(
        strategy_id=strategy.META["id"], symbols=None,
        start=date(2025, 1, 1), end=date(2025, 1, 23),
        matching="close_t",  # 策略元数据必须仍强制次日开盘。
        overrides={"max_hold_days": 1, "basic_filter": {"enabled": False}},
        commission_pct=0.0003, stamp_tax_pct=0.0005, slippage_bps=10,
    ), result_policy=BacktestResultPolicy(include_benchmark=False, include_monte_carlo=False))
    assert result.error is None
    assert len(result.trades) == 1
    trade = result.trades[0]
    assert str(trade["entry_signal_date"])[:10] == "2025-01-16"
    assert str(trade["entry_date"])[:10] == "2025-01-17"
    assert str(trade["exit_date"])[:10] > str(trade["entry_date"])[:10]
    assert trade["pnl_pct"] < 0  # 相同开盘价进出，仍扣双边成本和卖出税。
