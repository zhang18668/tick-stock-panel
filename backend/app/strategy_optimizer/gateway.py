from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import replace
from datetime import date, timedelta

from app.backtest.strategy import (
    BacktestResultPolicy,
    StrategyBacktestConfig,
    StrategyBacktestService,
)

from .contracts import ParameterSpec, StrategyOptimizationContract
from .scoring import DEFAULT_WEIGHTS, score_candidates, select_top_candidates
from .search import AdaptiveSearchService


class StrategyOptimizationGateway:
    """Adapter over the existing strategy backtest service; no separate simulator."""

    api_version = 1

    def __init__(self, service: StrategyBacktestService, strategy_engine, *, repository=None):
        self.service = service
        self.strategy_engine = strategy_engine
        self.repository = repository

    def data_generation(self, asset_type: str) -> str:
        getter = getattr(self.repository, "get_matrix_data_generation", None)
        return str(getter(asset_type)) if callable(getter) else ""

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
