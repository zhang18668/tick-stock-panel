from datetime import date, timedelta
from pathlib import Path

import polars as pl

from app.backtest.matrix import build_market_data_matrix
from app.strategy.engine import StrategyEngine
from tests.strategy_plugin_test_support import load_plugin_module

strategy = load_plugin_module("double_limit_up_golden_pullback")


def _market(
    *,
    symbol: str = "000001.SZ",
    pullback_volume: float = 600.0,
    pullback_low: float = 10.60,
    pullback_close: float = 10.80,
    pullback_offset: int = 3,
):
    rows = []
    total_rows = 15
    for index in range(total_rows):
        open_ = high = low = close = 10.0
        volume = 1000.0
        is_limit_up = False
        if index == 2:
            open_, high, low, close, volume, is_limit_up = 10.0, 11.0, 10.0, 11.0, 1200.0, True
        elif index == 3:
            open_, high, low, close, volume, is_limit_up = 11.0, 12.1, 11.0, 12.1, 1400.0, True
        elif index == 3 + pullback_offset:
            open_, high, low, close, volume = 10.9, 10.95, pullback_low, pullback_close, pullback_volume
        elif index > 3:
            open_, high, low, close, volume = 11.4, 11.5, 11.3, 11.4, 800.0
        rows.append({
            "symbol": symbol,
            "date": date(2024, 1, 2) + timedelta(days=index),
            "open": open_, "high": high, "low": low, "close": close,
            "raw_high": high, "raw_low": low, "raw_close": close,
            "signal_limit_up": is_limit_up,
            "volume": volume, "amount": volume * close,
        })
    return build_market_data_matrix(
        pl.DataFrame(rows),
        field_columns={"amount", "raw_high", "raw_low", "raw_close"},
    )


def test_metadata_discovery_and_risk_defaults():
    assert strategy.META["visibility_group"] == "private"
    assert "私有" in strategy.META["tags"]
    plugin_dir = Path(strategy.__file__).resolve().parent
    discovered = StrategyEngine(strategy_dirs=[plugin_dir]).get(
        "double_limit_up_golden_pullback"
    )
    assert discovered.execution_backend == "matrix_native"
    assert discovered.stop_loss == -0.03
    assert discovered.take_profit == 0.15
    assert discovered.trailing_take_profit_activate == 0.10
    assert discovered.trailing_take_profit_drawdown == 0.03


def test_enters_on_contracted_pullback_touching_and_holding_first_board_golden_level():
    signals = strategy.MATRIX_STRATEGY.compute_signals(_market(), {})
    assert signals.entry[:, 0].sum() == 1
    assert signals.entry[6, 0] == 1


def test_rejects_heavy_volume_close_below_support_and_300_symbol():
    assert strategy.MATRIX_STRATEGY.compute_signals(
        _market(pullback_volume=1000.0), {}
    ).entry.sum() == 0
    assert strategy.MATRIX_STRATEGY.compute_signals(
        _market(pullback_close=10.50), {}
    ).entry.sum() == 0
    assert strategy.MATRIX_STRATEGY.compute_signals(
        _market(symbol="300001.SZ"), {}
    ).entry.sum() == 0


def test_rejects_pullback_after_ten_trading_day_window():
    signals = strategy.MATRIX_STRATEGY.compute_signals(
        _market(pullback_offset=11),
        {},
    )
    assert signals.entry.sum() == 0
