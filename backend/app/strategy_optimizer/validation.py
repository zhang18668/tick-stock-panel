from __future__ import annotations

import math
from datetime import date
from typing import Any

from .contracts import OptimizationRunConfig, StrategyOptimizationContract

_FIELDS = {
    "strategy_id",
    "asset_type",
    "start",
    "end",
    "parameters",
    "buy_signals",
    "sell_signals",
    "seed",
    "max_rounds",
    "candidates_per_round",
    "total_candidates",
    "objective",
    "train_days",
    "test_days",
    "step_days",
    "symbols",
    "matching",
    "fees_pct",
    "commission_pct",
    "stamp_tax_pct",
    "slippage_bps",
    "mode",
    "holding_days",
    "weights",
    "max_drawdown",
    "min_trades",
    "train_fraction",
    "convergence_threshold",
}


def validate_run_config(
    raw: dict[str, Any], contract: StrategyOptimizationContract
) -> OptimizationRunConfig:
    unknown = set(raw) - _FIELDS
    if unknown:
        raise ValueError(f"unknown field: {sorted(unknown)[0]}")
    if raw.get("strategy_id") != contract.strategy_id:
        raise ValueError("strategy_id does not match contract")
    if raw.get("asset_type") != contract.asset_type:
        raise ValueError("asset_type does not match contract")
    try:
        start = date.fromisoformat(raw["start"]) if isinstance(raw["start"], str) else raw["start"]
        end = date.fromisoformat(raw["end"]) if isinstance(raw["end"], str) else raw["end"]
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("start and end must be ISO dates") from exc
    if not isinstance(start, date) or not isinstance(end, date) or start > end:
        raise ValueError("invalid date range")
    if (end - start).days > 20 * 366:
        raise ValueError("date range exceeds the 20 year limit")
    params = raw.get("parameters", {})
    if not isinstance(params, dict):
        raise ValueError("parameters must be an object")
    specs = {p.id: p for p in contract.parameters}
    if set(params) - set(specs):
        raise ValueError(f"unknown parameter: {next(iter(set(params) - set(specs)))}")
    for pid, value in params.items():
        if not isinstance(value, dict) or set(value) - {"min", "max", "step", "values"}:
            raise ValueError(f"invalid parameter range: {pid}")
        for key, number in value.items():
            if key != "values" and (
                not isinstance(number, (int, float))
                or isinstance(number, bool)
                or not math.isfinite(float(number))
            ):
                raise ValueError(f"parameter range must be finite: {pid}")
        spec = specs[pid]
        if not spec.optimizable:
            raise ValueError(f"parameter is not optimizable: {pid}")
        if "values" in value:
            if (
                spec.type not in {"bool", "enum"}
                or not isinstance(value["values"], list)
                or not value["values"]
            ):
                raise ValueError(f"invalid discrete values: {pid}")
            if any(not spec.validate_value(item) for item in value["values"]):
                raise ValueError(f"parameter values outside contract: {pid}")
        if "min" in value and not spec.validate_value(value["min"]):
            raise ValueError(f"parameter range outside contract: {pid}")
        if "max" in value and not spec.validate_value(value["max"]):
            raise ValueError(f"parameter range outside contract: {pid}")
        if "min" in value and "max" in value and value["min"] > value["max"]:
            raise ValueError(f"parameter range min exceeds max: {pid}")
        step = value.get("step", spec.step)
        if spec.type in {"int", "float"} and (step is None or step <= 0):
            raise ValueError(f"parameter range step must be positive: {pid}")
    buys = tuple(raw.get("buy_signals", ()))
    sells = tuple(raw.get("sell_signals", ()))
    if len(buys) != len(set(buys)) or len(sells) != len(set(sells)):
        raise ValueError("signal lists must not contain duplicates")
    if not set(buys) <= set(contract.buy_signals) or not set(sells) <= set(contract.sell_signals):
        raise ValueError("unknown signal")
    if len(buys) + len(sells) > contract.max_signal_combinations:
        raise ValueError("signal combination limit exceeded")
    if len(params) > 20:
        raise ValueError("parameter dimension limit exceeded")
    rounds = int(raw.get("max_rounds", 10))
    per_round = int(raw.get("candidates_per_round", 50))
    total = int(raw.get("total_candidates", rounds * per_round))
    if not (
        1 <= rounds <= 10 and 1 <= per_round <= 50 and 1 <= total <= 500 and total >= per_round
    ):
        raise ValueError("optimization budget exceeds limits")
    return OptimizationRunConfig(
        raw["strategy_id"],
        raw["asset_type"],
        start,
        end,
        dict(params),
        buys,
        sells,
        int(raw.get("seed", 0)),
        rounds,
        per_round,
        total,
    )
