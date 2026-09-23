from datetime import date, timedelta

import polars as pl

from app.backtest.matrix import build_market_data_matrix
from app.strategy.engine import StrategyEngine
from tests.strategy_plugin_test_support import PLUGIN_DIR

STRATEGY_PATH = (
    PLUGIN_DIR
    / "overnight_dragon.py"
)


def _market(symbol: str = "600001.SH", name: str = "样本股份"):
    rows = []
    for index in range(50):
        close = 10 + index * 0.03
        rows.append({
            "symbol": symbol,
            "name": name,
            "date": date(2026, 1, 1) + timedelta(days=index),
            "open": close - 0.03,
            "high": close + 0.06,
            "low": close - 0.06,
            "close": close,
            "volume": 100.0,
        })
    previous_close = rows[-1]["close"]
    close = previous_close * 1.035
    rows.append({
        "symbol": symbol,
        "name": name,
        "date": date(2026, 2, 20),
        "open": previous_close * 1.01,
        "high": close + 0.08,
        "low": previous_close * 1.005,
        "close": close,
        "volume": 200.0,
    })
    rows.append({
        "symbol": symbol,
        "name": name,
        "date": date(2026, 2, 21),
        "open": close,
        "high": close + 0.05,
        "low": close - 0.05,
        "close": close + 0.02,
        "volume": 100.0,
    })
    return build_market_data_matrix(pl.DataFrame(rows))


def test_overnight_dragon_is_private_and_optimizer_ready():
    strategy = StrategyEngine._load_file(STRATEGY_PATH)

    assert strategy.meta["visibility_group"] == "diya"
    assert strategy.meta["name"] == "一夜持股法(尾盘短线擒龙)"
    assert {item["id"] for item in strategy.meta["params"]} >= {
        "ma_long_days",
        "kdj_d_min",
        "volume_ratio_min",
        "gain_min_pct",
        "gain_max_pct",
        "close_position_min",
    }
    assert strategy.meta["execution_entry_fill"] == "open_t+1"
    assert strategy.meta["execution_exit_fill"] == "open_t+1"
    assert strategy.max_hold_days == 2


def test_overnight_dragon_matches_formula_and_schedules_next_bar_exit_signal():
    strategy = StrategyEngine._load_file(STRATEGY_PATH)
    signals = strategy.matrix_strategy.compute_signals(_market(), {})

    assert signals.entry[-2, 0] == 1
    assert signals.exit[-1, 0] == 1


def test_overnight_dragon_honors_gain_volume_board_and_st_filters():
    strategy = StrategyEngine._load_file(STRATEGY_PATH)

    strict_gain = strategy.matrix_strategy.compute_signals(
        _market(), {"gain_min_pct": 4.0}
    )
    strict_volume = strategy.matrix_strategy.compute_signals(
        _market(), {"volume_ratio_min": 2.1}
    )
    excluded_board = strategy.matrix_strategy.compute_signals(_market("688001.SH"), {})
    excluded_st = strategy.matrix_strategy.compute_signals(_market(name="*ST样本"), {})

    assert not strict_gain.entry.any()
    assert not strict_volume.entry.any()
    assert not excluded_board.entry.any()
    assert not excluded_st.entry.any()
