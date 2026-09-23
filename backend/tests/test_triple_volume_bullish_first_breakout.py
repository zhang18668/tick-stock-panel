from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import polars as pl

from app.backtest.matrix import build_market_data_matrix
from app.strategy.engine import StrategyEngine
from tests.strategy_plugin_test_support import load_plugin_module

triple_volume_bullish_first_breakout = load_plugin_module("triple_volume_bullish_first_breakout")


def _market(overrides: dict[int, tuple[float, float, float]] | None = None):
    rows = []
    overrides = overrides or {}
    start = date(2024, 1, 2)
    for index in range(35):
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
    return build_market_data_matrix(
        pl.DataFrame(rows),
        field_columns={"amount", "turnover_rate"},
    )


def _signals(
    overrides: dict[int, tuple[float, float, float]],
    params: dict | None = None,
):
    market = _market(overrides)
    return triple_volume_bullish_first_breakout.MATRIX_STRATEGY.compute_signals(
        market,
        params or {},
    )


def test_first_lower_volume_close_breakout_is_the_buy_point():
    signals = _signals({
        22: (9.5, 11.0, 300.0),
        23: (10.9, 11.1, 250.0),
    })

    assert signals.entry[23, 0] == 1
    assert signals.entry.sum() == 1


def test_equal_close_is_not_a_breakout():
    signals = _signals({
        22: (9.5, 11.0, 300.0),
        23: (10.9, 11.0, 200.0),
        24: (10.9, 11.1, 200.0),
    })

    assert signals.entry[23, 0] == 0
    assert signals.entry[24, 0] == 1


def test_first_breakout_on_seventh_trading_day_is_valid():
    signals = _signals({
        22: (9.5, 11.0, 300.0),
        29: (10.9, 11.2, 200.0),
    })

    assert signals.entry[29, 0] == 1


def test_first_breakout_after_seven_trading_days_is_rejected():
    signals = _signals({
        22: (9.5, 11.0, 300.0),
        30: (10.9, 11.2, 200.0),
    })

    assert not signals.entry.any()


def test_equal_volume_first_breakout_abandons_the_setup():
    signals = _signals({
        22: (9.5, 11.0, 300.0),
        23: (10.9, 11.1, 300.0),
        24: (11.0, 10.9, 100.0),
        25: (10.9, 11.2, 200.0),
    })

    assert not signals.entry.any()


def test_setup_requires_bullish_candle_and_three_times_previous_volume():
    bearish = _signals({
        22: (11.0, 10.5, 300.0),
        23: (10.5, 10.6, 100.0),
    })
    insufficient_volume = _signals({
        22: (9.5, 11.0, 299.9),
        23: (10.9, 11.1, 100.0),
    })

    assert not bearish.entry.any()
    assert not insufficient_volume.entry.any()


def test_setup_requires_open_below_and_close_above_all_three_mas():
    open_above_mas = _signals({
        22: (10.1, 11.0, 300.0),
        23: (10.9, 11.1, 100.0),
    })
    close_below_one_ma = _signals({
        22: (9.5, 10.0, 300.0),
        23: (10.0, 10.1, 100.0),
    })

    assert not open_above_mas.entry.any()
    assert not close_below_one_ma.entry.any()


def test_all_numeric_conditions_are_parameterized():
    params = {
        param["id"]
        for param in triple_volume_bullish_first_breakout.META["params"]
    }

    assert params == {
        "ma_short_days",
        "ma_mid_days",
        "ma_long_days",
        "volume_ratio_min",
        "bullish_body_min_pct",
        "max_breakout_days",
        "breakout_close_pct",
        "breakout_volume_ratio_max",
    }


def test_strategy_is_in_tianya_and_discoverable():
    engine = StrategyEngine(
        strategy_dirs=[Path(triple_volume_bullish_first_breakout.__file__).resolve().parent]
    )
    strategy = engine.get("triple_volume_bullish_first_breakout")

    assert strategy.meta["visibility_group"] == "tianya"
    assert strategy.meta["name"] == "三线逐浪"
    assert "天涯" in strategy.meta["tags"]
    assert strategy.meta["basic_filter"]["exclude_st"] is True
    assert strategy.execution_backend == "matrix_native"
    assert strategy.matrix_strategy is not None
