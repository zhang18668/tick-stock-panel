from __future__ import annotations

from datetime import date
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.strategy.engine import StrategyDef
from app.strategy_library.api import build_router
from app.strategy_library.api import _resolve_window
from app.strategy_library.contracts import BacktestPeriod, BacktestWindow
from app.strategy_library.manager import StrategyLibraryManager


class FakeEngine:
    def __init__(self):
        self.strategy = StrategyDef(
            meta={
                "id": "demo",
                "name": "演示策略",
                "description": "策略规则说明",
                "rules": ["条件甲", "条件乙"],
                "asset_types": ["stock"],
                "timeframes": ["1d"],
            },
            basic_filter={},
            entry_signals=["signal_entry"],
            exit_signals=["signal_exit"],
            stop_loss=-0.08,
            trailing_stop=None,
            trailing_take_profit_activate=None,
            trailing_take_profit_drawdown=None,
            max_hold_days=10,
            filter_fn=None,
            filter_history_fn=None,
            lookback_days=60,
            source="builtin",
            execution_backend="matrix_native",
        )

    def strategy_definitions(self):
        return (self.strategy,)

    def get(self, strategy_id):
        if strategy_id != "demo":
            raise ValueError("unknown strategy")
        return self.strategy

    def list_strategies(self, include_research=False):
        return [{**self.strategy.meta, "source": "builtin", "execution_backend": "matrix_native"}]


class FakeRepo:
    store = SimpleNamespace(data_dir=Path("."))

    def latest_daily_date(self):
        return date(2026, 10, 8)

    def earliest_daily_date(self):
        return date(2023, 1, 3)

    def execute_all(self, _sql, _params=None):
        return []


def _client(*, user_id="alice", owned_ids=frozenset()):
    import app.strategy_library.api as library_api

    app = FastAPI()

    @app.middleware("http")
    async def set_user(request, call_next):
        if user_id is not None:
            request.state.current_user = SimpleNamespace(id=user_id, is_admin=False)
            request.state.owned_strategy_ids = owned_ids
            request.state.installed_strategy_ids = frozenset()
            request.state.strategy_overrides = {}
        return await call_next(request)

    app.state.strategy_engine = FakeEngine()
    app.state.repo = FakeRepo()
    app.include_router(build_router())
    return TestClient(app), library_api, app


def test_library_endpoint_returns_strategy_rules_and_execution_details():
    client, _, _ = _client()

    response = client.get("/api/strategy-library")

    assert response.status_code == 200
    payload = response.json()
    assert payload["strategies"][0]["rules"] == ["条件甲", "条件乙"]
    assert payload["strategies"][0]["execution"]["timeframes"] == ["1d"]
    assert payload["latest_trading_day"] == "2026-10-08"


def test_job_rejects_unknown_strategy_with_structured_error():
    client, _, _ = _client()

    response = client.post(
        "/api/strategy-library/jobs",
        json={"strategy_ids": ["../secret"]},
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "invalid_strategy_id"


def test_user_cannot_read_or_cancel_another_users_task():
    client, _, app = _client(user_id="bob")

    manager = StrategyLibraryManager(
        runner=lambda *_args: {"stats": {"total_return": 0.1}},
        store=SimpleNamespace(get_tasks=lambda: [], save_task=lambda _task: None, save_result=lambda *_args: None),
        strategy_ids=lambda: ["demo"],
        latest_trading_day=lambda: date(2026, 10, 8),
    )
    task = manager.start("alice", ["demo"])
    app.state.strategy_library_managers = {"bob": manager}
    manager.wait(task.id, timeout=10)

    assert client.get(f"/api/strategy-library/jobs/{task.id}").status_code == 404
    assert client.post(f"/api/strategy-library/jobs/{task.id}/cancel").status_code == 404


def test_minute_window_is_unavailable_when_any_trading_day_lacks_minute_data(monkeypatch):
    import app.strategy_library.api as library_api

    monkeypatch.setattr(library_api.settings, "backtest_range_guard", False)
    engine = FakeEngine()
    engine.strategy.execution_backend = "minute_filter"
    repo = SimpleNamespace(
        earliest_minute_date=lambda: date(2026, 1, 1),
        latest_minute_date_global=lambda: date(2026, 10, 8),
        execute_all=lambda *_args: [(date(2026, 7, 1),), (date(2026, 7, 2),)],
        list_minute_dates=lambda *_args: [date(2026, 7, 1)],
    )
    window = BacktestWindow(
        BacktestPeriod.THREE_MONTHS,
        date(2026, 7, 1),
        date(2026, 10, 8),
    )

    resolved = _resolve_window(repo, engine, "demo", window)

    assert resolved.availability == "unavailable"
    assert resolved.reason == "分钟 K 数据缺少 1 个交易日"


def test_minute_coverage_query_failure_returns_unavailable(monkeypatch):
    import app.strategy_library.api as library_api

    monkeypatch.setattr(library_api.settings, "backtest_range_guard", False)
    engine = FakeEngine()
    engine.strategy.execution_backend = "minute_filter"

    class Repo:
        earliest_minute_date = lambda self: date(2026, 1, 1)
        latest_minute_date_global = lambda self: date(2026, 10, 8)
        list_minute_dates = lambda self, *_args: []

        def execute_all(self, *_args):
            raise RuntimeError("storage unavailable")

    window = BacktestWindow(
        BacktestPeriod.THREE_MONTHS,
        date(2026, 7, 1),
        date(2026, 10, 8),
    )
    resolved = _resolve_window(Repo(), engine, "demo", window)

    assert resolved.availability == "unavailable"
    assert resolved.reason == "无法确认分钟 K 窗口完整性"


def test_one_year_window_respects_enabled_server_range_guard(monkeypatch):
    import app.strategy_library.api as library_api

    monkeypatch.setattr(library_api.settings, "backtest_range_guard", True)
    window = BacktestWindow(
        BacktestPeriod.TWELVE_MONTHS,
        date(2025, 10, 8),
        date(2026, 10, 8),
    )

    resolved = _resolve_window(FakeRepo(), FakeEngine(), "demo", window)

    assert resolved.availability == "unavailable"
    assert resolved.reason == library_api.BACKTEST_SERVER_GUARD_MESSAGE
