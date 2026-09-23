from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import polars as pl
import pytest

from app.backtest.matrix import build_market_data_matrix
from app.strategy.engine import StrategyEngine
from tests.strategy_plugin_test_support import load_plugin_module

strategy = load_plugin_module("magpies_on_plum")


def _signals(*, overrides=None, setup_close=11.0, setup_low=10.4, name="平安银行", params=None, volumes=None, return_market=False):
    overrides = overrides or {}
    rows = []
    start = date(2024, 1, 2)
    for index in range(70):
        open_, high, low, close = (10.0, 10.05, 9.95, 10.0)
        if index == 65:
            open_, high, low, close = (10.4, setup_close, setup_low, setup_close)
        elif index == 66:
            open_, high, low, close = (11.05, 11.35, 11.02, 11.30)
        elif index == 67:
            open_, high, low, close = (11.25, 11.60, 11.20, 11.50)
        elif index == 68:
            open_, high, low, close = (11.45, 11.85, 11.40, 11.75)
        open_, high, low, close = overrides.get(index, (open_, high, low, close))
        rows.append({
            "symbol": "000001.SZ",
            "name": name,
            "date": start + timedelta(days=index),
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "raw_close": close,
            "raw_high": high,
            "volume": (volumes or {}).get(index, {66: 150.0, 67: 120.0, 68: 90.0}.get(index, 100.0)),
            "amount": close * 100.0,
            "signal_limit_up": index == 65,
        })
    market = build_market_data_matrix(pl.DataFrame(rows), field_columns=strategy.MATRIX_STRATEGY.required_fields())
    if return_market:
        return market
    return strategy.MATRIX_STRATEGY.compute_signals(market, params or {})


def test_matches_low_limit_up_followed_by_three_mild_bullish_bars():
    signals = _signals()
    assert signals.entry[68, 0] == 1
    assert signals.entry.sum() == 1


def test_requires_all_three_closes_above_limit_up_price():
    assert not _signals(overrides={67: (10.9, 11.1, 10.8, 10.95)}).entry.any()


def test_rejects_body_over_three_percent_or_intraday_gain_over_five_percent():
    assert not _signals(overrides={67: (11.10, 11.50, 11.05, 11.45)}).entry.any()
    assert not _signals(overrides={67: (11.30, 11.90, 11.25, 11.50)}).entry.any()


def test_requires_the_three_bullish_bars_to_be_consecutive():
    assert not _signals(overrides={67: (11.55, 11.60, 11.20, 11.25)}).entry.any()


def test_allows_false_bearish_with_both_shadows_and_positive_daily_change():
    assert _signals(overrides={67: (11.55, 11.60, 11.30, 11.40)}).entry[68, 0] == 1


@pytest.mark.parametrize("bar", [
    (11.25, 11.50, 11.20, 11.50),
    (11.25, 11.60, 11.25, 11.50),
    (11.50, 11.60, 11.20, 11.50),
    (11.80, 11.85, 11.30, 11.40),
])
def test_rejects_missing_shadow_doji_or_large_false_bearish_body(bar):
    assert not _signals(overrides={67: bar}).entry.any()


@pytest.mark.parametrize("volume", [120.0, 130.0, 0.0, float("nan")])
def test_requires_positive_strictly_shrinking_consolidation_volume(volume):
    assert not _signals(volumes={68: volume}).entry.any()


def test_allows_close_equal_to_limit_up_price():
    assert _signals(overrides={68: (10.9, 11.85, 10.8, 11.0)}).entry[68, 0] == 1


@pytest.mark.parametrize("overrides", [
    {67: (11.25, 11.35, 11.20, 11.32)},
    {67: (11.25, 11.34, 11.20, 11.32)},
])
def test_allows_second_high_equal_or_lower_when_third_is_highest(overrides):
    assert _signals(overrides=overrides).entry[68, 0] == 1


@pytest.mark.parametrize("overrides", [
    {68: (11.45, 11.60, 11.40, 11.55)},
    {68: (11.45, 11.58, 11.40, 11.55)},
    {66: (11.05, 11.54, 11.02, 11.30), 67: (11.25, 11.34, 11.20, 11.32),
     68: (11.40, 11.53, 11.35, 11.50)},
    {66: (11.05, 11.54, 11.02, 11.30), 67: (11.25, 11.34, 11.20, 11.32),
     68: (11.40, 11.54, 11.35, 11.50)},
])
def test_rejects_third_high_not_strictly_above_both_prior_highs(overrides):
    assert not _signals(overrides=overrides).entry.any()


