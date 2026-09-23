from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import polars as pl

from app.backtest.matrix import build_market_data_matrix
from app.strategy.engine import StrategyEngine
from tests.strategy_plugin_test_support import load_plugin_module

double_limit_up_cannon = load_plugin_module("double_limit_up_cannon")


def _market(*, symbol="000001.SZ", name="平安银行", front_body_pct=4.0, signal_volume=150.0):
    rows = []
    start = date(2024, 1, 2)
    close = 10.0
    for index in range(70):
        previous = close
        close = previous * (1.001 if index < 60 else 1.0)
        volume = 100.0
        signal_limit_up = False
        if index == 62:
            close = previous * 1.10
            signal_limit_up = True
        elif index == 66:
            close = previous * 1.10
            volume = signal_volume
            signal_limit_up = True
        rows.append({
            "symbol": symbol,
            "name": name,
            "date": start + timedelta(days=index),
            "open": close / (1.0 + (front_body_pct / 100.0 if index == 62 else 0.04)),
            "high": close,
            "low": close * 0.98,
            "close": close,
            "raw_close": close,
            "raw_high": close,
            "volume": volume,
            "amount": volume * close,
            "signal_limit_up": signal_limit_up,
        })
    return build_market_data_matrix(pl.DataFrame(rows), field_columns={"amount"})


def _entry(**kwargs) -> bool:
    signals = double_limit_up_cannon.MATRIX_STRATEGY.compute_signals(_market(**kwargs), {})
    return bool(signals.entry[66, 0])


def test_matches_extracted_double_cannon_formula():
    assert _entry()


def test_rejects_large_limit_up_body_and_weak_signal_day_volume():
    assert not _entry(front_body_pct=5.0)
    assert not _entry(signal_volume=110.0)


def test_excludes_st_star_market_and_beijing_exchange():
    assert not _entry(name="*ST测试")
    assert not _entry(symbol="688001.SH")
    assert not _entry(symbol="920001.BJ")


def test_is_private_optimizer_ready_and_discoverable():
    meta = double_limit_up_cannon.META
    assert meta["visibility_group"] == "private"
    assert {item["id"] for item in meta["params"]} >= {
        "spacing_min_days",
        "limit_up_window_days",
        "limit_up_body_max_pct",
        "volume_ma_days",
        "volume_ratio_min",
        "trend_ma_days",
    }
    engine = StrategyEngine(
        strategy_dirs=[Path(double_limit_up_cannon.__file__).resolve().parent]
    )
    strategy = engine.get("double_limit_up_cannon")
    assert strategy.execution_backend == "matrix_native"
