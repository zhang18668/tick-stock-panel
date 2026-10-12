from datetime import date

import pytest

from app.strategy_optimizer.gateway import StrategyOptimizationGateway


class FakeResult:
    def __init__(self, stats, error=None):
        self.stats = stats
        self.error = error
        self.trades = [
            {"symbol": "000001.SZ", "entry_date": "2024-01-02", "exit_date": "2024-01-03"}
        ]


class FakeService:
    def __init__(self):
        self.configs = []

    def run(self, config, **kwargs):
        self.configs.append(config)
        return FakeResult(
            {"total_return": 0.1, "max_drawdown": -0.1, "win_rate": 0.6, "n_trades": 8}
        )


class FakeStrategy:
    def __init__(self):
        self.meta = {
            "id": "demo",
            "name": "Demo",
            "asset_type": "stock",
            "params": [
                {"id": "window", "type": "int", "default": 10, "min": 2, "max": 20, "step": 1}
            ],
        }
        self.entry_signals = ["buy_a"]
        self.exit_signals = ["sell_a"]


class FakeEngine:
    def get(self, strategy_id):
        assert strategy_id == "demo"
        return FakeStrategy()

    def strategy_definitions(self):
        return (FakeStrategy(),)


class FakeRepo:
    def get_matrix_data_generation(self, asset_type):
        return f"g-{asset_type}"


def test_lists_optimizable_strategies_from_real_strategy_definition_shape():
    gateway = StrategyOptimizationGateway(FakeService(), FakeEngine(), repository=FakeRepo())

    assert gateway.list_optimizable_strategies() == [
        {
            "strategy_id": "demo",
            "name": "Demo",
            "asset_type": "stock",
            "optimizable": True,
            "reason": None,
        }
    ]


def test_gateway_evaluates_candidates_and_oos_with_shared_backtest_service():
    service = FakeService()
    gateway = StrategyOptimizationGateway(service, FakeEngine(), repository=FakeRepo())
    request = {
        "strategy_id": "demo",
        "validated": {
            "strategy_id": "demo",
            "asset_type": "stock",
            "start": "2023-01-01",
            "end": "2025-01-01",
            "parameters": {},
            "max_rounds": 1,
            "candidates_per_round": 2,
            "total_candidates": 2,
        },
        "train_days": 252,
        "test_days": 63,
        "step_days": 63,
        "min_trades": 1,
    }
    events = []
    result = gateway.run_optimization(request, events.append, __import__("threading").Event())
    assert result["top3"]
    assert result["data_generation"] == "g-stock"
    assert all(config.start >= date(2023, 1, 1) for config in service.configs)


def test_robust_preview_fails_closed_without_historical_calendar_source():
    gateway = StrategyOptimizationGateway(FakeService(), FakeEngine(), repository=FakeRepo())

    with pytest.raises(ValueError, match="historical trading calendar"):
        gateway.preview_robust_config(
            {
                "start": "2020-01-01",
                "end": "2024-12-31",
                "asset_type": "stock",
                "robust_config": {"layout": "holdout"},
            }
        )


def test_robust_preview_splits_default_boundaries_from_injected_calendar():
    days = [date(2020, 1, day) for day in range(1, 11)]
    gateway = StrategyOptimizationGateway(
        FakeService(),
        FakeEngine(),
        repository=FakeRepo(),
        trading_dates_reader=lambda _start, _end, _asset: days,
    )

    preview = gateway.preview_robust_config(
        {
            "start": days[0].isoformat(),
            "end": days[-1].isoformat(),
            "asset_type": "stock",
            "robust_config": {
                "layout": "holdout",
                "boundaries": [day.isoformat() for day in (days[0], days[3], days[6], days[8])],
            },
        }
    )

    assert preview["time_plan"]["development"] == [
        {"id": "development-1", "start": "2020-01-01", "end": "2020-01-03", "role": "development"},
        {"id": "development-2", "start": "2020-01-04", "end": "2020-01-06", "role": "development"},
        {"id": "development-3", "start": "2020-01-07", "end": "2020-01-08", "role": "development"},
    ]
    assert preview["time_plan"]["holdout"]["start"] == "2020-01-09"


def test_gateway_reads_historical_calendar_from_normalized_daily_repository():
    class CalendarRepo(FakeRepo):
        def execute_all(self, sql, params):
            assert "SELECT DISTINCT date FROM kline_daily" in sql
            assert params == [date(2020, 1, 1), date(2020, 1, 10)]
            return [(date(2020, 1, 1),), (date(2020, 1, 2),)]

    gateway = StrategyOptimizationGateway(FakeService(), FakeEngine(), repository=CalendarRepo())

    assert gateway.historical_trading_dates(date(2020, 1, 1), date(2020, 1, 10)) == (
        date(2020, 1, 1),
        date(2020, 1, 2),
    )
