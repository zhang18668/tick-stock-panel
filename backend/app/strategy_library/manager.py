from __future__ import annotations

import copy
import hashlib
import json
import math
import threading
import uuid
from datetime import UTC, date, datetime
from typing import Callable

from app.services.heavy_job_limiter import (
    HeavyJobCancelledError,
    shared_heavy_job_limiter,
)
from app.strategy_library.contracts import (
    BacktestPeriod,
    BacktestWindow,
    StrategyLibraryTask,
    StrategyLibraryTaskItem,
    StrategyLibraryTaskStatus,
    StrategyResultSummary,
)
from app.strategy_library.windows import build_rolling_windows


class StrategyLibraryTaskConflict(RuntimeError):
    """A strategy-library task cannot be retried in its current state."""


class StrategyLibraryManager:
    def __init__(
        self,
        *,
        runner: Callable,
        store,
        strategy_ids: Callable[[], list[str]],
        latest_trading_day: Callable[[], date | None],
        window_resolver: Callable[[str, BacktestWindow], BacktestWindow] | None = None,
    ) -> None:
        self.runner = runner
        self.store = store
        self.strategy_ids = strategy_ids
        self.latest_trading_day = latest_trading_day
        self.window_resolver = window_resolver or (lambda _strategy_id, window: window)
        self._tasks: dict[str, StrategyLibraryTask] = {}
        self._cancel_events: dict[str, threading.Event] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._lock = threading.RLock()
        self._load_existing()

    def _load_existing(self) -> None:
        try:
            records = self.store.get_tasks()
        except (AttributeError, TypeError):
            records = []
        for record in records:
            try:
                task = StrategyLibraryTask.from_dict(record)
            except (KeyError, TypeError, ValueError):
                continue
            if task.state in {StrategyLibraryTaskStatus.QUEUED, StrategyLibraryTaskStatus.RUNNING}:
                task.state = StrategyLibraryTaskStatus.INTERRUPTED
                task.current_strategy_id = None
                task.current_period = None
                task.cancel_requested = False
                task.error = "服务重启时任务仍在运行；可重试失败项"
                for item in task.items:
                    if item.status in {"running", "queued"}:
                        item.status = "failed"
                        item.reason = task.error
                self._touch(task)
                self._persist(task)
            self._tasks[task.id] = task
            self._cancel_events[task.id] = threading.Event()

    def start(
        self,
        user_id: str,
        strategy_ids: list[str] | None = None,
        strategy_configs: dict[str, dict] | None = None,
    ) -> StrategyLibraryTask:
        selected_ids = self.strategy_ids() if strategy_ids is None else strategy_ids
        if not selected_ids or any(not isinstance(item, str) or not item.strip() for item in selected_ids):
            raise ValueError("at least one valid strategy id is required")
        selected_ids = list(dict.fromkeys(item.strip() for item in selected_ids))
        latest = self.latest_trading_day()
        if latest is None:
            raise ValueError("本地没有可用于回测的日线交易日期")
        windows = build_rolling_windows(latest)

        with self._lock:
            items = []
            for strategy_id in selected_ids:
                for window in windows:
                    resolved = self.window_resolver(strategy_id, window)
                    status = "unavailable" if resolved.availability == "unavailable" else "queued"
                    items.append(
                        StrategyLibraryTaskItem(
                            strategy_id=strategy_id,
                            period=window.period,
                            window=resolved,
                            status=status,
                            reason=resolved.reason if status == "unavailable" else None,
                        )
                    )
            now = _now()
            task = StrategyLibraryTask(
                id=uuid.uuid4().hex,
                user_id=str(user_id),
                state=StrategyLibraryTaskStatus.QUEUED,
                created_at=now,
                updated_at=now,
                items=items,
                strategy_configs=_safe_config_map(strategy_configs or {}, selected_ids),
            )
            self._tasks[task.id] = task
            cancel_event = threading.Event()
            self._cancel_events[task.id] = cancel_event
            self._persist(task)
            self._start_thread(task.id)
            return copy.deepcopy(task)

    def get_task(self, user_id: str, task_id: str) -> StrategyLibraryTask | None:
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None or task.user_id != str(user_id):
                return None
            return copy.deepcopy(task)

    def cancel(self, user_id: str, task_id: str) -> bool:
        with self._lock:
            task = self._owned_task(user_id, task_id)
            if task.state not in {StrategyLibraryTaskStatus.QUEUED, StrategyLibraryTaskStatus.RUNNING}:
                return False
            task.cancel_requested = True
            self._cancel_events[task_id].set()
            self._touch(task)
            self._persist(task)
            return True

    def retry_failed(
        self,
        user_id: str,
        task_id: str,
        items: list[tuple[str, BacktestPeriod]] | None = None,
    ) -> StrategyLibraryTask:
        with self._lock:
            task = self._owned_task(user_id, task_id)
            if task.state in {StrategyLibraryTaskStatus.QUEUED, StrategyLibraryTaskStatus.RUNNING}:
                raise StrategyLibraryTaskConflict("任务仍在运行，不能同时重试")
            selected = {
                (strategy_id, BacktestPeriod(period)) for strategy_id, period in items
            } if items is not None else None
            failed = [
                item for item in task.items
                if item.status == "failed"
                and (selected is None or (item.strategy_id, item.period) in selected)
            ]
            if selected is not None and len(failed) != len(selected):
                raise ValueError("重试项必须对应此任务中失败的策略周期")
            if not failed:
                raise ValueError("没有可重试的失败项")
            for item in failed:
                item.status = "queued"
                item.reason = None
                item.progress = None
            task.state = StrategyLibraryTaskStatus.QUEUED
            task.cancel_requested = False
            task.error = None
            task.current_strategy_id = None
            task.current_period = None
            self._cancel_events[task_id] = threading.Event()
            self._touch(task)
            self._persist(task)
            self._start_thread(task_id)
            return copy.deepcopy(task)

    def wait(self, task_id: str, timeout: float | None = None) -> None:
        with self._lock:
            thread = self._threads.get(task_id)
        if thread is not None:
            thread.join(timeout)

    def shutdown(self, timeout: float = 5.0) -> None:
        with self._lock:
            for task_id, task in self._tasks.items():
                if task.state in {StrategyLibraryTaskStatus.QUEUED, StrategyLibraryTaskStatus.RUNNING}:
                    self._cancel_events[task_id].set()
                    task.cancel_requested = True
                    self._touch(task)
                    self._persist(task)
            threads = list(self._threads.values())
        deadline = __import__("time").monotonic() + timeout
        for thread in threads:
            thread.join(max(0.0, deadline - __import__("time").monotonic()))

    def _owned_task(self, user_id: str, task_id: str) -> StrategyLibraryTask:
        task = self._tasks.get(task_id)
        if task is None or task.user_id != str(user_id):
            raise KeyError(task_id)
        return task

    def _start_thread(self, task_id: str) -> None:
        thread = threading.Thread(target=self._run, args=(task_id,), daemon=True)
        self._threads[task_id] = thread
        thread.start()

    def _run(self, task_id: str) -> None:
        with self._lock:
            task = self._tasks[task_id]
            cancel_event = self._cancel_events[task_id]
            if cancel_event.is_set():
                self._finish_cancelled(task)
                return
            task.state = StrategyLibraryTaskStatus.RUNNING
            self._touch(task)
            self._persist(task)

        for item in task.items:
            with self._lock:
                if item.status != "queued":
                    continue
                if cancel_event.is_set():
                    self._finish_cancelled(task)
                    return
                task.current_strategy_id = item.strategy_id
                task.current_period = item.period
                item.status = "running"
                item.attempts += 1
                item.started_at = _now()
                item.progress = None
                self._touch(task)
                self._persist(task)

            try:
                with shared_heavy_job_limiter.slot("normal", cancel_event=cancel_event):
                    result = self.runner(
                        item.strategy_id,
                        item.window,
                        cancel_event,
                        lambda progress: self._progress(task_id, item, progress),
                        task.strategy_configs.get(item.strategy_id, {}),
                    )
                if cancel_event.is_set() and isinstance(result, dict) and result.get("error") == "cancelled":
                    raise HeavyJobCancelledError("回测已取消")
                summary = _summary(item, result, task.strategy_configs.get(item.strategy_id, {}))
                self.store.save_result(item.strategy_id, item.period, summary)
            except HeavyJobCancelledError as exc:
                with self._lock:
                    item.status = "cancelled"
                    item.reason = str(exc)
                    item.completed_at = _now()
                    self._touch(task)
                    self._persist(task)
                    self._finish_cancelled(task)
                return
            except Exception as exc:
                with self._lock:
                    item.status = "failed"
                    item.reason = str(exc) or type(exc).__name__
                    item.completed_at = _now()
                    task.current_strategy_id = None
                    task.current_period = None
                    self._touch(task)
                    self._persist(task)
                continue

            with self._lock:
                item.status = "completed"
                item.completed_at = _now()
                item.progress = {"phase": "completed"}
                task.current_strategy_id = None
                task.current_period = None
                self._touch(task)
                self._persist(task)

        with self._lock:
            if cancel_event.is_set():
                self._finish_cancelled(task)
                return
            has_errors = any(item.status in {"failed", "unavailable"} for item in task.items)
            task.state = (
                StrategyLibraryTaskStatus.COMPLETED_WITH_ERRORS
                if has_errors else StrategyLibraryTaskStatus.COMPLETED
            )
            task.current_strategy_id = None
            task.current_period = None
            self._touch(task)
            self._persist(task)

    def _progress(self, task_id: str, item: StrategyLibraryTaskItem, progress: dict) -> None:
        if not isinstance(progress, dict):
            return
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None or item.status != "running":
                return
            item.progress = _safe_progress(progress)
            task.updated_at = _now()

    def _finish_cancelled(self, task: StrategyLibraryTask) -> None:
        for item in task.items:
            if item.status == "queued":
                item.status = "cancelled"
                item.reason = "任务已取消"
                item.completed_at = _now()
        task.state = StrategyLibraryTaskStatus.CANCELLED
        task.current_strategy_id = None
        task.current_period = None
        task.cancel_requested = True
        self._touch(task)
        self._persist(task)

    def _touch(self, task: StrategyLibraryTask) -> None:
        task.updated_at = _now()

    def _persist(self, task: StrategyLibraryTask) -> None:
        self.store.save_task(task.to_dict())


