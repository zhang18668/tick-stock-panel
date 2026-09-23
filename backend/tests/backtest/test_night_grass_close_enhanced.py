from datetime import date, timedelta

import numpy as np
import polars as pl

from app.backtest.engine import BacktestEngine, MatcherConfig
from app.backtest.matrix import build_market_data_matrix, build_market_matrix_from_signals
from app.strategy.engine import StrategyEngine
from tests.strategy_plugin_test_support import PLUGIN_DIR

STRATEGY_PATH = (
    PLUGIN_DIR
    / "night_grass_close_enhanced.py"
)


def test_night_grass_is_renamed_and_in_tianya_group():
    strategy = StrategyEngine._load_file(STRATEGY_PATH)
    assert strategy.meta["name"] == "空中飞饼"
    assert strategy.meta["visibility_group"] == "tianya"


def _panel(
    symbol: str = "600001.SH",
    name: str = "样本股份",
    confirmation_volume: float = 150.0,
    next_close: float | None = None,
    third_close: float | None = None,
):
    closes = [7.5 + i * 0.024 for i in range(50)]
    closes += [8.7, 8.75, 8.8, 8.85, 8.9, 9.0, 9.25, 9.27, 9.3, 10.23, 10.70, 10.90]
    volumes = [100.0] * (len(closes) - 2) + [200.0, confirmation_volume]
    rows = []
    for i, (close, volume) in enumerate(zip(closes, volumes, strict=True)):
        rows.append({
            "symbol": symbol,
            "name": name,
            "date": date(2026, 1, 1) + timedelta(days=i),
            "open": close - 0.05,
            "high": close + 0.05,
            "low": close - 0.10,
            "close": close,
            "raw_close": close,
            "raw_high": close + 0.05,
            "volume": volume,
            "amount": 120_000_000.0,
            "turnover_rate": 5.0,
        })
    rows[-3]["high"] = rows[-3]["raw_high"] = rows[-3]["close"]
    rows[-2].update(open=10.50, high=10.90, low=10.30)
    rows[-1].update(high=10.96, low=10.79, raw_high=10.96)
    if next_close is not None:
        rows.append({
            "symbol": symbol,
            "name": name,
            "date": date(2026, 1, 1) + timedelta(days=len(rows)),
            "open": next_close - 0.05,
            "high": next_close + 0.05,
            "low": next_close - 0.10,
            "close": next_close,
            "raw_close": next_close,
            "raw_high": next_close + 0.05,
            "volume": 120.0,
            "amount": 120_000_000.0,
            "turnover_rate": 5.0,
        })
    if third_close is not None:
        rows.append({
            "symbol": symbol,
            "name": name,
            "date": date(2026, 1, 1) + timedelta(days=len(rows)),
            "open": third_close - 0.05,
            "high": third_close + 0.05,
            "low": third_close - 0.10,
            "close": third_close,
            "raw_close": third_close,
            "raw_high": third_close + 0.05,
            "volume": 120.0,
            "amount": 120_000_000.0,
            "turnover_rate": 5.0,
        })
    for row in rows:
        row["raw_low"] = row["low"]
    panel = pl.DataFrame(rows)
    fields = {"amount", "raw_close", "raw_high", "raw_low", "turnover_rate"}
    return build_market_data_matrix(panel, field_columns=fields)


def test_night_grass_formula_matches_confirmation_day():
    strategy = StrategyEngine._load_file(STRATEGY_PATH)
    signals = strategy.matrix_strategy.compute_signals(_panel(), {})

    assert signals.entry[:-1].sum() == 0
    assert signals.entry[-1, 0] == 1
    assert strategy.stop_loss is None
    assert strategy.take_profit is None
    assert strategy.max_hold_days == 5


def test_night_grass_exits_on_profitable_next_close_only():
    strategy = StrategyEngine._load_file(STRATEGY_PATH)

    profitable = strategy.matrix_strategy.compute_signals(_panel(next_close=10.91), {})
    not_profitable = strategy.matrix_strategy.compute_signals(_panel(next_close=10.90), {})

    assert profitable.entry[-2, 0] == 1
    assert profitable.exit[-1, 0] == 1
    assert profitable.exit_signal_code[-1, 0] == 0
    assert not_profitable.exit[-1, 0] == 0


