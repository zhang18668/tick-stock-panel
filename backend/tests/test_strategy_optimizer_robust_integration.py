from __future__ import annotations

import threading
from datetime import date, timedelta

import polars as pl

from app.backtest.engine import BacktestEngine
from app.backtest.matrix import build_market_data_matrix
from app.backtest.strategy import StrategyBacktestService
from app.strategy.engine import StrategyEngine
from app.strategy_optimizer.gateway import StrategyOptimizationGateway


class _Repo:
    def get_matrix_data_generation(self, _asset_type):
        return "synthetic-generation"

    def get_index_daily(self, *_args, **_kwargs):
        return pl.DataFrame()


def _write_strategy(path):
    path.write_text(
        '''import numpy as np
from app.backtest.matrix import make_signal_matrix

META = {"id": "robust_e2e", "name": "稳健集成策略", "asset_type": "stock", "params": [
    {"id": "window", "type": "int", "default": 2, "min": 1, "max": 3, "step": 1}
]}
ENTRY_SIGNALS = ["always_buy"]
EXIT_SIGNALS = ["never_sell"]
EXECUTION_BACKEND = "matrix_native"

class AlwaysEntry:
    def required_fields(self): return frozenset({"close"})
    def required_warmup_bars(self, params): return 0
    def compute_signals(self, market, params):
        return make_signal_matrix(market.shape,
            entry=np.ones(market.shape, dtype=np.uint8),
            exit=np.zeros(market.shape, dtype=np.uint8),
            entry_signal_code=np.zeros(market.shape, dtype=np.int16),
            exit_signal_code=np.full(market.shape, -1, dtype=np.int16),
            entry_signal_ids=("always_buy",), exit_signal_ids=("never_sell",))

MATRIX_STRATEGY = AlwaysEntry()
''',
        encoding="utf-8",
    )


def test_robust_gateway_uses_real_backtest_service_for_segment_and_continuous_curves(tmp_path):
    dates = tuple(date(2024, 1, 1) + timedelta(days=index) for index in range(12))
    rows = []
    prices = [100, 90, 100, 90, 90, 81, 90, 81, 81, 72.9, 81, 72.9]
    for day, close in zip(dates, prices, strict=True):
        rows.append({
            "symbol": "600000.SH", "date": day, "open": close,
            "high": close, "low": close, "close": close, "volume": 1_000_000,
            "amount": close * 1_000_000,
            "raw_close": close, "raw_high": close, "raw_low": close,
        })
    panel = pl.DataFrame(rows)
    engine = BacktestEngine(_Repo())

    def load_matrix(self, symbols, start, end, feature_plan, asset_type="stock", **_kwargs):
        frame = panel.filter((pl.col("date") >= start) & (pl.col("date") <= end))
        if symbols:
            frame = frame.filter(pl.col("symbol").is_in(symbols))
        columns = [column for column in feature_plan.base_columns if column in frame.columns]
        return build_market_data_matrix(frame.select(columns), field_columns=feature_plan.matrix_columns)

    engine.load_market_data_matrix_for_backtest = load_matrix.__get__(engine)
    strategy_dir = tmp_path / "strategies"
    strategy_dir.mkdir()
    _write_strategy(strategy_dir / "robust_e2e.py")
    strategy_engine = StrategyEngine(strategy_dirs=[strategy_dir])
    service = StrategyBacktestService(engine, strategy_engine)
    configs = []
    original_run = service.run

    def record_run(config, *args, **kwargs):
        configs.append(config)
        return original_run(config, *args, **kwargs)

    service.run = record_run
    gateway = StrategyOptimizationGateway(
        service,
        strategy_engine,
        repository=_Repo(),
        trading_dates_reader=lambda _start, _end, _asset: dates,
    )
    boundaries = [dates[0], dates[4], dates[8]]
    robust_config = {
        "layout": "diagnostic", "neighbor_budget": 20, "neighbor_centers": 1,
        "boundaries": [day.isoformat() for day in boundaries],
        "gates": {
            "max_drawdown": 1, "min_trades": 0, "min_baseline_delta": -1,
            "min_positive_segments": 1, "all_segment_percentile": 0,
            "strong_segment_percentile": 0, "min_stability": 0,
        },
    }
    preview = gateway.preview_robust_config({
        "start": dates[0].isoformat(), "end": dates[-1].isoformat(),
        "asset_type": "stock", "total_candidates": 3, "robust_config": robust_config,
    })
    snapshot = strategy_engine.get("robust_e2e")
    request = {
        "strategy_id": "robust_e2e", "asset_type": "stock",
        "start": dates[0].isoformat(), "end": dates[-1].isoformat(),
        "evaluation_mode": "robust", "mode": "position", "seed": 3,
        "total_candidates": 3, "candidates_per_round": 3, "max_rounds": 1,
        "holding_days": 1, "fees_pct": 0, "slippage_bps": 0,
        "symbols": ["600000.SH"], "robust_config": robust_config,
        "robust_preview": preview, "strategy_snapshot": {
            "strategy_id": "robust_e2e", "entry_signals": snapshot.entry_signals,
            "exit_signals": snapshot.exit_signals,
        },
        "validated": {
            "strategy_id": "robust_e2e", "asset_type": "stock",
            "start": dates[0].isoformat(), "end": dates[-1].isoformat(),
            "parameters": {"window": {"min": 1, "max": 3, "step": 1}},
            "buy_signals": ["always_buy"], "sell_signals": ["never_sell"],
            "total_candidates": 3, "candidates_per_round": 3, "max_rounds": 1,
        },
    }

    result = gateway.run_optimization(request, lambda _event: None, threading.Event())

    robust = result["robust_result"]
    assert result["stop_reason"] == "budget_exhausted"
    continuous_drawdown = robust["continuous_development"]["baseline"]["max_drawdown"]
    segment_drawdowns = [row["metrics"]["max_drawdown"] for row in robust["baseline"]]
    assert continuous_drawdown > max(segment_drawdowns)
    assert robust["continuous_development"]["window"] == {
        "start": dates[0].isoformat(), "end": dates[-1].isoformat(),
    }
    assert all(config.mode == "position" for config in configs)
    assert {config.start for config in configs} >= {dates[0], dates[4], dates[8]}
    assert robust["time_plan"]["holdout"] is None