def test_requires_limit_up_to_be_low_and_excludes_st():
    assert not _signals(setup_close=14.0, setup_low=13.5).entry.any()
    assert not _signals(name="ST测试").entry.any()


def test_exits_when_close_falls_below_the_setup_limit_up_price():
    signals = _signals(overrides={69: (11.05, 11.10, 10.80, 10.90)})

    assert signals.entry[68, 0] == 1
    assert signals.exit[69, 0] == 1
    assert signals.exit_signal_ids == ("close_below_limit_up_price",)


def test_does_not_stop_at_or_above_the_setup_limit_up_price():
    signals = _signals(overrides={69: (11.05, 11.10, 10.90, 11.00)})

    assert not signals.exit.any()


def test_confirmation_days_and_close_buffer_are_parameterized():
    assert _signals(params={"bullish_days": 2}).entry[67, 0] == 1
    assert not _signals(params={"close_above_limit_min_pct": 3.0}).entry.any()


def test_st_filter_and_limit_price_stop_are_parameterized():
    assert _signals(name="ST测试", params={"exclude_st": False}).entry[68, 0] == 1
    signals = _signals(
        overrides={69: (11.05, 11.10, 10.80, 10.90)},
        params={"use_limit_price_stop": False},
    )
    assert not signals.exit.any()


def test_stop_buffer_is_parameterized():
    signals = _signals(
        overrides={69: (11.10, 11.20, 11.02, 11.05)},
        params={"stop_buffer_pct": 1.0},
    )
    assert signals.exit[69, 0] == 1


def test_is_private_optimizer_ready_and_discoverable():
    assert {item["id"] for item in strategy.META["params"]} == {
        "low_lookback_days", "low_position_max_pct", "bullish_days",
        "close_above_limit_min_pct", "body_max_pct", "high_gain_max_pct",
        "exclude_st", "use_limit_price_stop", "stop_buffer_pct",
    }
    engine = StrategyEngine(strategy_dirs=[Path(strategy.__file__).resolve().parent])
    discovered = engine.get("magpies_on_plum")
    assert discovered.meta["visibility_group"] == "tianya"
    assert "天涯" in discovered.meta["tags"]
    assert "地涯" not in discovered.meta["tags"]
    assert discovered.execution_backend == "matrix_native"
    assert strategy.STOP_LOSS is None
    assert strategy.EXIT_SIGNALS == ["close_below_limit_up_price"]
    assert discovered.meta["execution_entry_fill"] == "close_t"


def test_detail_uses_shared_defaults_and_preserves_saved_params():
    from app.api.strategy import _strategy_detail

    engine = StrategyEngine(strategy_dirs=[Path(strategy.__file__).resolve().parent])
    detail = _strategy_detail(engine.get("magpies_on_plum"), {"params": {"body_max_pct": 2.0}})
    assert detail["params_defaults"]["body_max_pct"] == 2.0
    assert detail["params_defaults"]["bullish_days"] == 3
    assert engine.get("magpies_on_plum").meta["visibility_group"] == "tianya"
    assert "收盘集合竞价" in detail["description"]


def test_no_future_bars_change_confirmation():
    import numpy as np

    market = _signals(return_market=True)
    before = strategy.MATRIX_STRATEGY.compute_signals(market, {})
    after = _signals(overrides={69: (99.0, 101.0, 98.0, 100.0)})
    np.testing.assert_array_equal(before.entry[:69], after.entry[:69])


def test_fills_on_third_consolidation_close_and_exits_no_earlier_than_next_day():
    from app.backtest.engine import BacktestEngine, MatcherConfig
    from app.backtest.matrix import build_market_matrix_from_signals

    market = _signals(return_market=True)
    signals = strategy.MATRIX_STRATEGY.compute_signals(market, {})
    execution = build_market_matrix_from_signals(market, signals)
    result = BacktestEngine(repo=None).simulate_market_matrix(
        execution,
        MatcherConfig(
            entry_fill=strategy.META["execution_entry_fill"],
            exit_fill="close_t", fees_pct=0, slippage_bps=0,
            max_positions=1, max_exposure_pct=1, initial_capital=100_000,
        ),
    )
    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.entry_price == 11.75
    assert str(trade.entry_date)[:10] == execution.timestamp_labels[68][:10]
    assert str(trade.exit_date)[:10] == execution.timestamp_labels[69][:10]
