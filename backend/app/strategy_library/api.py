from __future__ import annotations

import asyncio
import hashlib
import json
import threading
from dataclasses import replace
from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from app.api.backtest import BACKTEST_MAX_SERVER_DAYS, BACKTEST_SERVER_GUARD_MESSAGE
from app.api.strategy import _all_overrides, _can_access_strategy, _strategy_detail
from app.backtest.strategy import StrategyBacktestConfig
from app.config import settings
from app.persistence.repositories.user_settings import PostgresUserSettingsRepository
from app.services import preferences
from app.strategy.engine import StrategyEngine
from app.strategy_library.contracts import (
    BacktestPeriod,
    BacktestWindow,
    StrategyGroup,
    StrategyLibraryTask,
)
from app.strategy_library.manager import (
    StrategyLibraryManager,
    StrategyLibraryTaskConflict,
)
from app.strategy_library.store import StrategyLibraryStore
from app.user_system.dependencies import require_paid_user

EXTENSION_ID = "strategy.library"
API_PREFIX = "/api/strategy-library"
_MANAGERS_LOCK = threading.Lock()


class _RequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class JobCreateRequest(_RequestModel):
    strategy_ids: list[str] | None = Field(default=None, max_length=500)


class RetryItem(_RequestModel):
    strategy_id: str = Field(min_length=1, max_length=200)
    period: BacktestPeriod


class RetryRequest(_RequestModel):
    items: list[RetryItem] | None = Field(default=None, max_length=500)


class StrategyGroupInput(_RequestModel):
    id: str = Field(min_length=1, max_length=120)
    name: str = Field(min_length=1, max_length=100)
    order: int = Field(ge=0, le=1000)
    strategy_ids: list[str] = Field(default_factory=list, max_length=500)


class GroupsUpdateRequest(_RequestModel):
    groups: list[StrategyGroupInput] = Field(max_length=100)


def build_router() -> APIRouter:
    router = APIRouter(
        prefix=API_PREFIX, tags=["strategy-library"], dependencies=[Depends(require_paid_user)]
    )

    @router.get("")
    def library(request: Request):
        engine = _engine(request)
        overrides = _all_overrides(request)
        strategies = []
        for strategy in engine.strategy_definitions():
            if strategy.meta.get("research_only") or not _can_access_strategy(request, strategy):
                continue
            strategies.append(_strategy_detail(strategy, overrides.get(strategy.meta["id"]), engine))
        store = StrategyLibraryStore()
        latest = _latest_trading_day(request.app.state.repo)
        results = {
            strategy_id: {
                period.value: summary.to_dict()
                for period, summary in periods.items()
            }
            for strategy_id, periods in store.get_results().items()
        }
        current_user = getattr(request.state, "current_user", None)
        recent_tasks = [
            task for task in store.get_tasks()
            if current_user is None or task.get("user_id") == str(current_user.id)
        ][-10:]
        earliest = _earliest_daily_date(request.app.state.repo)
        return {
            "strategies": strategies,
            "groups": [group.to_dict() for group in store.get_groups()],
            "results": results,
            "tasks": recent_tasks,
            "latest_trading_day": latest.isoformat() if latest else None,
            "earliest_daily_date": earliest.isoformat() if earliest else None,
        }

    @router.put("/groups")
    def update_groups(payload: GroupsUpdateRequest, request: Request):
        strategies = _accessible_strategies(request)
        known = {strategy.meta["id"] for strategy in strategies}
        for group in payload.groups:
            for strategy_id in group.strategy_ids:
                if strategy_id not in known:
                    raise HTTPException(
                        422,
                        detail={"code": "invalid_strategy_id", "strategy_id": strategy_id},
                    )
        store = StrategyLibraryStore()
        try:
            store.save_groups([
                StrategyGroup(group.id, group.name.strip(), group.order, tuple(group.strategy_ids))
                for group in payload.groups
            ])
        except ValueError as exc:
            raise HTTPException(422, detail={"code": "invalid_groups", "message": str(exc)}) from exc
        return {"groups": [group.to_dict() for group in store.get_groups()]}

    @router.post("/jobs", status_code=202)
    async def start_job(payload: JobCreateRequest, request: Request):
        accessible = _accessible_strategies(request)
        by_id = {strategy.meta["id"]: strategy for strategy in accessible}
        strategy_ids = list(by_id) if payload.strategy_ids is None else payload.strategy_ids
        configs: dict[str, dict] = {}
        all_overrides = _all_overrides(request)
        for strategy_id in strategy_ids:
            if not isinstance(strategy_id, str) or not strategy_id.strip() or strategy_id not in by_id:
                raise HTTPException(
                    422,
                    detail={"code": "invalid_strategy_id", "strategy_id": str(strategy_id)},
                )
            strategy = by_id[strategy_id]
            strategy_overrides = dict(all_overrides.get(strategy_id) or {})
            asset_types = strategy.meta.get("asset_types", ["stock"])
            asset_type = "stock" if "stock" in asset_types else asset_types[0]
            source_hash = _source_fingerprint(strategy)
            configs[strategy_id] = {
                "asset_type": asset_type,
                "params": StrategyEngine.resolve_params(strategy, overrides=strategy_overrides),
                "overrides": strategy_overrides,
                "source_fingerprint": source_hash,
            }
        try:
            manager = await _manager_for_request(request)
            task = await asyncio.to_thread(
                manager.start,
                _user_scope(request),
                strategy_ids,
                configs,
            )
        except StrategyLibraryTaskConflict as exc:
            raise HTTPException(409, detail={"code": "job_already_running", "message": str(exc)}) from exc
        except ValueError as exc:
            raise HTTPException(409, detail={"code": "job_unavailable", "message": str(exc)}) from exc
        return _task_payload(task)

    @router.get("/jobs/{task_id}")
    async def get_job(task_id: str, request: Request):
        manager = await _manager_for_request(request)
        task = manager.get_task(_user_scope(request), task_id)
        if task is None:
            raise HTTPException(404, detail="strategy library task not found")
        return _task_payload(task)

    @router.post("/jobs/{task_id}/cancel")
    async def cancel_job(task_id: str, request: Request):
        manager = await _manager_for_request(request)
        try:
            accepted = await asyncio.to_thread(
                manager.cancel,
                _user_scope(request),
                task_id,
            )
        except KeyError as exc:
            raise HTTPException(404, detail="strategy library task not found") from exc
        task = manager.get_task(_user_scope(request), task_id)
        return {**_task_payload(task), "cancel_accepted": accepted}

    @router.post("/jobs/{task_id}/retry")
    async def retry_job(task_id: str, payload: RetryRequest, request: Request):
        manager = await _manager_for_request(request)
        items = (
            [(item.strategy_id, item.period) for item in payload.items]
            if payload.items is not None else None
        )
        try:
            task = await asyncio.to_thread(
                manager.retry_failed,
                _user_scope(request),
                task_id,
                items,
            )
        except KeyError as exc:
            raise HTTPException(404, detail="strategy library task not found") from exc
        except StrategyLibraryTaskConflict as exc:
            raise HTTPException(409, detail={"code": "job_already_running", "message": str(exc)}) from exc
        except ValueError as exc:
            raise HTTPException(422, detail={"code": "invalid_retry", "message": str(exc)}) from exc
        return _task_payload(task)

    return router