def _summary(
    item: StrategyLibraryTaskItem,
    result: dict,
    config: dict,
) -> StrategyResultSummary:
    if not isinstance(result, dict):
        raise TypeError("backtest worker returned a malformed result")
    if result.get("error"):
        if result["error"] == "cancelled":
            raise HeavyJobCancelledError("回测已取消")
        raise RuntimeError(str(result["error"]))
    stats = result.get("stats")
    if not isinstance(stats, dict):
        raise ValueError("回测结果缺少统计指标")
    trades = result.get("trades")
    trade_count = stats.get("trade_count", stats.get("n_trades"))
    if type(trade_count) is not int and isinstance(trades, list):
        trade_count = len(trades)

    fingerprint_source = json.dumps(
        {
            "strategy_id": item.strategy_id,
            "period": item.period.value,
            "window": {
                "requested_start": item.window.requested_start,
                "requested_end": item.window.requested_end,
                "actual_start": item.window.actual_start,
                "actual_end": item.window.actual_end,
            },
            "config": config,
        },
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )
    return StrategyResultSummary(
        period=item.period,
        actual_start=item.window.actual_start or item.window.requested_start,
        actual_end=item.window.actual_end or item.window.requested_end,
        total_return=_finite_number(stats.get("total_return")),
        max_drawdown=_finite_number(stats.get("max_drawdown")),
        sharpe=_finite_number(stats.get("sharpe")),
        win_rate=_finite_number(stats.get("win_rate")),
        profit_factor=_finite_number(stats.get("profit_factor")),
        benchmark_return=_finite_number(stats.get("benchmark_return")),
        excess_return=_finite_number(stats.get("excess_return", stats.get("excess"))),
        trade_count=trade_count if type(trade_count) is int else None,
        config_fingerprint=hashlib.sha256(fingerprint_source.encode()).hexdigest(),
        source_fingerprint=config.get("source_fingerprint")
        if isinstance(config.get("source_fingerprint"), str) else None,
        updated_at=_now(),
    )


def _finite_number(value) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(float(value)) else None


def _safe_config_map(raw: dict, strategy_ids: list[str]) -> dict[str, dict]:
    return {
        strategy_id: copy.deepcopy(raw.get(strategy_id, {}))
        for strategy_id in strategy_ids
        if isinstance(raw.get(strategy_id, {}), dict)
    }


def _safe_progress(raw: dict) -> dict:
    out = {}
    for key, value in raw.items():
        if not isinstance(key, str):
            continue
        if value is None or isinstance(value, (str, bool, int)):
            out[key] = value
        elif isinstance(value, float):
            out[key] = value if math.isfinite(value) else None
    return out


def _now() -> str:
    return datetime.now(UTC).isoformat()
