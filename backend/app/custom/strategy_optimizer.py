from __future__ import annotations

import ast
import asyncio
import hashlib
import json
import math
import threading

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.extensions import BACKEND_EXTENSION_API_VERSION, BackendExtensionRegistrar
from app.strategy.access import can_access_strategy
from app.strategy_optimizer.contracts import ParameterSpec, StrategyOptimizationContract
from app.strategy_optimizer.manager import OptimizationJobManager
from app.strategy_optimizer.store import OptimizationRunStore
from app.strategy_optimizer.validation import validate_run_config


def _set_literal_assignment(code: str, name: str, value) -> str:
    tree = ast.parse(code)
    node = next((item for item in tree.body if isinstance(item, ast.Assign) and any(
        isinstance(target, ast.Name) and target.id == name for target in item.targets
    )), None)
    if node is None or not isinstance(node.value, (ast.Dict, ast.List, ast.Tuple)):
        raise ValueError(f"策略源码缺少可编辑的 {name} 字面量")
    lines = code.splitlines(keepends=True)
    def offset(lineno, col):
        return sum(len(line.encode("utf-8")) for line in lines[:lineno - 1]) + col
    raw = code.encode("utf-8")
    start = offset(node.value.lineno, node.value.col_offset)
    end = offset(node.value.end_lineno, node.value.end_col_offset)
    return (raw[:start] + repr(value).encode("utf-8") + raw[end:]).decode("utf-8")


def _optimized_strategy_code(code: str, parameters: dict, buy_signals: list, sell_signals: list) -> str:
    tree = ast.parse(code)
    meta_node = next((item.value for item in tree.body if isinstance(item, ast.Assign) and any(
        isinstance(target, ast.Name) and target.id == "META" for target in item.targets
    )), None)
    if not isinstance(meta_node, ast.Dict):
        raise ValueError("策略 META 必须是字面量字典")
    meta = ast.literal_eval(meta_node)
    if not isinstance(meta, dict) or not isinstance(meta.get("params"), list):
        raise ValueError("策略 META.params 必须是列表")
    known = {item.get("id") for item in meta["params"] if isinstance(item, dict)}
    if set(parameters) - known:
        raise ValueError("推荐参数包含策略未声明的参数")
    for item in meta["params"]:
        if isinstance(item, dict) and item.get("id") in parameters:
            item["default"] = parameters[item["id"]]
    code = _set_literal_assignment(code, "META", meta)
    # The saved strategy must keep the signal combination that produced its recommendation.
    tree = ast.parse(code)
    for name, value in (("ENTRY_SIGNALS", buy_signals), ("EXIT_SIGNALS", sell_signals)):
        if any(isinstance(target, ast.Name) and target.id == name
               for item in tree.body if isinstance(item, ast.Assign) for target in item.targets):
            code = _set_literal_assignment(code, name, value)
            tree = ast.parse(code)
    return code

EXTENSION_ID = "strategy.optimizer"
EXTENSION_API_VERSION = BACKEND_EXTENSION_API_VERSION
_optimization_gateway = None
_optimization_managers: set[OptimizationJobManager] = set()
_manager_lock = threading.Lock()


class RunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    strategy_id: str
    asset_type: str = "stock"
    start: str
    end: str
    parameters: dict = Field(default_factory=dict)
    buy_signals: list[str] = Field(default_factory=list)
    sell_signals: list[str] = Field(default_factory=list)
    seed: int = 0
    max_rounds: int = 10
    candidates_per_round: int = 50
    total_candidates: int = 500
    train_fraction: float = Field(default=0.6, gt=0.1, lt=0.9)
    objective: str = "total_return"
    train_days: int = Field(default=252, ge=30, le=2000)
    test_days: int = Field(default=63, ge=10, le=500)
    step_days: int = Field(default=63, ge=1, le=500)
    symbols: list[str] | None = Field(default=None, max_length=500)
    matching: str = "open_t+1"
    fees_pct: float = Field(default=0.0002, ge=0, le=0.1, allow_inf_nan=False)
    commission_pct: float | None = Field(default=None, ge=0, le=0.1, allow_inf_nan=False)
    stamp_tax_pct: float | None = Field(default=None, ge=0, le=0.1, allow_inf_nan=False)
    slippage_bps: float = Field(default=5, ge=0, le=1000, allow_inf_nan=False)
    mode: str = "position"
    holding_days: int = Field(default=5, ge=1, le=500)
    weights: dict[str, float] = Field(
        default_factory=lambda: {
            "oos_return": 0.55,
            "drawdown_improvement": 0.20,
            "win_rate": 0.15,
            "trade_count": 0.10,
        }
    )
    max_drawdown: float = Field(default=0.5, ge=0, le=1, allow_inf_nan=False)
    min_trades: int = Field(default=5, ge=0, le=100000)
    convergence_threshold: float = Field(default=0.01, gt=0, le=0.25, allow_inf_nan=False)

    @model_validator(mode="after")
    def validate_execution_and_weights(self):
        from app.backtest.optimizer import VALID_OBJECTIVES

        if self.matching not in {"close_t", "open_t+1"} or self.mode not in {"position", "full"}:
            raise ValueError("invalid backtest execution options")
        if self.objective not in VALID_OBJECTIVES:
            raise ValueError("unsupported optimization objective")
        expected = {"oos_return", "drawdown_improvement", "win_rate", "trade_count"}
        if set(self.weights) != expected or any(
            not math.isfinite(weight) or weight < 0 for weight in self.weights.values()
        ):
            raise ValueError(
                "weights must define supported metrics with finite non-negative values"
            )
        if abs(sum(self.weights.values()) - 1) > 1e-9:
            raise ValueError("weights must sum to 1")
        return self