def _engine(request: Request):
    engine = getattr(request.app.state, "strategy_engine", None)
    if engine is None:
        raise HTTPException(503, detail="策略引擎未初始化")
    return engine


def _accessible_strategies(request: Request):
    return [
        strategy for strategy in _engine(request).strategy_definitions()
        if not strategy.meta.get("research_only") and _can_access_strategy(request, strategy)
    ]


def _user_scope(request: Request) -> str:
    user = getattr(getattr(request, "state", None), "current_user", None)
    return str(user.id) if user is not None else "standalone"


def _latest_trading_day(repo) -> date | None:
    method = getattr(repo, "latest_daily_date", None)
    return method() if callable(method) else None


def _earliest_daily_date(repo) -> date | None:
    method = getattr(repo, "earliest_daily_date", None)
    return method() if callable(method) else None


async def _manager_for_request(request: Request) -> StrategyLibraryManager:
    managers = getattr(request.app.state, "strategy_library_managers", None)
    manager_locks = getattr(request.app.state, "strategy_library_manager_locks", None)
    with _MANAGERS_LOCK:
        if managers is None:
            managers = {}
            request.app.state.strategy_library_managers = managers
        if manager_locks is None:
            manager_locks = {}
            request.app.state.strategy_library_manager_locks = manager_locks
    scope = _user_scope(request)
    with _MANAGERS_LOCK:
        manager_lock = manager_locks.setdefault(scope, asyncio.Lock())

    async with manager_lock:
        existing = managers.get(scope)
        if existing is not None:
            return existing

        loop = asyncio.get_running_loop()
        current_user = getattr(request.state, "current_user", None)
        if current_user is not None:
            initial_preferences = preferences.load()
            if settings.app_mode == "multi_user":
                persist_updates = _user_settings_persister(loop, str(current_user.id))
                store = StrategyLibraryStore(
                    initial_preferences=initial_preferences,
                    persist_updates=persist_updates,
                )
            else:
                store = StrategyLibraryStore(initial_preferences=initial_preferences)
        else:
            store = StrategyLibraryStore()

        engine = _engine(request)
        repo = request.app.state.repo
        data_dir = getattr(getattr(repo, "store", None), "data_dir", settings.data_dir)

        def runner(strategy_id, window, cancel_event, progress_cb, config):
            if settings.backtest_range_guard:
                start = window.actual_start or window.requested_start
                end = window.actual_end or window.requested_end
                if (end - start).days + 1 > BACKTEST_MAX_SERVER_DAYS:
                    raise ValueError(BACKTEST_SERVER_GUARD_MESSAGE)
            backtest_config = StrategyBacktestConfig(
                strategy_id=strategy_id,
                symbols=None,
                start=window.actual_start or window.requested_start,
                end=window.actual_end or window.requested_end,
                params=config.get("params"),
                overrides=config.get("overrides"),
                matching="open_t+1",
                asset_type=config.get("asset_type", "stock"),
            )
            from app.backtest.worker import make_worker_task, run_worker_task

            task = make_worker_task("backtest", data_dir, backtest_config)
            return run_worker_task(task, progress_cb, cancel_event)

        # Job creation validates and passes the request's accessible strategy IDs directly.
        # Do not retain Request (and its per-request auth state) in a background manager.
        manager = await asyncio.to_thread(
            StrategyLibraryManager,
            runner=runner,
            store=store,
            strategy_ids=lambda: [],
            latest_trading_day=lambda: _latest_trading_day(repo),
            window_resolver=lambda strategy_id, window: _resolve_window(repo, engine, strategy_id, window),
        )
        managers[scope] = manager
        return manager


