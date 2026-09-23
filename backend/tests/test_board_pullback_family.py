from dataclasses import replace
from datetime import date, timedelta
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
from tests.strategy_plugin_test_support import PLUGIN_DIR

MODES = [
    "shallow",
    "deep",
    "ma10",
    "late",
    "trend",
    "reclaim5",
    "first",
    "midpoint",
    "volume",
    "macd",
    "kdj",
    "momentum",
]


@pytest.fixture(scope="module")
def engine():
    return StrategyEngine(strategy_dirs=[PLUGIN_DIR])


def market(mode="shallow"):
    candles = {
        60: (10, 11, 10, 11, 1000),
        61: (11, 12.1, 11, 12.1, 1000),
        62: (12, 12, 11.5, 11.6, 300),
        63: (11.6, 11.7, 11.25, 11.3, 300),
        64: (11.4, 11.5, 11.1, 11.2, 300),
        65: (11.1, 11.9, 11.1, 11.8, 1300),
    }
    if mode == "deep":
        candles[64] = (11.3, 11.4, 10.5, 10.8, 300)
        candles[65] = (10.8, 12, 10.6, 11.9, 1300)
    if mode == "first":
        candles[63] = (11.6, 11.7, 10.95, 11.1, 300)
    if mode in {"late", "macd", "kdj"}:
        for t in range(63, 72):
            price = 11.5 - (t - 63) * (0.30 if mode == "kdj" else 0.10)
            candles[t] = (price + 0.1, price + 0.2, price - 0.1, price, 300)
        candles[72] = (10.7, 12.3, 9.8 if mode == "kdj" else 10.6, 12.2, 1300)
    if mode in {"trend", "momentum"}:
        candles[65] = (11.1, 12.3, 11.1, 12.2, 1300)
    if mode == "momentum":
        candles[63] = (11.5, 12.3, 11.4, 12.3, 1300)
    rows = []
    for t in range(90):
        base = 10 if mode != "momentum" else max(6.0, 6.0 + (t - 39) * 0.2)
        values = candles.get(t, (base, base + 0.1, base - 0.1, base, 1000))
        if t > 72:
            values = (12.2, 12.4, 12.1, 12.3, 1000)
        op, high, low, close, volume = values
        rows.append(
            dict(
                symbol="000001.SZ",
                name="示例",
                date=date(2025, 1, 1) + timedelta(days=t),
                open=op,
                high=high,
                low=low,
                close=close,
                raw_close=close,
                raw_high=high,
                raw_low=low,
                volume=volume,
                amount=50_000_000.0,
                signal_limit_up=t in {60, 61},
                signal_limit_down=False,
            )
        )
    return build_market_data_matrix(pl.DataFrame(rows), field_columns={"amount"})


@pytest.mark.parametrize("mode", MODES)
def test_discovery_parameters_and_signal_contract(engine, tmp_path, mode):
    sd = engine.get("board_pullback_" + mode)
    detail = _strategy_detail(sd)
    assert sd.meta["visibility_group"] == "board_pullback"
    assert sd.execution_backend == "matrix_native"
    assert (
        detail["stop_loss"] == -0.05
        and detail["take_profit"] == 0.15
        and detail["max_hold_days"] == 10
    )
    saved_config.save_override(tmp_path, sd.meta["id"], {"params": {"max_days": 20}})
    assert (
        _strategy_detail(sd, saved_config.load_override(tmp_path, sd.meta["id"]))[
            "params_defaults"
        ]["max_days"]
        == 20
    )
    result = sd.matrix_strategy.compute_signals(market(mode), {})
    assert result.entry.sum() >= 1, mode
    assert result.entry.sum() == 1
    assert result.entry_signal_ids == (sd.meta["id"],)
    assert result.exit.sum() == 0


@pytest.mark.parametrize("mode", MODES)
def test_no_future_information_and_uniform_adjustment(engine, mode):
    sd = engine.get("board_pullback_" + mode)
    m = market(mode)
    result = sd.matrix_strategy.compute_signals(m, {}).entry
    for end in [62, 64, 66, 73]:
        np.testing.assert_array_equal(
            sd.matrix_strategy.compute_signals(slice_market_data_matrix(m, 0, end), {}).entry,
            result[:end],
        )
    scaled = replace(m, **{k: getattr(m, k) * 0.5 for k in ["open", "high", "low", "close"]})
    np.testing.assert_array_equal(sd.matrix_strategy.compute_signals(scaled, {}).entry, result)


@pytest.mark.parametrize("mode", MODES)
def test_reject_three_boards_and_missing_break(engine, mode):
    sd = engine.get("board_pullback_" + mode)
    m = market(mode)
    up = m.limit_up_locked.copy()
    up[62] = 1
    assert sd.matrix_strategy.compute_signals(replace(m, limit_up_locked=up), {}).entry.sum() == 0
    close = m.close.copy()
    close[62] = np.nan
    assert sd.matrix_strategy.compute_signals(replace(m, close=close), {}).entry.sum() == 0
    assert sd.matrix_strategy.compute_signals(m, {"min_days": 29, "max_days": 30}).entry.sum() == 0
    with pytest.raises(ValueError):
        sd.matrix_strategy.compute_signals(m, {"min_days": 5, "max_days": 2})
    assert sd.matrix_strategy.compute_signals(slice_market_data_matrix(m, 0, 0), {}).entry.size == 0


def test_all_twelve_are_in_new_group(engine):
    assert {
        s["id"] for s in engine.list_strategies() if s.get("visibility_group") == "board_pullback"
    } == {"board_pullback_" + m for m in MODES}


@pytest.mark.parametrize("mode", MODES)
def test_shared_backtest_next_open_and_t1(engine, mode):
    m = market(mode)

    class FixtureEngine(BacktestEngine):
        def load_market_data_matrix_for_backtest(self, *args, **kwargs):
            return m

    service = StrategyBacktestService(FixtureEngine(SimpleNamespace()), engine)
    cfg = StrategyBacktestConfig(
        strategy_id="board_pullback_" + mode,
        symbols=None,
        start=date(2025, 1, 1),
        end=date(2025, 3, 31),
        matching="close_t",
        overrides={"max_hold_days": 1, "basic_filter": {"enabled": False}},
    )
    result = service.run(
        cfg, result_policy=BacktestResultPolicy(include_benchmark=False, include_monte_carlo=False)
    )
    assert result.error is None
    assert len(result.trades) == 1
    trade = result.trades[0]
    assert str(trade["entry_date"])[:10] > str(trade["entry_signal_date"])[:10]
    assert str(trade["exit_date"])[:10] > str(trade["entry_date"])[:10]


@pytest.mark.parametrize("exit_mode", ["ma5", "ma10", "pullback_low"])
def test_additional_exit_and_entry_parameter_change(engine, exit_mode):
    sd = engine.get("board_pullback_shallow")
    m = market()
    result = sd.matrix_strategy.compute_signals(m, {"exit_mode": exit_mode})
    assert result.entry[65, 0]
    assert result.exit[66, 0]  # Price falls to 10, below both MAs and the known pullback low.
    assert sd.matrix_strategy.compute_signals(m, {"depth_max": 0.01}).entry.sum() == 0