def _contract(strategy) -> StrategyOptimizationContract:
    strategy_id = strategy.meta["id"]
    params = []
    for raw in strategy.meta.get("params", []):
        if not all(key in raw for key in ("id", "type", "default")):
            continue
        typ = "enum" if raw["type"] == "select" else raw["type"]
        params.append(
            ParameterSpec(
                raw["id"],
                raw.get("label", raw["id"]),
                typ,
                raw["default"],
                raw.get("min"),
                raw.get("max"),
                raw.get("step"),
                tuple(raw.get("options", ())),
                optimizable=raw.get("optimizable", True),
            )
        )
    return StrategyOptimizationContract(
        strategy_id,
        strategy.meta.get("name", strategy_id),
        strategy.meta.get("asset_type", "stock"),
        tuple(params),
        tuple(strategy.entry_signals),
        tuple(strategy.exit_signals),
        constraints=tuple(strategy.meta.get("optimization_constraints", ())),
    )


def build_router() -> APIRouter:
    router = APIRouter(prefix="/api/custom/strategy-optimizer", tags=["strategy-optimizer"])

    def strategy_for(request: Request, strategy_id: str):
        try:
            strategy = request.app.state.strategy_engine.get(strategy_id)
        except (KeyError, ValueError) as exc:
            raise HTTPException(404, "strategy not found") from exc
        state = request.state
        user = getattr(state, "current_user", None)
        if user is not None and not can_access_strategy(
            strategy,
            user,
            {
                *getattr(state, "owned_strategy_ids", ()),
                *getattr(state, "installed_strategy_ids", ()),
            },
        ):
            raise HTTPException(404, "strategy not found")
        return strategy

    def owner_scope(request: Request) -> str:
        user = getattr(request.state, "current_user", None)
        return str(user.id) if user is not None else "standalone"

    def owned_run(request: Request, run_id: str):
        try:
            record = manager(request).get(run_id)
        except KeyError as exc:
            raise HTTPException(404, "run not found") from exc
        if record.get("config", {}).get("owner_scope", "standalone") != owner_scope(request):
            raise HTTPException(404, "run not found")
        return record

    def manager(request: Request):
        value = getattr(request.app.state, "strategy_optimizer_manager", None)
        if value is None:
            with _manager_lock:
                value = getattr(request.app.state, "strategy_optimizer_manager", None)
                if value is None:
                    root = request.app.state.repo.store.data_dir / "strategy_optimizer" / "runs"
                    value = OptimizationJobManager(
                        OptimizationRunStore(root),
                        _build_evaluator(request),
                    )
                    request.app.state.strategy_optimizer_manager = value
                    _optimization_managers.add(value)
        return value

    @router.get("/strategies")
    def strategies(request: Request):
        result = []
        source = _optimization_gateway
        definitions = (
            source.list_optimizable_strategies()
            if source is not None
            else request.app.state.strategy_engine.strategy_definitions()
        )
        for item in definitions:
            if isinstance(item, dict):
                try:
                    strategy_for(request, item["strategy_id"])
                except HTTPException:
                    continue
                result.append(item)
                continue
            try:
                item = strategy_for(request, item.meta["id"])
            except HTTPException:
                continue
            strategy_id = item.meta["id"]
            reason = "missing parameter contract"
            try:
                contract = _contract(item)
                ok = bool(contract.parameters)
            except (ValueError, TypeError) as exc:
                ok, reason = False, str(exc)
            result.append(
                {
                    "strategy_id": strategy_id,
                    "name": item.meta.get("name", strategy_id),
                    "optimizable": ok,
                    "reason": None if ok else reason,
                }
            )
        return result

    @router.get("/strategies/{strategy_id}/contract")
    def contract(strategy_id: str, request: Request):
        try:
            return _contract(strategy_for(request, strategy_id))
        except HTTPException:
            raise
        except (ValueError, TypeError) as exc:
            raise HTTPException(404, str(exc)) from exc

    @router.post("/runs", status_code=202)
    def create_run(req: RunRequest, request: Request):
        try:
            contract_obj = _contract(strategy_for(request, req.strategy_id))
            config = validate_run_config(req.model_dump(), contract_obj)
        except (ValueError, TypeError) as exc:
            raise HTTPException(422, str(exc)) from exc
        app_manager = manager(request)
        run_config = {
            **req.model_dump(),
            "owner_scope": owner_scope(request),
            "validated": {
                **config.__dict__,
                "start": config.start.isoformat(),
                "end": config.end.isoformat(),
            },
        }
        run_config["input_fingerprint"] = _input_fingerprint(request, run_config)
        try:
            return app_manager.create(run_config)
        except RuntimeError as exc:
            raise HTTPException(429, str(exc)) from exc

    @router.get("/runs/{run_id}")
    def get_run(run_id: str, request: Request):
        try:
            return owned_run(request, run_id)
        except KeyError as exc:
            raise HTTPException(404, "run not found") from exc

    @router.post("/runs/{run_id}/save")
    async def save_recommendations(run_id: str, request: Request):
        try:
            record = owned_run(request, run_id)
        except KeyError as exc:
            raise HTTPException(404, "run not found") from exc
        if record.get("state") != "succeeded":
            raise HTTPException(409, "优化任务尚未成功完成")
        config = record.get("config", {})
        strategy = strategy_for(request, str(config.get("strategy_id", "")))
        contract_obj = _contract(strategy)
        source_path = getattr(strategy, "file_path", None)
        if not source_path or not source_path.is_file():
            raise HTTPException(409, "策略源文件不可用, 无法另存优化结果")
        source_code = source_path.read_text(encoding="utf-8")
        candidates = (record.get("result") or {}).get("top3")
        if not isinstance(candidates, list) or not candidates:
            raise HTTPException(409, "没有通过筛选的推荐参数可保存")
        from app.api.strategy import (
            StrategyCodeSaveRequest,
            _persist_user_strategy,
            _save_strategy_code,
        )

        saved = []
        errors = []
        for rank, candidate in enumerate(candidates[:3], start=1):
            if not isinstance(candidate, dict) or not isinstance(candidate.get("parameters"), dict):
                errors.append({"rank": rank, "error": "推荐参数格式无效"})
                continue
            parameters = candidate["parameters"]
            specs = {spec.id: spec for spec in contract_obj.parameters}
            if any(key not in specs or not specs[key].validate_value(value)
                   for key, value in parameters.items()):
                errors.append({"rank": rank, "error": "推荐参数不符合策略契约"})
                continue
            buy_signals = candidate.get("buy_signals", config.get("buy_signals", []))
            sell_signals = candidate.get("sell_signals", config.get("sell_signals", []))
            if (not isinstance(buy_signals, list) or not isinstance(sell_signals, list)
                    or any(not isinstance(signal, str) for signal in [*buy_signals, *sell_signals])
                    or not set(buy_signals).issubset(contract_obj.buy_signals)
                    or not set(sell_signals).issubset(contract_obj.sell_signals)):
                errors.append({"rank": rank, "error": "推荐信号不符合策略契约"})
                continue
            strategy_id = f"custom_opt_{run_id[:12]}_top{rank}"
            name = f"{contract_obj.name}-top{rank}"
            try:
                existing = request.app.state.strategy_engine.get(strategy_id)
            except (KeyError, ValueError):
                existing = None
            if existing is not None:
                saved.append({"strategy_id": strategy_id, "name": name, "already_saved": True})
                continue
            try:
                derived = _optimized_strategy_code(
                    source_code, parameters, buy_signals, sell_signals
                )
                result = _save_strategy_code(StrategyCodeSaveRequest(
                    code=derived,
                    strategy_id=strategy_id,
                    target_source="custom",
                    mode="create",
                    name=name,
                    description=f"由策略优化任务 {run_id[:8]} 生成。",
                ), request)
                await _persist_user_strategy(request, result)
                saved.append({"strategy_id": strategy_id, "name": name, "already_saved": False})
            except Exception as exc:
                errors.append({"rank": rank, "error": str(exc)})
        return {"saved": saved, "errors": errors}

    @router.get("/runs")
    def list_runs(request: Request):
        return [
            item
            for item in manager(request).list()
            if item.get("config", {}).get("owner_scope", "standalone") == owner_scope(request)
        ]

    @router.get("/runs/{run_id}/candidates/{candidate_id}")
    def candidate(run_id: str, candidate_id: str, request: Request):
        try:
            owned_run(request, run_id)
            return manager(request).candidate(run_id, candidate_id)
        except KeyError as exc:
            raise HTTPException(404, "candidate or run not found") from exc

    @router.get("/runs/{run_id}/events")
    async def events(
        run_id: str,
        request: Request,
        last_event_id: int = 0,
        last_event_header: int = Header(default=0, alias="Last-Event-ID"),
    ):
        try:
            owned_run(request, run_id)
        except KeyError as exc:
            raise HTTPException(404, "run not found") from exc

        async def stream():
            cursor = max(last_event_id, last_event_header)
            for _ in range(120):
                rows = manager(request).events(run_id, cursor)
                if rows and rows[0].get("event_id", cursor + 1) > cursor + 1:
                    yield f"data: {json.dumps({'type': 'snapshot_required'}, ensure_ascii=False)}\n\n"
                for event in rows:
                    cursor = event.get("event_id", cursor + 1)
                    yield f"id: {cursor}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
                if manager(request).get(run_id)["state"] in {"succeeded", "failed", "cancelled"}:
                    break
                yield ": ping\n\n"
                await asyncio.sleep(1)

        return StreamingResponse(
            stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"}
        )

    @router.post("/runs/{run_id}/resume")
    def resume(run_id: str, request: Request):
        try:
            record = owned_run(request, run_id)
            expected = record.get("config", {}).get("input_fingerprint")
            if not expected or expected != _input_fingerprint(request, record.get("config", {})):
                raise HTTPException(409, "strategy or data changed; create a new optimization run")
            return manager(request).resume(run_id)
        except KeyError as exc:
            raise HTTPException(404, "run not found") from exc
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @router.post("/runs/{run_id}/cancel")
    def cancel(run_id: str, request: Request):
        try:
            owned_run(request, run_id)
            return manager(request).cancel(run_id)
        except KeyError as exc:
            raise HTTPException(404, "run not found") from exc

    return router