def test_night_grass_excludes_non_main_board_and_st_names():
    strategy = StrategyEngine._load_file(STRATEGY_PATH)

    assert not strategy.matrix_strategy.compute_signals(_panel("300001.SZ"), {}).entry.any()
    assert not strategy.matrix_strategy.compute_signals(_panel(name="*ST样本"), {}).entry.any()


def test_night_grass_requires_confirmation_volume_above_eighty_percent_of_t2():
    strategy = StrategyEngine._load_file(STRATEGY_PATH)

    signals = strategy.matrix_strategy.compute_signals(
        _panel(confirmation_volume=80.0),
        {},
    )
    assert not signals.entry.any()


def test_night_grass_requires_signal_close_strictly_above_limit_up_price():
    strategy = StrategyEngine._load_file(STRATEGY_PATH)
    market = _panel()
    market.fields["raw_close"].flags.writeable = True
    market.fields["raw_close"][-1, 0] = market.fields["raw_close"][-3, 0]
    market.fields["raw_close"].flags.writeable = False

    signals = strategy.matrix_strategy.compute_signals(market, {})

    assert not signals.entry.any()


def test_night_grass_requires_both_signal_day_wicks_at_least_half_percent():
    strategy = StrategyEngine._load_file(STRATEGY_PATH)
    missing_upper = _panel()
    missing_upper.high.flags.writeable = True
    missing_upper.high[-1, 0] = 10.95
    missing_upper.high.flags.writeable = False
    missing_lower = _panel()
    missing_lower.low.flags.writeable = True
    missing_lower.low[-1, 0] = 10.80
    missing_lower.low.flags.writeable = False

    assert not strategy.matrix_strategy.compute_signals(missing_upper, {}).entry.any()
    assert not strategy.matrix_strategy.compute_signals(missing_lower, {}).entry.any()


def test_night_grass_rejects_gain_above_eighteen_percent_in_five_days():
    strategy = StrategyEngine._load_file(STRATEGY_PATH)
    market = _panel()
    market.close.flags.writeable = True
    market.close[-6, 0] = market.close[-1, 0] / 1.181
    market.close.flags.writeable = False

    assert not strategy.matrix_strategy.compute_signals(market, {}).entry.any()


def test_night_grass_allows_exactly_eighteen_percent_gain_in_five_days():
    strategy = StrategyEngine._load_file(STRATEGY_PATH)
    market = _panel()
    market.close.flags.writeable = True
    market.close[-6, 0] = market.close[-1, 0] / 1.18
    market.close.flags.writeable = False

    assert strategy.matrix_strategy.compute_signals(market, {}).entry[-1, 0] == 1


def test_night_grass_rejects_gain_above_twenty_five_percent_in_ten_days():
    strategy = StrategyEngine._load_file(STRATEGY_PATH)
    market = _panel()
    market.close.flags.writeable = True
    market.close[-11, 0] = market.close[-1, 0] / 1.251
    market.close.flags.writeable = False

    assert not strategy.matrix_strategy.compute_signals(market, {}).entry.any()


def test_night_grass_allows_exactly_twenty_five_percent_gain_in_ten_days():
    strategy = StrategyEngine._load_file(STRATEGY_PATH)
    market = _panel()
    market.close.flags.writeable = True
    market.close[-11, 0] = market.close[-1, 0] / 1.25
    market.close.flags.writeable = False

    assert strategy.matrix_strategy.compute_signals(market, {}).entry[-1, 0] == 1


def test_night_grass_strategy_params_override_formula_thresholds():
    strategy = StrategyEngine._load_file(STRATEGY_PATH)

    strict = strategy.matrix_strategy.compute_signals(
        _panel(),
        {"recent_gain_max_pct": 10.0},
    )
    disabled = strategy.matrix_strategy.compute_signals(
        _panel(next_close=10.91),
        {"sell_next_day_profit": False},
    )

    assert not strict.entry.any()
    assert not disabled.exit.any()


