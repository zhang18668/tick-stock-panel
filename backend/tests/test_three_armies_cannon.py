from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import polars as pl

from app.backtest.matrix import build_market_data_matrix
from app.strategy.engine import StrategyEngine
from tests.strategy_plugin_test_support import load_plugin_module

three_armies_cannon = load_plugin_module("three_armies_cannon")


def _market(*, meeting_volume: float, cannon_offset: int | None = None):
    rows = []
    start = date(2024, 1, 2)
    for index in range(34):
        close = 10.0
        open_ = 9.98
        volume = 100.0
        if index == 24:
            close, open_ = 9.0, 9.1
        elif index >= 25:
            close, open_ = 11.0, 10.9
        if index == 26:
            volume = meeting_volume
        if cannon_offset is not None and index == 26 + cannon_offset:
            volume = 220.0
        rows.append({
            "symbol": "000001.SZ",
            "date": start + timedelta(days=index),
            "open": open_,
            "high": max(open_, close) + 0.05,
            "low": min(open_, close) - 0.05,
            "close": close,
            "volume": volume,
            "amount": volume * close,
        })
    return build_market_data_matrix(pl.DataFrame(rows), field_columns={"amount"})


def test_model_a_fires_on_high_volume_bullish_meeting():
    signals = three_armies_cannon.MATRIX_STRATEGY.compute_signals(
        _market(meeting_volume=220.0),
        {},
    )
    assert signals.entry[26, 0] == 1


def test_model_b_fires_after_low_volume_meeting_within_five_bars():
    signals = three_armies_cannon.MATRIX_STRATEGY.compute_signals(
        _market(meeting_volume=90.0, cannon_offset=3),
        {},
    )
    assert signals.entry[26, 0] == 0
    assert signals.entry[29, 0] == 1


def test_model_b_expires_after_configured_distance():
    signals = three_armies_cannon.MATRIX_STRATEGY.compute_signals(
        _market(meeting_volume=90.0, cannon_offset=6),
        {},
    )
    assert not signals.entry.any()


def test_private_metadata_optimizer_params_and_discovery():
    meta = three_armies_cannon.META
    assert meta["visibility_group"] == "private"
    assert meta["asset_types"] == ["stock"]
    assert {param["id"] for param in meta["params"]} >= {
        "cross_recent_days",
        "volume_lookback_days",
        "cannon_max_days",
    }
    engine = StrategyEngine(
        strategy_dirs=[Path(three_armies_cannon.__file__).resolve().parent]
    )
    strategy = engine.get("three_armies_cannon")
    assert strategy.execution_backend == "matrix_native"
    assert strategy.matrix_strategy is not None
