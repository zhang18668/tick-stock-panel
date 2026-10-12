from __future__ import annotations

import calendar as month_calendar
import hashlib
import json
import threading
from bisect import bisect_left
from dataclasses import asdict, replace
from datetime import date, timedelta
from pathlib import Path

from app.backtest.strategy import (
    BacktestResultPolicy,
    StrategyBacktestConfig,
    StrategyBacktestService,
)

from .contracts import (
    EvaluationWindow,
    ParameterSpec,
    RobustGates,
    RobustTimePlan,
    SegmentMetrics,
    SegmentObservation,
    StrategyOptimizationContract,
)
from .scoring import DEFAULT_WEIGHTS, score_candidates, select_top_candidates
from .search import AdaptiveSearchService
from .time_plan import build_time_plan


class StrategyOptimizationGateway:
    """Adapter over the existing strategy backtest service; no separate simulator."""

    api_version = 1

    def __init__(
        self,
        service: StrategyBacktestService,
        strategy_engine,
        *,
        repository=None,
        trading_dates_reader=None,
    ):
        self.service = service
        self.strategy_engine = strategy_engine
        self.repository = repository
        self.trading_dates_reader = trading_dates_reader

    def preview_robust_config(self, raw: dict) -> dict:
        try:
            start = _as_date(raw["start"])
            end = _as_date(raw["end"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("start and end must be ISO dates") from exc
        if start > end:
            raise ValueError("invalid date range")
        robust_config = raw.get("robust_config") or {}
        if not isinstance(robust_config, dict):
            raise ValueError("robust_config must be an object")
        allowed_robust_fields = {
            "layout", "boundaries", "holdout_usage", "gates", "reference_strategy_ids",
            "neighbor_budget", "neighbor_centers",
        }
        unknown = set(robust_config) - allowed_robust_fields
        if unknown:
            raise ValueError(f"unknown robust_config field: {sorted(unknown)[0]}")
        layout = robust_config.get("layout", "holdout")
        if layout not in {"holdout", "diagnostic"}:
            raise ValueError("layout must be 'holdout' or 'diagnostic'")
        usage = robust_config.get("holdout_usage", "unknown")
        if usage not in {"used", "declared_unused", "unknown"}:
            raise ValueError("invalid holdout usage declaration")
        gates = robust_config.get("gates", {})
        if not isinstance(gates, dict):
            raise ValueError("robust gates must be an object")
        RobustGates(**gates)
        neighbor_budget = int(robust_config.get("neighbor_budget", 200))
        neighbor_centers = int(robust_config.get("neighbor_centers", 10))
        if not 0 <= neighbor_budget <= 200 or not 0 <= neighbor_centers <= 10:
            raise ValueError("neighborhood budget is outside supported limits")
        reader = self.trading_dates_reader or self.historical_trading_dates
        try:
            calendar = tuple(reader(start, end, raw.get("asset_type", "stock")))
        except Exception as exc:
            raise ValueError("historical trading calendar is unavailable") from exc
        if not calendar:
            raise ValueError("historical trading calendar returned no dates")
        if any(not isinstance(day, date) for day in calendar):
            raise ValueError("authoritative trading calendar returned invalid dates")
        boundaries = robust_config.get("boundaries")
        if boundaries is None:
            boundaries = _default_robust_boundaries(start, end, calendar, layout)
        else:
            try:
                boundaries = tuple(_as_date(day) for day in boundaries)
            except (TypeError, ValueError) as exc:
                raise ValueError("robust boundaries must be ISO dates") from exc
        plan = build_time_plan(start, end, calendar, tuple(boundaries), layout)
        diagnostics = _rolling_diagnostic_windows(
            plan.development[0].start, plan.development[-1].end, tuple(calendar)
        )
        time_plan = {
            "development": [_window_payload(window) for window in plan.development],
            "holdout": _window_payload(plan.holdout) if plan.holdout else None,
            "diagnostics": [_window_payload(window) for window in diagnostics],
        }
        total_candidates = min(500, max(1, int(raw.get("total_candidates", 500))))
        neighbor_budget = min(200, max(0, neighbor_budget))
        references = robust_config.get("reference_strategy_ids", ())
        if not isinstance(references, (list, tuple)) or len(references) > 2:
            raise ValueError("at most two unique fixed reference strategies are supported")
        if any(not isinstance(item, str) or not item for item in references) or len(references) != len(set(references)):
            raise ValueError("at most two unique fixed reference strategies are supported")
        windows_for_budget = len(diagnostics)
        holdout_count = int(plan.holdout is not None)
        budget = (
            3 * total_candidates
            + 3 * neighbor_budget
            + 3 * (1 + windows_for_budget + holdout_count + len(references))
        )
        return {
            "time_plan": time_plan,
            "calendar_source": "injected_authoritative_calendar" if self.trading_dates_reader else "normalized_repository_daily_dates",
            "calendar_coverage": {
                "requested_start": start.isoformat(),
                "requested_end": end.isoformat(),
                "covered_start": calendar[0].isoformat(),
                "covered_end": calendar[-1].isoformat(),
                "trading_dates": len(calendar),
            },
            "data_generation": self.data_generation(raw.get("asset_type", "stock")),
            "budgets": {
                "main_candidates": total_candidates,
                "neighbor_candidates": neighbor_budget,
                "estimated_backtests": budget,
            },
            "holdout_usage": usage,
            "warnings": [],
        }

    def data_generation(self, asset_type: str) -> str:
        getter = getattr(self.repository, "get_matrix_data_generation", None)
        return str(getter(asset_type)) if callable(getter) else ""

    def historical_trading_dates(self, start: date, end: date, asset_type: str = "stock"):
        """Read the shared repository's normalized market dates, never a single symbol's rows."""
        if self.repository is None or not hasattr(self.repository, "execute_all"):
            raise ValueError("historical trading calendar is unavailable")
        view = {"stock": "kline_daily", "etf": "kline_etf_daily", "index": "kline_index_daily"}.get(asset_type)
        if view is None:
            raise ValueError("unsupported asset type for historical trading calendar")
        rows = self.repository.execute_all(
            f"SELECT DISTINCT date FROM {view} WHERE date >= ? AND date <= ? ORDER BY date",
            [start, end],
        )
        return tuple(_as_date(row[0]) for row in rows)

    def calendar_coverage(self, start: date, end: date, asset_type: str = "stock") -> dict:
        dates = self.historical_trading_dates(start, end, asset_type)
        if not dates:
            raise ValueError("historical trading calendar returned no dates")
        return {
            "source": "normalized_repository_daily_dates",
            "requested_start": start.isoformat(),
            "requested_end": end.isoformat(),
            "covered_start": dates[0].isoformat(),
            "covered_end": dates[-1].isoformat(),
            "trading_dates": dates,
        }

    def list_optimizable_strategies(self):
        result = []
        for strategy in self.strategy_engine.strategy_definitions():
            strategy_id = strategy.meta["id"]
            try:
                contract = self.get_optimization_contract(strategy_id)
                result.append(
                    {
                        "strategy_id": strategy_id,
                        "name": contract.name,
                        "asset_type": contract.asset_type,
                        "optimizable": bool(contract.parameters),
                        "reason": None,
                    }
                )
            except (ValueError, TypeError) as exc:
                result.append(
                    {
                        "strategy_id": strategy_id,
                        "name": strategy.meta.get("name", strategy_id),
                        "asset_type": strategy.meta.get("asset_type", "stock"),
                        "optimizable": False,
                        "reason": str(exc),
                    }
                )
        return result

    def get_optimization_contract(self, strategy_id: str) -> StrategyOptimizationContract:
        strategy = self.strategy_engine.get(strategy_id)
        params = []
        for raw in strategy.meta.get("params", []):
            if not all(key in raw for key in ("id", "type", "default")):
                raise ValueError(f"parameter contract incomplete for {strategy_id}")
            param_type = "enum" if raw["type"] == "select" else raw["type"]
            if param_type not in {"int", "float", "bool", "enum"}:
                raise ValueError(f"unsupported parameter type {raw['type']!r}")
            params.append(
                ParameterSpec(
                    raw["id"],
                    raw.get("label", raw["id"]),
                    param_type,
                    raw["default"],
                    raw.get("min"),
                    raw.get("max"),
                    raw.get("step"),
                    tuple(raw.get("options", ())),
                    optimizable=raw.get("optimizable", True),
                )
            )
        if not params:
            raise ValueError("strategy has no complete optimizable parameter contract")
        return StrategyOptimizationContract(
            strategy.meta["id"],
            strategy.meta.get("name", strategy.meta["id"]),
            strategy.meta.get("asset_type", "stock"),
            tuple(params),
            tuple(strategy.entry_signals),
            tuple(strategy.exit_signals),
            constraints=tuple(strategy.meta.get("optimization_constraints", ())),
        )

    def evaluate_candidates(
        self, request: dict, candidates: list[dict], progress_cb, cancel_event: threading.Event
    ):
        config = request["validated"]
        start = date.fromisoformat(config["start"])
        total_days = (date.fromisoformat(config["end"]) - start).days + 1
        train_days = max(1, int(total_days * float(request.get("train_fraction", 0.6))))
        end = start + timedelta(days=train_days - 1)
        objective = request.get("objective", "total_return")
        selected_signals = {
            "entry_signals": config.get("buy_signals", []),
            "exit_signals": config.get("sell_signals", []),
        }
        contract = self.get_optimization_contract(config["strategy_id"])
        defaults = {parameter.id: parameter.default for parameter in contract.parameters}
        rows = []
        for index, candidate in enumerate(candidates, 1):
            if cancel_event.is_set():
                break
            result = self.service.run(
                StrategyBacktestConfig(
                    strategy_id=config["strategy_id"],
                    symbols=request.get("symbols"),
                    start=start,
                    end=end,
                    params={**defaults, **candidate["parameters"]},
                    overrides={
                        "entry_signals": candidate.get(
                            "buy_signals", selected_signals["entry_signals"]
                        ),
                        "exit_signals": candidate.get(
                            "sell_signals", selected_signals["exit_signals"]
                        ),
                    },
                    asset_type=config["asset_type"],
                    matching=request.get("matching", "open_t+1"),
                    fees_pct=float(request.get("fees_pct", 0.0002)),
                    commission_pct=request.get("commission_pct"),
                    stamp_tax_pct=request.get("stamp_tax_pct"),
                    slippage_bps=float(request.get("slippage_bps", 5)),
                    mode=request.get("mode", "position"),
                    holding_days=int(request.get("holding_days", 5)),
                ),
                cancel_event=cancel_event,
                result_policy=BacktestResultPolicy.optimizer_trial(objective),
            )
            rows.append(
                {**candidate, "training_metrics": result.stats, "training_error": result.error}
            )
            progress_cb({"type": "candidate_progress", "done": index, "total": len(candidates)})
        return rows

    def run_optimization(self, request: dict, progress_cb, cancel_event: threading.Event):
        if request.get("evaluation_mode") == "robust":
            return self.run_robust_optimization(request, progress_cb, cancel_event)
        contract = self.get_optimization_contract(request["strategy_id"])
        search_params = []
        for parameter in contract.parameters:
            override = request["validated"].get("parameters", {}).get(parameter.id, {})
            minimum = override.get("min", parameter.minimum)
            maximum = override.get("max", parameter.maximum)
            options = tuple(override.get("values", parameter.options))
            default = parameter.default
            if parameter.type in {"int", "float"}:
                default = min(max(default, minimum), maximum)
            elif parameter.type in {"bool", "enum"} and options and default not in options:
                default = options[0]
            search_params.append(
                replace(
                    parameter,
                    minimum=minimum,
                    maximum=maximum,
                    step=override.get("step", parameter.step),
                    options=options,
                    default=default,
                )
            )
        search = AdaptiveSearchService(
            tuple(parameter for parameter in search_params if parameter.optimizable),
            buy_signals=tuple(request["validated"].get("buy_signals", ())),
            sell_signals=tuple(request["validated"].get("sell_signals", ())),
            seed=int(request.get("seed", 0)),
            constraints=contract.constraints,
            base_values={
                parameter.id: parameter.default
                for parameter in contract.parameters
                if not parameter.optimizable
            },
        )
        budget = int(request["validated"]["total_candidates"])
        batch_size = int(request["validated"]["candidates_per_round"])
        max_rounds = int(request["validated"]["max_rounds"])
        resume_state = request.get("resume_state") or {}
        all_rows = list(resume_state.get("all_rows", []))
        previous = list(resume_state.get("previous", []))
        best_scores = list(resume_state.get("best_scores", []))
        examined = int(resume_state.get("examined", 0))
        search.round_index = max(0, int(resume_state.get("round", 0)) - 1)
        if resume_state.get("random_state"):
            search.random.setstate(_as_tuple(resume_state["random_state"]))
        for row in all_rows:
            search.seen.add(
                (
                    tuple(sorted(row["parameters"].items())),
                    tuple(row.get("buy_signals", ())),
                    tuple(row.get("sell_signals", ())),
                )
            )
        first_round = int(resume_state.get("round", 0)) + 1
        stop_reason = "max_rounds"
        for round_no in range(first_round, max_rounds + 1):
            if cancel_event.is_set():
                return {"cancelled": True, "rounds": round_no - 1, "candidates": all_rows}
            count = min(batch_size, budget - examined)
            if count <= 0:
                break
            batch = (
                search.first_round(count) if round_no == 1 else search.next_round(previous, count)
            )
            if not batch:
                stop_reason = "search_space_exhausted"
                break
            payloads = [
                {
                    "parameters": candidate.parameters,
                    "buy_signals": candidate.buy_signals,
                    "sell_signals": candidate.sell_signals,
                }
                for candidate in batch
            ]
            evaluated = self.evaluate_candidates(request, payloads, progress_cb, cancel_event)
            if cancel_event.is_set():
                return {"cancelled": True, "rounds": round_no, "candidates": all_rows}
            usable = [row for row in evaluated if not row.get("training_error")]
            for row in usable:
                score_metric = request.get("objective", "total_return")
                row["score"] = row["training_metrics"].get(score_metric)
            previous = usable
            all_rows.extend({**row, "round": round_no} for row in evaluated)
            examined += len(batch)
            round_best = max(
                (float(row["score"]) for row in usable if row.get("score") is not None),
                default=None,
            )
            prior_best = best_scores[-1] if best_scores else None
            cumulative_best = max(
                (value for value in (prior_best, round_best) if value is not None),
                default=None,
            )
            best_scores.append(cumulative_best)
            progress_cb(
                {
                    "type": "round_complete",
                    "round": round_no,
                    "rounds": max_rounds,
                    "evaluated": examined,
                    "budget": budget,
                    "best_training_score": cumulative_best,
                }
            )
            progress_cb(
                {
                    "type": "checkpoint",
                    "checkpoint": {
                        "round": round_no,
                        "all_rows": all_rows,
                        "previous": previous,
                        "best_scores": best_scores,
                        "examined": examined,
                        "random_state": search.random.getstate(),
                    },
                }
            )
            if len(best_scores) >= 4 and all(
                best_scores[-index] is not None
                and best_scores[-index - 1] is not None
                and best_scores[-index] - best_scores[-index - 1]
                < float(request.get("convergence_threshold", 0.01))
                * max(abs(best_scores[-index - 1]), 1e-9)
                for index in (1, 2, 3)
            ):
                stop_reason = "converged"
                break
            if examined >= budget:
                stop_reason = "candidate_budget"
        if cancel_event.is_set():
            return {"cancelled": True, "rounds": len(best_scores), "candidates": all_rows}
        if not any(row.get("score") is not None for row in all_rows):
            raise ValueError("all training candidates failed or were invalid")
        finalists = sorted(
            (row for row in all_rows if row.get("score") is not None),
            key=lambda row: float(row["score"]),
            reverse=True,
        )[:20]
        result = self.validate_oos(request, finalists, progress_cb, cancel_event)
        result.update(
            {
                "rounds": len(best_scores),
                "evaluated_candidates": examined,
                "training_candidates": all_rows,
                "stop_reason": stop_reason,
            }
        )
        return result

    def run_robust_optimization(self, request: dict, progress_cb, cancel_event: threading.Event):
        from .robustness import RobustnessRunner
        from .search import Candidate

        checkpoint = request.get("resume_state") or {}
        if checkpoint.get("version") == 2 and checkpoint.get("stage") == "holdout_complete":
            if checkpoint.get("input_fingerprint") != request.get("input_fingerprint"):
                raise ValueError("robust checkpoint does not match the frozen task")
            return checkpoint["result"]

        snapshot = request.get("strategy_snapshot")
        if not snapshot or snapshot.get("strategy_id") != request.get("strategy_id"):
            raise ValueError("frozen strategy snapshot is unavailable or invalid")
        preview = request.get("robust_preview") or self.preview_robust_config(request)
        plan_data = preview["time_plan"]
        development = tuple(
            EvaluationWindow(item["id"], _as_date(item["start"]), _as_date(item["end"]), "development")
            for item in plan_data["development"]
        )
        holdout_data = plan_data.get("holdout")
        holdout = (
            EvaluationWindow(holdout_data["id"], _as_date(holdout_data["start"]), _as_date(holdout_data["end"]), "holdout")
            if holdout_data else None
        )
        plan = RobustTimePlan(development, holdout)
        expected_generation = preview.get("data_generation")
        current_generation = self.data_generation(request.get("asset_type", "stock"))
        if expected_generation and current_generation != expected_generation:
            raise ValueError("matrix data generation changed after robust preview; create a new run")
        calendar_reader = self.trading_dates_reader or self.historical_trading_dates
        calendar = tuple(calendar_reader(
            _as_date(request["start"]), _as_date(request["end"]), request.get("asset_type", "stock")
        ))
        if not calendar:
            raise ValueError("historical trading calendar is unavailable for robust preflight")
        for window in (*development, *((holdout,) if holdout else ())):
            covered = tuple(day for day in calendar if window.start <= day <= window.end)
            if not covered or covered[0] != window.start or covered[-1] != window.end:
                raise ValueError(f"trading calendar does not cover {window.id}")
        rolling_windows = tuple(
            EvaluationWindow(item["id"], _as_date(item["start"]), _as_date(item["end"]), "diagnostic")
            for item in plan_data.get("diagnostics", ())
        )
        contract = self.get_optimization_contract(request["strategy_id"])
        search_params = []
        for parameter in contract.parameters:
            override = request["validated"].get("parameters", {}).get(parameter.id, {})
            minimum = override.get("min", parameter.minimum)
            maximum = override.get("max", parameter.maximum)
            options = tuple(override.get("values", parameter.options))
            default = parameter.default
            if parameter.type in {"int", "float"}:
                default = min(max(default, minimum), maximum)
            elif parameter.type in {"bool", "enum"} and options and default not in options:
                default = options[0]
            search_params.append(replace(parameter, minimum=minimum, maximum=maximum,
                step=override.get("step", parameter.step), options=options, default=default))
        search = AdaptiveSearchService(
            tuple(parameter for parameter in search_params if parameter.optimizable),
            buy_signals=tuple(request["validated"].get("buy_signals", ())),
            sell_signals=tuple(request["validated"].get("sell_signals", ())),
            seed=int(request.get("seed", 0)), constraints=contract.constraints,
            base_values={parameter.id: parameter.default for parameter in contract.parameters if not parameter.optimizable},
        )
        config = request["validated"]

        evaluation_artifacts = {}

        def evaluate(candidate, window, include_curve):
            result = self.service.run(StrategyBacktestConfig(
                strategy_id=request["strategy_id"], symbols=request.get("symbols"),
                start=window.start, end=window.end,
                params={parameter.id: parameter.default for parameter in contract.parameters} | candidate.parameters,
                overrides={"entry_signals": list(candidate.buy_signals), "exit_signals": list(candidate.sell_signals)},
                asset_type=request.get("asset_type", "stock"),
                matching=request.get("matching", "open_t+1"), fees_pct=float(request.get("fees_pct", 0.0002)),
                commission_pct=request.get("commission_pct"), stamp_tax_pct=request.get("stamp_tax_pct"),
                slippage_bps=float(request.get("slippage_bps", 5)), mode="position",
                holding_days=int(request.get("holding_days", 5)),
            ), cancel_event=cancel_event, result_policy=BacktestResultPolicy(
                required_stats=frozenset({"total_return", "annual_return", "max_drawdown", "n_trades"}),
                include_curves=include_curve, include_trades=False, include_per_symbol_stats=False,
                include_return_distribution=False, include_benchmark=False, include_strategy_info=False,
            ))
            if result.error:
                return SegmentObservation(window.id, None, result.error)
            stats = result.stats or {}
            from .robust_scoring import annualize
            curve = result.equity_curve or []
            if curve:
                ending_nav = float(curve[-1].get("value", curve[-1].get("equity", curve[-1].get("nav", 1.0))))
                initial_capital = float(result.config.get("initial_capital", 1_000_000) or 1_000_000)
                ending_nav /= initial_capital
                drawdown_values = [float(row["value"]) for row in result.drawdown_curve if row.get("value") is not None]
                curve_drawdown = abs(min(drawdown_values, default=float(stats.get("max_drawdown", 0))))
            else:
                ending_nav = 1.0 + float(stats.get("total_return", 0) or 0)
                curve_drawdown = abs(float(stats.get("max_drawdown", 0) or 0))
            annualized = annualize(ending_nav, (window.end - window.start).days + 1)
            drawdown = curve_drawdown if include_curve else stats.get("max_drawdown")
            trades = stats.get("n_trades", stats.get("trade_count"))
            if annualized is None or drawdown is None or trades is None:
                return SegmentObservation(window.id, None, "backtest omitted required robust metrics")
            if int(trades) <= 0:
                return SegmentObservation(window.id, None, "no trades in evaluation window")
            observation = SegmentObservation(window.id, SegmentMetrics(float(annualized), abs(float(drawdown)), int(trades), 0.0))
            if include_curve:
                evaluation_artifacts[(candidate.key, window.id)] = {
                    "equity_curve": curve,
                    "drawdown_curve": result.drawdown_curve,
                    "stats": stats,
                }
            return observation

        raw_robust = request.get("robust_config") or {}
        gates = RobustGates(**raw_robust.get("gates", {}))
        reference_candidates = []
        for reference_snapshot in request.get("reference_strategy_snapshots", ()):
            reference_contract = self.get_optimization_contract(reference_snapshot["strategy_id"])
            reference_candidates.append((
                reference_snapshot["strategy_id"],
                Candidate(
                    {parameter.id: parameter.default for parameter in reference_contract.parameters},
                    tuple(reference_snapshot.get("entry_signals", ())),
                    tuple(reference_snapshot.get("exit_signals", ())),
                ),
            ))
        robust_result = RobustnessRunner(evaluate, search).run({
            "time_plan": plan, "gates": gates,
            "baseline_parameters": {parameter.id: parameter.default for parameter in contract.parameters},
            "baseline_buy_signals": tuple(snapshot.get("entry_signals", ())),
            "baseline_sell_signals": tuple(snapshot.get("exit_signals", ())),
            "reference_candidates": reference_candidates,
            "total_candidates": int(config.get("total_candidates", 500)),
            "candidates_per_round": int(config.get("candidates_per_round", 50)),
            "max_rounds": int(config.get("max_rounds", 10)),
            "neighbor_budget": int(raw_robust.get("neighbor_budget", 200)),
            "neighbor_centers": int(raw_robust.get("neighbor_centers", 10)),
            "holdout_window": ({"id": holdout.id, "start": holdout.start.isoformat(), "end": holdout.end.isoformat(), "role": "holdout"} if holdout else None),
            "holdout_usage": raw_robust.get("holdout_usage", "unknown"),
            "run_id": request.get("run_id"),
            "owner_scope": request.get("owner_scope", "standalone"),
            "holdout_store_root": request.get("holdout_store_root"),
        }, progress_cb, cancel_event)
        if robust_result.get("cancelled"):
            return robust_result
        progress_cb({"type": "stage", "stage": "continuous_diagnostics"})
        baseline_candidate = Candidate(
            {parameter.id: parameter.default for parameter in contract.parameters},
            tuple(snapshot.get("entry_signals", ())),
            tuple(snapshot.get("exit_signals", ())),
        )
        continuous_window = EvaluationWindow(
            "continuous-development", development[0].start, development[-1].end, "diagnostic"
        )
        continuous_baseline = evaluate(baseline_candidate, continuous_window, True)
        continuous_rows = []
        frozen_rows = []
        for index, frozen in enumerate(robust_result["top3"], 1):
            if cancel_event.is_set():
                return {**robust_result, "cancelled": True, "stop_reason": "cancelled", "top3": [], "frozen_candidate_ids": []}
            candidate = Candidate(
                frozen["parameters"], tuple(frozen["buy_signals"]), tuple(frozen["sell_signals"])
            )
            observation = evaluate(candidate, continuous_window, True)
            baseline_metrics = continuous_baseline.metrics
            metrics = observation.metrics
            continuous_rows.append({
                "candidate_id": frozen["candidate_id"],
                "metrics": {**metrics.__dict__, "baseline_delta": metrics.annualized_return - baseline_metrics.annualized_return}
                    if metrics and baseline_metrics else None,
                "failure": observation.failure if metrics is None else None,
            })
            frozen_rows.append((frozen, candidate))
            progress_cb({"type": "candidate_progress", "stage": "continuous_development", "done": index, "total": len(robust_result["top3"])})
        rolling_rows = []
        if rolling_windows:
            baseline_rolling = {window.id: evaluate(baseline_candidate, window, False) for window in rolling_windows}
            for window in rolling_windows:
                for frozen, candidate in frozen_rows:
                    observation = evaluate(candidate, window, False)
                    base = baseline_rolling[window.id].metrics
                    metrics = observation.metrics
                    rolling_rows.append({
                        "candidate_id": frozen["candidate_id"], "window_id": window.id,
                        "metrics": {**metrics.__dict__, "baseline_delta": metrics.annualized_return - base.annualized_return}
                            if metrics and base else None,
                        "failure": observation.failure if metrics is None else None,
                    })
                progress_cb({"type": "candidate_progress", "stage": "rolling_diagnostics", "window": window.id, "done": rolling_windows.index(window) + 1, "total": len(rolling_windows)})
        robust_result["robust_result"]["continuous_development"] = {
            "window": {"start": continuous_window.start.isoformat(), "end": continuous_window.end.isoformat()},
            "baseline": asdict(continuous_baseline.metrics) if continuous_baseline.metrics else None,
            "candidates": continuous_rows,
        }
        robust_result["robust_result"]["diagnostics"] = [
            {"window": {"id": item["id"], "start": item["start"], "end": item["end"]},
             "candidates": [row for row in rolling_rows if row["window_id"] == item["id"]]}
            for item in plan_data.get("diagnostics", ())
        ]
        robust_result["robust_result"]["coverage"] = {
            "calendar_source": preview.get("calendar_source"),
            "calendar_coverage": preview.get("calendar_coverage"),
            "data_generation": current_generation,
            "universe_mode": "explicit_symbols" if request.get("symbols") else "current_universe",
            "survivorship_bias_warning": True,
            "warnings": ["当前回测数据契约未提供历史退市证券池，无法验证历史股票池完整性，结果可能存在幸存者偏差。"],
        }
        if holdout is not None:
            run_id = request.get("run_id")
            usage_key = f"{request.get('owner_scope', 'standalone')}:{request['strategy_id']}:{request.get('asset_type', 'stock')}:{holdout.start}:{holdout.end}"
            from .store import OptimizationRunStore
            holdout_store = (
                OptimizationRunStore(Path(request["holdout_store_root"]))
                if run_id and request.get("holdout_store_root") else None
            )
            claim = holdout_store.claim_holdout(run_id, usage_key) if holdout_store else "unknown"
            if claim == "completed":
                saved_holdout = holdout_store.get_holdout_result(run_id, usage_key)
                if saved_holdout is None:
                    raise ValueError("completed holdout claim has no persisted result")
                robust_result["robust_result"]["holdout"] = saved_holdout
                return robust_result
            if claim == "resumed":
                robust_result["robust_result"]["holdout"] = {
                    "status": "insufficient",
                    "usage": raw_robust.get("holdout_usage", "unknown"),
                    "reuse": "interrupted",
                    "results": [],
                    "failure": "留出验证曾启动但结果未持久化；为避免重复访问该区间，本次恢复不重跑。请创建新任务。",
                }
                return robust_result
            holdout_rows = []
            passed = True
            enough = True
            baseline = Candidate(
                {parameter.id: parameter.default for parameter in contract.parameters},
                tuple(request["validated"].get("buy_signals", ())),
                tuple(request["validated"].get("sell_signals", ())),
            )
            baseline_observation = evaluate(baseline, holdout, False)
            for frozen in robust_result["top3"]:
                candidate = Candidate(frozen["parameters"], tuple(frozen["buy_signals"]), tuple(frozen["sell_signals"]))
                observation = evaluate(candidate, holdout, False)
                metrics = observation.metrics
                base_metrics = baseline_observation.metrics
                if metrics is None or base_metrics is None:
                    enough = False
                    holdout_rows.append({"candidate_id": frozen["candidate_id"], "metrics": None, "failure": observation.failure or baseline_observation.failure})
                    continue
                delta = metrics.annualized_return - base_metrics.annualized_return
                relative_pass = delta >= gates.min_baseline_delta
                risk_pass = metrics.max_drawdown <= gates.max_drawdown
                sample_pass = metrics.trade_count >= gates.min_trades and base_metrics.trade_count >= gates.min_trades
                passed = passed and relative_pass and risk_pass and sample_pass
                enough = enough and sample_pass
                holdout_rows.append({"candidate_id": frozen["candidate_id"], "metrics": {**metrics.__dict__, "baseline_delta": delta}, "passed": relative_pass and risk_pass and sample_pass})
            status = "insufficient" if not enough else ("passed" if passed else "failed")
            holdout_result = {
                "status": status, "usage": raw_robust.get("holdout_usage", "unknown"),
                "reuse": claim, "results": holdout_rows,
            }
            if holdout_store:
                holdout_store.complete_holdout(run_id, usage_key, holdout_result)
            robust_result["robust_result"]["holdout"] = holdout_result
            progress_cb({"type": "checkpoint", "checkpoint": {
                "version": 2, "stage": "holdout_complete",
                "input_fingerprint": request.get("input_fingerprint"),
                "result": robust_result,
            }})
        return robust_result

    def validate_oos(
        self, request: dict, candidates: list[dict], progress_cb, cancel_event: threading.Event
    ):
        config = request["validated"]
        start, end = date.fromisoformat(config["start"]), date.fromisoformat(config["end"])
        total_days = (end - start).days + 1
        train_end = start + timedelta(
            days=max(1, int(total_days * float(request.get("train_fraction", 0.6)))) - 1
        )
        test_days = int(request.get("test_days", 63))
        step_days = int(request.get("step_days", 63))
        folds = []
        cursor = train_end + timedelta(days=1)
        while True:
            test_start = cursor
            test_end = test_start + timedelta(days=test_days - 1)
            if test_end > end:
                break
            folds.append((cursor, train_end, test_start, test_end))
            cursor += timedelta(days=step_days)
            if len(folds) > 100:
                raise ValueError("out-of-sample fold count exceeds the 100 fold limit")
        if not folds:
            raise ValueError("date range cannot produce a valid out-of-sample fold")
        scored = []
        for ci, candidate in enumerate(candidates, 1):
            fold_stats = []
            for fi, (_, _, test_start, test_end) in enumerate(folds, 1):
                if cancel_event.is_set():
                    return []
                result = self.service.run(
                    StrategyBacktestConfig(
                        strategy_id=config["strategy_id"],
                        symbols=request.get("symbols"),
                        start=test_start,
                        end=test_end,
                        params={
                            **{
                                parameter.id: parameter.default
                                for parameter in self.get_optimization_contract(
                                    config["strategy_id"]
                                ).parameters
                            },
                            **candidate["parameters"],
                        },
                        overrides={
                            "entry_signals": candidate.get(
                                "buy_signals", config.get("buy_signals", [])
                            ),
                            "exit_signals": candidate.get(
                                "sell_signals", config.get("sell_signals", [])
                            ),
                        },
                        asset_type=config["asset_type"],
                        matching=request.get("matching", "open_t+1"),
                        fees_pct=float(request.get("fees_pct", 0.0002)),
                        commission_pct=request.get("commission_pct"),
                        stamp_tax_pct=request.get("stamp_tax_pct"),
                        slippage_bps=float(request.get("slippage_bps", 5)),
                        mode=request.get("mode", "position"),
                        holding_days=int(request.get("holding_days", 5)),
                    ),
                    cancel_event=cancel_event,
                    result_policy=BacktestResultPolicy(),
                )
                if result.error:
                    break
                fold_stats.append(
                    {
                        "fold": fi,
                        "start": test_start.isoformat(),
                        "end": test_end.isoformat(),
                        "metrics": result.stats,
                        "trade_signature": [
                            f"{trade.get('symbol')}:{trade.get('entry_date')}:{trade.get('exit_date')}"
                            for trade in result.trades[:2000]
                        ],
                    }
                )
            if len(fold_stats) == len(folds):
                metrics = self._aggregate_metrics(fold_stats)
                trade_signature = sorted(
                    {item for fold in fold_stats for item in fold["trade_signature"]}
                )[:2000]
                scored.append(
                    {
                        "candidate_id": hashlib.sha256(
                            json.dumps(
                                [
                                    candidate.get("parameters", {}),
                                    candidate.get("buy_signals", ()),
                                    candidate.get("sell_signals", ()),
                                ],
                                sort_keys=True,
                                default=str,
                            ).encode()
                        ).hexdigest()[:16],
                        **candidate,
                        "folds": [
                            {key: value for key, value in fold.items() if key != "trade_signature"}
                            for fold in fold_stats
                        ],
                        "trade_signature": trade_signature,
                        "oos_metrics": metrics,
                    }
                )
            progress_cb(
                {
                    "type": "oos_progress",
                    "candidate": ci,
                    "total": len(candidates),
                    "folds_done": len(fold_stats),
                    "folds_total": len(folds),
                }
            )
        ranked = score_candidates(
            scored,
            request.get("weights", DEFAULT_WEIGHTS),
            max_drawdown=request.get("max_drawdown"),
            min_trades=request.get("min_trades", 0),
        )
        top = select_top_candidates(ranked)
        return {
            "top3": top,
            "candidates": ranked,
            "insufficient_recommendations": len(top) < 3,
            "stop_reason": request.get("stop_reason", "budget_exhausted"),
            "data_generation": self.data_generation(config["asset_type"]),
        }

    @staticmethod
    def _aggregate_metrics(folds):
        names = ("total_return", "max_drawdown", "win_rate", "n_trades")
        all_metrics = [fold["metrics"] for fold in folds]
        compounded = 1.0
        for metrics in all_metrics:
            compounded *= 1 + float(metrics.get("total_return", 0) or 0)
        drawdowns = [
            abs(float(metrics["max_drawdown"]))
            for metrics in all_metrics
            if metrics.get("max_drawdown") is not None
        ]
        wins = sum(
            float(metrics.get("win_rate", 0) or 0) * int(metrics.get("n_trades", 0) or 0)
            for metrics in all_metrics
        )
        trades = sum(int(metrics.get("n_trades", 0) or 0) for metrics in all_metrics)
        return {
            "oos_return": compounded - 1,
            "drawdown_improvement": -max(drawdowns) if drawdowns else None,
            "max_oos_drawdown": max(drawdowns) if drawdowns else None,
            "win_rate": wins / trades if trades else None,
            "trade_count": trades,
            "fold_metrics": [
                {name: metrics.get(name) for name in names} for metrics in all_metrics
            ],
        }

    def fingerprint(self, request: dict, candidate: dict, fold: tuple[date, date]):
        strategy = self.strategy_engine.get(request["strategy_id"])
        source_hash = ""
        if strategy.file_path and strategy.file_path.is_file():
            source_hash = hashlib.sha256(strategy.file_path.read_bytes()).hexdigest()
        payload = {
            "strategy": request["strategy_id"],
            "strategy_source": source_hash,
            "strategy_meta": strategy.meta,
            "params": candidate,
            "fold": [d.isoformat() for d in fold],
            "asset_type": request["asset_type"],
            "generation": self.data_generation(request["asset_type"]),
            "execution": {
                key: request.get(key)
                for key in (
                    "symbols",
                    "matching",
                    "fees_pct",
                    "commission_pct",
                    "stamp_tax_pct",
                    "slippage_bps",
                    "mode",
                    "holding_days",
                )
            },
            "seed": request.get("seed"),
            "optimizer_api_version": self.api_version,
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def _as_tuple(value):
    if isinstance(value, list):
        return tuple(_as_tuple(item) for item in value)
    return value


def _as_date(value):
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        return date.fromisoformat(value)
    raise TypeError("expected a date")


def _default_robust_boundaries(start, end, trading_dates, layout):
    dates = tuple(day for day in trading_dates if start <= day <= end)
    if layout == "holdout":
        try:
            holdout_start = end.replace(year=end.year - 2)
        except ValueError:
            holdout_start = end.replace(year=end.year - 2, day=28)
        holdout_index = bisect_left(dates, holdout_start)
        development_count = holdout_index
        if development_count < 3 or holdout_index >= len(dates):
            raise ValueError("date range cannot form three development windows and a holdout")
        quotient, remainder = divmod(development_count, 3)
        lengths = [quotient + (index < remainder) for index in range(3)]
        first = lengths[0]
        second = first + lengths[1]
        return (dates[0], dates[first], dates[second], dates[holdout_index])
    if layout == "diagnostic":
        if len(dates) < 3:
            raise ValueError("date range cannot form three diagnostic windows")
        quotient, remainder = divmod(len(dates), 3)
        first = quotient + (remainder > 0)
        second = first + quotient + (remainder > 1)
        return (dates[0], dates[first], dates[second])
    raise ValueError("layout must be 'holdout' or 'diagnostic'")


def _window_payload(window):
    return {
        "id": window.id,
        "start": window.start.isoformat(),
        "end": window.end.isoformat(),
        "role": window.role,
    }


def _add_months(day: date, months: int) -> date:
    month_index = day.year * 12 + day.month - 1 + months
    year, month0 = divmod(month_index, 12)
    month = month0 + 1
    return date(year, month, min(day.day, month_calendar.monthrange(year, month)[1]))


def _rolling_diagnostic_windows(start: date, end: date, trading_dates: tuple[date, ...]):
    from bisect import bisect_right

    windows = []
    cursor = start
    index = 1
    while True:
        window_end = _add_months(cursor, 24)
        if window_end > end:
            break
        left = bisect_left(trading_dates, cursor)
        right = bisect_right(trading_dates, window_end)
        if left < right:
            windows.append(EvaluationWindow(
                f"rolling-{index}", trading_dates[left], trading_dates[right - 1], "diagnostic"
            ))
            index += 1
        cursor = _add_months(cursor, 6)
    return tuple(windows)