def test_night_grass_conditional_stop_requires_close_below_both_mas():
    strategy = StrategyEngine._load_file(STRATEGY_PATH)
    market = _panel()
    market.close.flags.writeable = True
    market.close[-1, 0] = 9.0
    market.close.flags.writeable = False

    stop_mask = strategy.matrix_strategy.compute_conditional_stop(market, {})
    disabled = strategy.matrix_strategy.compute_conditional_stop(
        market,
        {"use_ma_loss_stop": False},
    )

    assert stop_mask[-1, 0] == 1
    assert not disabled.any()


def test_night_grass_requires_ma5_above_rising_ma60():
    strategy = StrategyEngine._load_file(STRATEGY_PATH)
    rising = _panel()
    falling = _panel()
    falling.close.flags.writeable = True
    falling.close[-61, 0] = falling.close[-1, 0] + 0.1
    falling.close.flags.writeable = False

    assert strategy.matrix_strategy.compute_signals(rising, {}).entry[-1, 0] == 1
    assert not strategy.matrix_strategy.compute_signals(falling, {}).entry.any()


def test_night_grass_scales_in_on_next_day_decline_above_limit_price_and_plans_exit():
    strategy = StrategyEngine._load_file(STRATEGY_PATH)
    market = _panel(next_close=10.80, third_close=10.90)
    signals = strategy.matrix_strategy.compute_signals(market, {})

    plan = strategy.matrix_strategy.compute_execution_plan(market, {}, signals)

    assert plan["scale_in"][-2, 0] == 1
    assert plan["forced_exit_price"][-1, 0] == 10.90


def test_night_grass_scales_in_on_decline_even_when_low_breaks_limit_price():
    strategy = StrategyEngine._load_file(STRATEGY_PATH)
    market = _panel(next_close=10.80, third_close=10.90)
    market.fields["raw_low"].flags.writeable = True
    market.fields["raw_low"][-2, 0] = 10.22
    market.fields["raw_low"].flags.writeable = False
    signals = strategy.matrix_strategy.compute_signals(market, {})

    plan = strategy.matrix_strategy.compute_execution_plan(market, {}, signals)

    assert plan["scale_in"][-2, 0] == 1
    assert plan["forced_exit_price"][-1, 0] == 10.90


def test_night_grass_execution_doubles_shares_and_exits_at_signal_close():
    strategy = StrategyEngine._load_file(STRATEGY_PATH)
    market = _panel(next_close=10.80, third_close=10.90)
    signals = strategy.matrix_strategy.compute_signals(market, {})
    plan = strategy.matrix_strategy.compute_execution_plan(market, {}, signals)
    execution = build_market_matrix_from_signals(market, signals, **plan)

    engine = BacktestEngine(repo=None)
    next_day = execution.timestamp_labels[-2][:10]
    minute_rows = np.array([[10.90, 10.95, 10.70, 10.80, 1, 1, 570]], dtype=float)
    engine._load_minute_for_fills = lambda *_args, **_kwargs: {  # type: ignore[method-assign]
        (execution.symbols[0], next_day): minute_rows
    }
    result = engine.simulate_independent_market_matrix(
        execution,
        raw_candidates=1,
        config=MatcherConfig(
            matching="close_t",
            entry_fill="close_t",
            exit_fill="close_t",
            fees_pct=0,
            slippage_bps=0,
            take_profit_pct=None,
            max_hold_days=5,
            minute_fill=True,
        ),
    )

    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.shares == 200
    assert trade.entry_price == 10.85
    assert trade.exit_price == 10.90
    assert trade.exit_reason == "planned_exit"

    portfolio_engine = BacktestEngine(repo=None)
    portfolio_engine._load_minute_for_fills = engine._load_minute_for_fills  # type: ignore[method-assign]
    portfolio = portfolio_engine.simulate_market_matrix(
        execution,
        MatcherConfig(
            matching="close_t",
            entry_fill="close_t",
            exit_fill="close_t",
            fees_pct=0,
            slippage_bps=0,
            take_profit_pct=None,
            max_hold_days=5,
            max_positions=1,
            max_exposure_pct=1,
            initial_capital=100_000,
            reserve_scale_in=True,
            minute_fill=True,
        ),
    )
    assert portfolio.trades[0].shares == 9000
    assert portfolio.trades[0].exit_price == 10.90
    assert portfolio.trades[0].exit_reason == "planned_exit"