def startup(context):
    global _optimization_gateway
    if context.strategy_optimization is not None:
        _optimization_gateway = context.strategy_optimization


def shutdown():
    with _manager_lock:
        managers = tuple(_optimization_managers)
        _optimization_managers.clear()
    for manager in managers:
        manager.shutdown()


def setup(registrar: BackendExtensionRegistrar) -> None:
    registrar.include_router(build_router())


def _build_evaluator(request: Request):
    from app.backtest.worker import make_worker_task, run_worker_task

    data_dir = request.app.state.repo.store.data_dir

    def evaluate(config, progress_cb, cancel_event):
        task = make_worker_task("strategy_optimizer", data_dir, config)
        return run_worker_task(task, progress_cb, cancel_event)

    return evaluate


def _input_fingerprint(request: Request, config: dict) -> str:
    strategy = request.app.state.strategy_engine.get(config["strategy_id"])
    source_hash = ""
    if strategy.file_path and strategy.file_path.is_file():
        source_hash = hashlib.sha256(strategy.file_path.read_bytes()).hexdigest()
    repo = request.app.state.repo
    generation = repo.get_matrix_data_generation(config.get("asset_type", "stock"))
    payload = {
        "strategy_id": config["strategy_id"],
        "optimizer_api_version": 1,
        "backtest_method_version": 1,
        "source_hash": source_hash,
        "meta": strategy.meta,
        "entry_signals": strategy.entry_signals,
        "exit_signals": strategy.exit_signals,
        "data_generation": generation,
        "config": {
            key: value
            for key, value in config.items()
            if key not in {"resume_state", "input_fingerprint"}
        },
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()
