from datetime import date, timedelta

import polars as pl

from app.backtest.matrix import build_market_data_matrix
from app.strategy.engine import StrategyEngine
from tests.strategy_plugin_test_support import PLUGIN_DIR, load_plugin_module

strategy = load_plugin_module("double_dragon_playing_water")


def _market(*, large_bearish_index: int | None = None, wide_pre_board_range: bool = False):
    closes = [10.0] * 45 + [10.3, 11.33, 12.46, 12.20, 12.12, 12.08, 12.04, 12.02, 12.01, 12.00]
    volumes = [1000.0] * 45 + [1100.0, 3000.0, 3200.0, 2500.0, 1700.0, 1500.0, 1300.0, 1200.0, 1100.0, 1000.0]
    rows = []
    for index, close in enumerate(closes):
        open_ = close
        high = close + 0.08
        low = close - 0.08
        is_limit = index in (46, 47)
        if wide_pre_board_range and index == 10:
            high = 14.0
        if index == 46:
            open_, high, low = 10.3, close, 9.9
        elif index == 47:
            open_, high, low = 11.33, close, 11.30
        elif index == 48:
            open_, high, low = 12.35, 12.38, 12.10
        if index == large_bearish_index:
            open_ = close / 0.90
            high = open_ + 0.05
            low = close - 0.05
        rows.append({
            "symbol": "000001.SZ",
            "date": date(2024, 1, 2) + timedelta(days=index),
            "open": open_, "high": high, "low": low, "close": close,
            "raw_close": close, "raw_high": high,
            "signal_limit_up": is_limit,
            "volume": volumes[index], "amount": volumes[index] * close,
        })
    return build_market_data_matrix(
        pl.DataFrame(rows),
        field_columns={"amount", "raw_close", "raw_high", "volume"},
    )


def test_metadata_and_adjustable_guard_parameters():
    assert strategy.META["name"] == "二龙戏水"
    assert strategy.META["visibility_group"] == "tianya"
    params = {item["id"]: item["default"] for item in strategy.META["params"]}
    assert params["max_bearish_body_pct"] == 8.0
    assert params["pre_board_range_days"] == 40
    assert params["max_pre_board_range_pct"] == 35.0
    plugin_dir = PLUGIN_DIR
    discovered = StrategyEngine(strategy_dirs=[plugin_dir]).get("double_dragon_playing_water")
    assert discovered.meta["visibility_group"] == "tianya"
    assert discovered.matrix_strategy is not None
    assert discovered.stop_loss is None
    assert discovered.take_profit is None
    assert discovered.trailing_stop is None
    assert discovered.trailing_take_profit_activate == 0.10
    assert discovered.trailing_take_profit_drawdown == 0.10
    assert discovered.max_hold_days == 40


def test_accepts_flat_pre_board_window_without_large_bearish_body():
    signals = strategy.MATRIX_STRATEGY.compute_signals(_market(), {})
    assert signals.entry[:, 0].sum() == 1
    assert signals.entry[54, 0] == 1


def test_rejects_large_bearish_body_after_second_board():
    params = {"max_bearish_body_pct": 8.0, "pre_board_range_days": 40, "max_pre_board_range_pct": 35.0}
    assert strategy.MATRIX_STRATEGY.compute_signals(_market(large_bearish_index=50), params).entry[:, 0].sum() == 0


def test_bearish_body_threshold_is_based_on_open_not_previous_close():
    params = {"max_bearish_body_pct": 11.0, "pre_board_range_days": 40, "max_pre_board_range_pct": 35.0}
    assert strategy.MATRIX_STRATEGY.compute_signals(_market(large_bearish_index=50), params).entry[:, 0].sum() == 1


def test_rejects_wide_range_before_first_board():
    params = {"max_bearish_body_pct": 8.0, "pre_board_range_days": 40, "max_pre_board_range_pct": 35.0}
    assert strategy.MATRIX_STRATEGY.compute_signals(_market(wide_pre_board_range=True), params).entry[:, 0].sum() == 0