def _user_settings_persister(loop, raw_user_id: str):
    user_id = UUID(raw_user_id)

    async def apply(updates: dict) -> None:
        from app.persistence.database import session_scope

        async with session_scope() as session:
            await PostgresUserSettingsRepository(session).apply(user_id, updates, {}, set())

    def persist(updates: dict) -> None:
        asyncio.run_coroutine_threadsafe(apply(updates), loop).result(timeout=30)

    return persist


def _resolve_window(repo, engine, strategy_id: str, window: BacktestWindow) -> BacktestWindow:
    try:
        strategy = engine.get(strategy_id)
    except (KeyError, ValueError):
        return replace(window, availability="unavailable", reason="策略源码不可用")

    if settings.backtest_range_guard and (
        window.requested_end - window.requested_start
    ).days + 1 > BACKTEST_MAX_SERVER_DAYS:
        return replace(window, availability="unavailable", reason=BACKTEST_SERVER_GUARD_MESSAGE)

    if strategy.execution_backend == "minute_filter":
        earliest = getattr(repo, "earliest_minute_date", lambda: None)()
        latest = getattr(repo, "latest_minute_date_global", lambda: None)()
        if earliest is None or latest is None:
            return replace(window, availability="unavailable", reason="本地没有分钟 K 数据")
        if window.requested_start < earliest or window.requested_end > latest:
            return replace(window, availability="unavailable", reason="分钟 K 数据未覆盖整个回测窗口")
        list_minute_dates = getattr(repo, "list_minute_dates", None)
        execute_all = getattr(repo, "execute_all", None)
        if not callable(list_minute_dates) or not callable(execute_all):
            return replace(window, availability="unavailable", reason="无法确认分钟 K 窗口完整性")
        try:
            expected_rows = execute_all(
                "SELECT DISTINCT CAST(date AS DATE) FROM kline_daily "
                "WHERE date >= ? AND date <= ? ORDER BY 1",
                [window.requested_start, window.requested_end],
            )
        except Exception:
            return replace(window, availability="unavailable", reason="无法确认分钟 K 窗口完整性")
        expected_days = {
            row[0] if isinstance(row[0], date) else date.fromisoformat(str(row[0]))
            for row in expected_rows if row and row[0]
        }
        actual_days = set(list_minute_dates(window.requested_start, window.requested_end, "stock"))
        missing_days = expected_days - actual_days
        if not expected_days or missing_days:
            reason = (
                f"分钟 K 数据缺少 {len(missing_days)} 个交易日"
                if missing_days else "回测窗口没有本地交易日数据"
            )
            return replace(window, availability="unavailable", reason=reason)
        return replace(
            window,
            actual_start=window.requested_start,
            actual_end=window.requested_end,
            availability="available",
        )

    earliest_daily = _earliest_daily_date(repo)
    latest_daily = _latest_trading_day(repo)
    if earliest_daily is None or latest_daily is None:
        return replace(window, availability="unavailable", reason="本地没有日线 K 数据")
    actual_start = max(window.requested_start, earliest_daily)
    actual_end = min(window.requested_end, latest_daily)
    if actual_start > actual_end:
        return replace(window, availability="unavailable", reason="本地行情数据不覆盖回测窗口")
    return replace(
        window,
        actual_start=actual_start,
        actual_end=actual_end,
        availability="available",
    )


def _source_fingerprint(strategy) -> str:
    path = getattr(strategy, "file_path", None)
    if path is not None:
        try:
            return hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            pass
    payload = json.dumps(strategy.meta, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()


def _task_payload(task: StrategyLibraryTask) -> dict:
    value = task.to_dict(include_user=False)
    counts: dict[str, int] = {}
    for item in task.items:
        counts[item.status] = counts.get(item.status, 0) + 1
    value["counts"] = counts
    return value
