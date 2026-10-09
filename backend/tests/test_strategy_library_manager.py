from __future__ import annotations

import threading
from datetime import date

import pytest

from app.strategy_library.contracts import (
    BacktestPeriod,
    BacktestWindow,
    StrategyLibraryTask,
    StrategyLibraryTaskItem,
    StrategyLibraryTaskStatus,
)
from app.strategy_library.manager import (
    StrategyLibraryManager,
    StrategyLibraryTaskConflict,
)


class MemoryStore:
    def __init__(self):
        self.tasks = {}
        self.results = {}

    def get_tasks(self):
        return list(self.tasks.values())

    def save_task(self, task):
        self.tasks[task["id"]] = task

    def save_result(self, strategy_id, period, summary):
        self.results[(strategy_id, period)] = summary


def _result():
    return {"stats": {"total_return": 0.1, "max_drawdown": -0.05, "win_rate": 0.6}}


def _manager(runner, strategy_ids=("builtin_a", "builtin_b")):
    return StrategyLibraryManager(
        runner=runner,
        store=MemoryStore(),
        strategy_ids=lambda: list(strategy_ids),
        latest_trading_day=lambda: date(2026, 10, 8),
    )


def test_one_window_failure_does_not_stop_remaining_windows():
    def runner(strategy_id, window, cancel_event, _progress_cb, _config):
        if (strategy_id, window.period) == ("builtin_a", BacktestPeriod.THREE_MONTHS):
            raise RuntimeError("synthetic failure")
        return _result()

    manager = _manager(runner)
    task = manager.start("user-a", ["builtin_a", "builtin_b"])
    manager.wait(task.id, timeout=10)

    finished = manager.get_task("user-a", task.id)
    assert finished.state == StrategyLibraryTaskStatus.COMPLETED_WITH_ERRORS
    assert finished.item("builtin_a", BacktestPeriod.THREE_MONTHS).status == "failed"
    assert finished.item("builtin_a", BacktestPeriod.SIX_MONTHS).status == "completed"
    assert finished.item("builtin_b", BacktestPeriod.THREE_MONTHS).status == "completed"


def test_cancel_stops_after_current_backtest():
    entered = threading.Event()
    release = threading.Event()

    def runner(_strategy_id, _window, _cancel_event, _progress_cb, _config):
        entered.set()
        assert release.wait(10)
        return _result()

    manager = _manager(runner)
    task = manager.start("user-a", ["builtin_a", "builtin_b"])
    assert entered.wait(5)
    assert manager.cancel("user-a", task.id) is True
    release.set()
    manager.wait(task.id, timeout=10)

    finished = manager.get_task("user-a", task.id)
    assert finished.state == StrategyLibraryTaskStatus.CANCELLED
    assert finished.item("builtin_a", BacktestPeriod.THREE_MONTHS).status == "completed"
    assert all(item.status == "cancelled" for item in finished.items[1:])


def test_active_task_is_scoped_and_duplicate_run_is_rejected():
    entered = threading.Event()
    release = threading.Event()

    def runner(_strategy_id, _window, _cancel_event, _progress_cb, _config):
        entered.set()
        release.wait(10)
        return _result()

    manager = _manager(runner, ("builtin_a",))
    task = manager.start("user-a", ["builtin_a"])
    assert entered.wait(5)
    assert manager.get_task("user-b", task.id) is None
    with pytest.raises(StrategyLibraryTaskConflict):
        manager.start("user-a", ["builtin_a"])
    release.set()
    manager.wait(task.id, timeout=10)


def test_failed_period_can_be_retried_without_rerunning_successes():
    attempts = {}

    def runner(strategy_id, window, _cancel_event, _progress_cb, _config):
        key = (strategy_id, window.period)
        attempts[key] = attempts.get(key, 0) + 1
        if key == ("builtin_a", BacktestPeriod.THREE_MONTHS) and attempts[key] == 1:
            raise RuntimeError("first attempt failed")
        return _result()

    manager = _manager(runner, ("builtin_a",))
    task = manager.start("user-a", ["builtin_a"])
    manager.wait(task.id, timeout=10)
    retried = manager.retry_failed("user-a", task.id)
    manager.wait(retried.id, timeout=10)

    assert attempts[("builtin_a", BacktestPeriod.THREE_MONTHS)] == 2
    assert attempts[("builtin_a", BacktestPeriod.SIX_MONTHS)] == 1
    assert manager.get_task("user-a", task.id).item(
        "builtin_a", BacktestPeriod.THREE_MONTHS
    ).status == "completed"


def test_running_task_is_marked_interrupted_after_manager_restart():
    store = MemoryStore()
    window = BacktestWindow(
        BacktestPeriod.THREE_MONTHS,
        date(2026, 7, 8),
        date(2026, 10, 8),
        availability="available",
    )
    task = StrategyLibraryTask(
        id="persisted-task",
        user_id="user-a",
        state=StrategyLibraryTaskStatus.RUNNING,
        created_at="2026-10-08T10:00:00+00:00",
        updated_at="2026-10-08T10:00:00+00:00",
        items=[StrategyLibraryTaskItem(
            strategy_id="builtin_a",
            period=BacktestPeriod.THREE_MONTHS,
            window=window,
            status="running",
        ), StrategyLibraryTaskItem(
            strategy_id="builtin_b",
            period=BacktestPeriod.SIX_MONTHS,
            window=BacktestWindow(
                BacktestPeriod.SIX_MONTHS,
                date(2026, 4, 8),
                date(2026, 10, 8),
                availability="available",
            ),
            status="queued",
        )],
        current_strategy_id="builtin_a",
        current_period=BacktestPeriod.THREE_MONTHS,
    )
    store.save_task(task.to_dict())

    manager = StrategyLibraryManager(
        runner=lambda *_args: _result(),
        store=store,
        strategy_ids=lambda: ["builtin_a"],
        latest_trading_day=lambda: date(2026, 10, 8),
    )

    recovered = manager.get_task("user-a", "persisted-task")
    assert recovered.state == StrategyLibraryTaskStatus.INTERRUPTED
    assert recovered.item("builtin_a", BacktestPeriod.THREE_MONTHS).status == "failed"
    assert recovered.item("builtin_b", BacktestPeriod.SIX_MONTHS).status == "failed"


def test_result_configuration_fingerprint_includes_complete_window():
    from app.strategy_library.manager import _summary

    first = StrategyLibraryTaskItem(
        "demo", BacktestPeriod.THREE_MONTHS,
        BacktestWindow(BacktestPeriod.THREE_MONTHS, date(2026, 7, 8), date(2026, 10, 8), date(2026, 7, 9), date(2026, 10, 7), "available"),
    )
    second = StrategyLibraryTaskItem(
        "demo", BacktestPeriod.THREE_MONTHS,
        BacktestWindow(BacktestPeriod.THREE_MONTHS, date(2026, 7, 8), date(2026, 10, 8), date(2026, 7, 10), date(2026, 10, 7), "available"),
    )

    assert _summary(first, {"stats": {"total_return": 0.1}}, {}).config_fingerprint != _summary(second, {"stats": {"total_return": 0.1}}, {}).config_fingerprint
