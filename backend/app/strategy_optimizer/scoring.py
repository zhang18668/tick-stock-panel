from __future__ import annotations

import math
from typing import Any

DEFAULT_WEIGHTS = {
    "oos_return": 0.55,
    "drawdown_improvement": 0.20,
    "win_rate": 0.15,
    "trade_count": 0.10,
}


def _finite(value: Any) -> float | None:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def score_candidates(
    candidates: list[dict], weights=None, *, max_drawdown=None, min_trades=0
) -> list[dict]:
    weights = dict(weights or DEFAULT_WEIGHTS)
    if abs(sum(weights.values()) - 1) > 1e-9:
        raise ValueError("weights must sum to 1")
    valid = []
    for row in candidates:
        metrics = row.get("oos_metrics", {})
        values = {name: _finite(metrics.get(name)) for name in weights}
        if any(v is None for v in values.values()):
            row = {**row, "eligible": False, "failure": "missing_or_non_finite_metric"}
            continue
        actual_drawdown = _finite(metrics.get("max_oos_drawdown"))
        if actual_drawdown is None:
            actual_drawdown = abs(values.get("drawdown_improvement", 0))
        if max_drawdown is not None and actual_drawdown > max_drawdown:
            row = {**row, "eligible": False, "failure": "hard_gate_drawdown"}
            continue
        if values.get("trade_count", 0) < min_trades:
            row = {**row, "eligible": False, "failure": "hard_gate_trade_count"}
            continue
        row = {**row, "eligible": True, "metrics": values}
        valid.append(row)
    if not valid:
        return []
    bounds = {}
    for name in weights:
        numbers = sorted(row["metrics"][name] for row in valid)
        low = numbers[int((len(numbers) - 1) * 0.1)]
        high = numbers[int((len(numbers) - 1) * 0.9)]
        bounds[name] = (low, high)
    for row in valid:
        normalized = {}
        for name, (low, high) in bounds.items():
            value = min(high, max(low, row["metrics"][name]))
            if name == "trade_count":
                normalized[name] = min(1.0, value / max(float(min_trades), 1.0))
            elif high == low:
                normalized[name] = 0.5
            else:
                normalized[name] = (value - low) / (high - low)
        row["component_scores"] = normalized
        row["score"] = sum(normalized[name] * weight for name, weight in weights.items())
    return sorted(valid, key=lambda row: row["score"], reverse=True)


def select_top_candidates(candidates: list[dict], limit=3, distance_threshold=0.05) -> list[dict]:
    chosen = []
    seen = set()
    for row in candidates:
        key = (
            tuple(sorted(row.get("parameters", {}).items())),
            tuple(row.get("buy_signals", ())),
            tuple(row.get("sell_signals", ())),
        )
        if key in seen:
            continue
        similar = False
        for existing in chosen:
            left = row.get("parameters", {})
            right = existing.get("parameters", {})
            if set(left) != set(right):
                continue
            distances = []
            for name in left:
                if isinstance(left[name], (int, float)) and isinstance(right[name], (int, float)):
                    scale = max(abs(float(left[name])), abs(float(right[name])), 1.0)
                    distances.append(abs(float(left[name]) - float(right[name])) / scale)
                else:
                    distances.append(0.0 if left[name] == right[name] else 1.0)
            left_trades = set(row.get("trade_signature", ()))
            right_trades = set(existing.get("trade_signature", ()))
            union = left_trades | right_trades
            similarity = len(left_trades & right_trades) / len(union) if union else 0.0
            if distances and max(distances) < distance_threshold and similarity >= 0.9:
                similar = True
                break
        if similar:
            continue
        seen.add(key)
        chosen.append(row)
        if len(chosen) >= limit:
            break
    return chosen
