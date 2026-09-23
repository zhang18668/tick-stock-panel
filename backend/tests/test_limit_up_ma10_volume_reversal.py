from datetime import date, timedelta

import polars as pl

from app.backtest.matrix import build_market_data_matrix
from app.strategy.engine import StrategyEngine
from tests.strategy_plugin_test_support import PLUGIN_DIR, load_plugin_module

strategy = load_plugin_module("limit_up_ma10_volume_reversal")


def _market(*, touch_ma_intraday: bool = False, shrink_ratio: float = 0.4):
    closes = [10.0] * 12 + [11.0, 10.8, 10.6, 10.5, 10.4, 10.3, 10.2, 10.15, 10.6, 10.0]
    if touch_ma_intraday:
        closes[-3] = 10.55
        closes[-2] = 10.65
    volumes = [1000.0] * len(closes)
    volumes[-4] = 2000.0
    volumes[-3] = 2000.0 * shrink_ratio
    volumes[-2] = 1200.0
    rows = []
    for index, close in enumerate(closes):
        low = close - 0.05
        if touch_ma_intraday and index == len(closes) - 1:
            low = 9.95
        if touch_ma_intraday and index == len(closes) - 2:
            low = 10.35
        rows.append(
            {
                "symbol": "000001.SZ",
                "date": date(2024, 1, 2) + timedelta(days=index),
                "open": close - 0.02,
                "high": close + 0.05,
                "low": low,
                "close": close,
                "volume": volumes[index],
                "amount": volumes[index] * close,
                "signal_limit_up": index == 12,
            }
        )
    return build_market_data_matrix(pl.DataFrame(rows), field_columns={"amount", "volume"})


def test_loads_with_close_fills_and_main_board_filter() -> None:
    plugin_dir = PLUGIN_DIR
    loaded = StrategyEngine(strategy_dirs=[plugin_dir]).get(
        "limit_up_ma10_volume_reversal"
    )

    assert loaded.source == "custom"
    assert loaded.meta["visibility_group"] == "private"
    assert loaded.meta["execution_entry_fill"] == "close_t"
    assert loaded.meta["execution_exit_fill"] == "close_t"
    assert loaded.basic_filter["exclude_st"] is True
    assert loaded.basic_filter["boards"] == ["沪主板", "深主板"]
    assert loaded.stop_loss is None
    assert loaded.take_profit is None
    assert loaded.max_hold_days is None


def test_enters_after_half_volume_then_rebound_and_exits_below_ma10() -> None:
    signals = strategy.MATRIX_STRATEGY.compute_signals(_market(), {})

    assert signals.entry[-2, 0] == 1
    assert signals.entry[:, 0].sum() == 1
    assert signals.exit[-1, 0] == 1


def test_accepts_same_day_ma10_touch_and_reclaim() -> None:
    signals = strategy.MATRIX_STRATEGY.compute_signals(
        _market(touch_ma_intraday=True), {}
    )

    assert signals.entry[-2, 0] == 1


def test_rejects_volume_that_does_not_shrink_by_half() -> None:
    signals = strategy.MATRIX_STRATEGY.compute_signals(
        _market(shrink_ratio=0.6), {}
    )

    assert signals.entry[:, 0].sum() == 0
