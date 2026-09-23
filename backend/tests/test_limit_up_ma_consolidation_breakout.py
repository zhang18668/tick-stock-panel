from __future__ import annotations

from datetime import date, timedelta

import polars as pl

from app.backtest.matrix import build_market_data_matrix
from tests.strategy_plugin_test_support import load_plugin_module

limit_up_ma_consolidation_breakout = load_plugin_module("limit_up_ma_consolidation_breakout")


def _market(
    *,
    bearish_volume: float = 220.0,
    breakout_day: int = 35,
    falling_ma20: bool = False,
    extra_limit_ups: int = 0,
    consolidation_candles: dict[int, tuple[float, float]] | None = None,
):
    start = date(2024, 1, 2)
    rows = []
    for index in range(42):
        base = 9.0 + index * 0.035
        open_, high, low, close, volume = base, base + 0.08, base - 0.08, base + 0.02, 100.0
        limit_up = False
        if index == 24:  # 第一段启动,建立 BARSLAST(启动点) 窗口
            open_, high, low, close, volume = 9.65, 10.05, 9.50, 9.98, 180.0
        elif index == 27:
            open_, high, low, close, volume, limit_up = 10.0, 11.0, 9.95, 11.0, 100.0, True
        elif index == 28:  # 涨停次日的倍量阴,同时成为整理阶段高点
            open_, high, low, close, volume = 11.12, 11.20, 10.92, 11.0, bearish_volume
        elif 29 <= index < breakout_day:
            close = 10.75 - (index - 29) * 0.04 if falling_ma20 else 11.01 + (index - 29) * 0.015
            open_, high, low, volume = close - 0.02, min(close + 0.05, 11.18), close - 0.08, 105.0
            if consolidation_candles and index in consolidation_candles:
                open_, close = consolidation_candles[index]
                high, low = min(max(open_ + 0.03, close), 11.18), close - 0.05
            if index < 29 + extra_limit_ups:
                limit_up = True
        elif index == breakout_day:
            open_, high, low, close, volume = 10.82, 11.18, 10.30, 11.15, 180.0
        rows.append({
            "symbol": "000001.SZ",
            "date": start + timedelta(days=index),
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "raw_close": close,
            "raw_high": high,
            "volume": volume,
            "amount": volume * close,
            "signal_limit_up": limit_up,
        })
    return build_market_data_matrix(pl.DataFrame(rows), field_columns={"amount"})


def _entry(**market_kwargs) -> bool:
    params = market_kwargs.pop("params", {})
    signals = limit_up_ma_consolidation_breakout.MATRIX_STRATEGY.compute_signals(
        _market(**market_kwargs),
        params,
    )
    return bool(signals.entry[market_kwargs.get("breakout_day", 35), 0])


def test_matches_full_screenshot_sequence():
    assert _entry()


def test_requires_double_volume_bearish_anchor():
    assert not _entry(bearish_volume=199.9)


def test_requires_five_completed_consolidation_bars():
    assert not _entry(breakout_day=32)


def test_rejects_falling_ma20_during_consolidation():
    assert not _entry(falling_ma20=True)


def test_rejects_more_than_three_limit_ups_in_setup_window():
    assert not _entry(extra_limit_ups=4)


def test_startup_must_close_above_previous_three_day_high():
    assert not _entry(consolidation_candles={34: (11.12, 11.17)})


def test_rejects_deep_pullback_during_consolidation():
    assert not _entry(consolidation_candles={30: (10.00, 9.75)})


def test_is_private_and_exposes_optimizer_parameters():
    meta = limit_up_ma_consolidation_breakout.META
    assert meta["visibility_group"] == "private"
    assert {param["id"] for param in meta["params"]} >= {
        "bearish_volume_ratio",
        "startup_volume_ratio",
        "startup_body_pct",
        "consolidation_min_days",
        "consolidation_max_days",
        "max_limit_ups",
        "consolidation_max_drawdown_pct",
        "ma20_support_tolerance_pct",
        "startup_ma_tolerance_pct",
    }
