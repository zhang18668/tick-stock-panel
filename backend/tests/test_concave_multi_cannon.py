from datetime import date, timedelta
from pathlib import Path

import polars as pl
import pytest

from app.backtest.matrix import build_market_data_matrix
from app.strategy.engine import StrategyEngine
from tests.strategy_plugin_test_support import load_plugin_module

concave_multi_cannon = load_plugin_module("concave_multi_cannon")


def _signals(*, middle_volume=80.0, third_volume=200.0, first_volume=200.0, warmup_end=10.5, params=None):
    rows = []
    start = date(2026, 1, 5)
    for index in range(8):
        close = 10.0 + (warmup_end - 10.0) * index / 7
        open_ = close * (0.998 if index % 2 == 0 else 1.002)
        rows.append((open_, close, 100.0))
    rows.extend([
        (10.45, 10.75, first_volume),
        (10.72, 10.62, middle_volume),
        (10.64, 10.90, third_volume),
    ])
    panel = pl.DataFrame([
        {
            "symbol": "000001.SZ",
            "date": start + timedelta(days=index),
            "open": open_,
            "high": max(open_, close) + 0.03,
            "low": min(open_, close) - 0.03,
            "close": close,
            "volume": volume,
            "amount": close * volume,
        }
        for index, (open_, close, volume) in enumerate(rows)
    ])
    market = build_market_data_matrix(panel, field_columns={"amount"})
    return concave_multi_cannon.MATRIX_STRATEGY.compute_signals(market, params or {})


def test_matches_double_volume_shrink_bearish_double_volume_bullish_pattern():
    signals = _signals()
    assert signals.entry[-1, 0] == 1
    assert signals.entry[:-1, 0].sum() == 0


@pytest.mark.parametrize(
    "overrides",
    [
        {"first_volume": 179.9},
        {"middle_volume": 80.1},
        {"third_volume": 199.9},
        {"warmup_end": 10.05},
    ],
)
def test_rejects_when_a_required_pattern_leg_fails(overrides):
    assert not _signals(**overrides).entry[-1, 0]


def test_volume_thresholds_are_optimizer_parameters():
    signals = _signals(
        first_volume=180.0,
        middle_volume=100.0,
        third_volume=150.0,
        params={
            "first_volume_ratio": 1.8,
            "middle_volume_max_ratio": 0.6,
            "third_volume_ratio": 1.5,
        },
    )
    assert signals.entry[-1, 0] == 1


def test_is_private_optimizer_ready_and_discoverable():
    meta = concave_multi_cannon.META
    assert meta["visibility_group"] == "private"
    assert meta["asset_types"] == ["stock"]
    assert {item["id"] for item in meta["params"]} >= {
        "rise_lookback_days",
        "first_volume_ratio",
        "middle_volume_max_ratio",
        "third_volume_ratio",
    }
    strategy = StrategyEngine(
        strategy_dirs=[Path(concave_multi_cannon.__file__).resolve().parent]
    ).get("concave_multi_cannon")
    assert strategy.execution_backend == "matrix_native"
    assert strategy.matrix_strategy is not None