def test_night_grass_second_day_exit_priority():
    before_ten_four = np.array([[10.9, 11.34, 10.8, 11.2, 1, 1, 599]], dtype=float)
    after_ten_four = np.array([[10.9, 11.34, 10.8, 11.2, 1, 1, 600]], dtype=float)

    assert BacktestEngine._resolve_second_day_exit(
        before_ten_four, 10.9, 11.34, 11.2
    )[0] == "take_profit_4_before_10"
    assert BacktestEngine._resolve_second_day_exit(
        after_ten_four, 10.9, 11.34, 11.2
    )[0] == "take_profit_2"
    assert BacktestEngine._resolve_second_day_exit(
        np.array([[10.9, 11.0, 10.8, 10.95, 1, 1, 570]], dtype=float),
        10.9,
        11.0,
        10.95,
    )[0] == "second_day_red_close"
    assert BacktestEngine._resolve_second_day_exit(
        None, 13.93, 13.88, 13.30
    ) == (None, None)


def test_night_grass_third_day_uses_close_when_signal_price_is_not_reached():
    strategy = StrategyEngine._load_file(STRATEGY_PATH)
    market = _panel(next_close=10.80, third_close=10.70)
    signals = strategy.matrix_strategy.compute_signals(market, {})
    plan = strategy.matrix_strategy.compute_execution_plan(market, {}, signals)
    execution = build_market_matrix_from_signals(market, signals, **plan)
    engine = BacktestEngine(repo=None)
    next_day = execution.timestamp_labels[-2][:10]
    engine._load_minute_for_fills = lambda *_args, **_kwargs: {  # type: ignore[method-assign]
        (execution.symbols[0], next_day): np.array(
            [[10.9, 10.95, 10.7, 10.8, 1, 1, 571]], dtype=float
        )
    }

    result = engine.simulate_independent_market_matrix(
        execution,
        raw_candidates=1,
        config=MatcherConfig(
            matching="close_t",
            entry_fill="close_t",
            exit_fill="close_t",
            fees_pct=0,
            slippage_bps=0,
            take_profit_pct=None,
            max_hold_days=5,
            minute_fill=True,
        ),
    )

    assert result.trades[0].exit_price == 10.70
    assert result.trades[0].exit_reason == "planned_close_exit"


def test_shared_service_uses_fill_defaults_and_execution_plan():
    from types import SimpleNamespace

    from app.backtest.strategy import (
        BacktestResultPolicy,
        StrategyBacktestConfig,
        StrategyBacktestService,
    )

    market = _panel(next_close=10.80, third_close=10.90)

    class FixtureEngine(BacktestEngine):
        def load_market_data_matrix_for_backtest(self, *args, **kwargs):
            return market

        def _load_minute_for_fills(self, *args, **kwargs):
            return {(market.symbols[0], market.timestamp_labels[-2][:10]): np.array(
                [[10.90, 10.95, 10.70, 10.80, 1, 1, 570]], dtype=float
            )}

    engine = StrategyEngine([PLUGIN_DIR])
    service = StrategyBacktestService(FixtureEngine(SimpleNamespace()), engine)
    result = service.run(
        StrategyBacktestConfig(
            strategy_id="night_grass_close_enhanced",
            symbols=None,
            start=date(2026, 1, 1),
            end=date(2026, 3, 5),
            matching="open_t+1",
            fees_pct=0,
            slippage_bps=0,
            max_positions=1,
            initial_capital=100_000,
            overrides={"basic_filter": {"enabled": False}},
        ),
        result_policy=BacktestResultPolicy(include_benchmark=False, include_monte_carlo=False),
    )
    assert result.error is None
    assert len(result.trades) == 1
    assert result.trades[0]["shares"] == 9000
    assert result.trades[0]["exit_reason"] == "planned_exit"
    assert result.trades[0]["entry_price"] == 10.85
