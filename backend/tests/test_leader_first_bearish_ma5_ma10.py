from datetime import date, timedelta

import polars as pl

from app.backtest.matrix import build_market_data_matrix
from tests.strategy_plugin_test_support import load_plugin_module

strategy = load_plugin_module("leader_first_bearish_ma5_ma10")


def _market(*, break_ma10: bool = False, no_shrink: bool = False):
    rows = []
    closes = [10.0] * 20 + [10.3, 11.33, 12.46, 12.20, 12.12, 12.08, 12.04, 12.02, 12.01, 12.00]
    volumes = [1000.0] * 20 + [1100.0, 3000.0, 3200.0, 2500.0, 1700.0, 1500.0, 1300.0, 1200.0, 1100.0, 1000.0]
    for index, close in enumerate(closes):
        open_ = close
        high = close + 0.08
        low = close - 0.08
        is_limit = index in (21, 22)
        if index == 21:
            open_, high, low = 10.3, close, 9.9
        elif index == 22:
            open_, high, low = 11.33, close, 11.30
        elif index == 23:
            open_, high, low = 12.35, 12.38, 12.10
        if break_ma10 and index == 26:
            close = 10.0
            open_, high, low = 10.2, 10.25, 9.9
        if no_shrink and index >= 24:
            volumes[index] = 3000.0
        rows.append({
            "symbol": "000001.SZ",
            "date": date(2024, 1, 2) + timedelta(days=index),
            "open": open_, "high": high, "low": low, "close": close,
            "raw_close": close, "raw_high": high,
            "signal_limit_up": is_limit,
            "volume": volumes[index], "amount": volumes[index] * close,
        })
    return build_market_data_matrix(pl.DataFrame(rows), field_columns={"amount", "raw_close", "raw_high", "volume"})


def test_signals_after_two_boards_first_bearish_shrink_and_convergence():
    signals = strategy.MATRIX_STRATEGY.compute_signals(_market(), {})
    assert signals.entry[:, 0].sum() == 1
    assert signals.entry[29, 0] == 1


def test_rejects_broken_ma10_or_non_shrinking_consolidation():
    assert strategy.MATRIX_STRATEGY.compute_signals(_market(break_ma10=True), {}).entry[:, 0].sum() == 0
    assert strategy.MATRIX_STRATEGY.compute_signals(_market(no_shrink=True), {}).entry[:, 0].sum() == 0


def test_private_metadata_and_optimizer_parameters():
    assert strategy.META["visibility_group"] == "diya"
    assert strategy.META["name"] == "龙头首阴--5弯10"
    assert {item["id"] for item in strategy.META["params"]} >= {"convergence_days", "max_setup_age", "volume_ratio_max"}
