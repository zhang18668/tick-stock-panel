from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal

OPTIMIZER_API_VERSION = 1
ParameterType = Literal["int", "float", "bool", "enum"]


@dataclass(frozen=True)
class ParameterSpec:
    id: str
    label: str
    type: ParameterType
    default: Any
    minimum: float | int | None = None
    maximum: float | int | None = None
    step: float | int | None = None
    options: tuple[Any, ...] = ()
    optimizable: bool = True
    group: str | None = None
    description: str = ""

    def __post_init__(self) -> None:
        if not self.id or not isinstance(self.id, str):
            raise ValueError("parameter id must be a non-empty string")
        if self.type == "enum" and not self.options:
            raise ValueError(f"parameter {self.id} enum options must not be empty")
        if self.type in ("int", "float") and self.optimizable:
            if self.minimum is None or self.maximum is None or self.step is None:
                raise ValueError(f"parameter {self.id} requires minimum, maximum and step")
            if not all(math.isfinite(float(v)) for v in (self.minimum, self.maximum, self.step)):
                raise ValueError(f"parameter {self.id} bounds must be finite")
            if self.minimum > self.maximum or self.step <= 0:
                raise ValueError(f"parameter {self.id} has invalid bounds")
        if not self.validate_value(self.default):
            raise ValueError(f"parameter {self.id} default is outside its contract")

    def validate_value(self, value: Any) -> bool:
        if self.type == "bool":
            return type(value) is bool
        if self.type == "enum":
            return value in self.options
        if type(value) is bool or not isinstance(value, (int, float)):
            return False
        if self.type == "int" and type(value) is not int:
            return False
        number = float(value)
        if not math.isfinite(number):
            return False
        return (self.minimum is None or number >= float(self.minimum)) and (
            self.maximum is None or number <= float(self.maximum)
        )


@dataclass(frozen=True)
class StrategyOptimizationContract:
    strategy_id: str
    name: str
    asset_type: str
    parameters: tuple[ParameterSpec, ...]
    buy_signals: tuple[str, ...] = ()
    sell_signals: tuple[str, ...] = ()
    max_signal_combinations: int = 16
    constraints: tuple[dict[str, Any], ...] = ()
    version: str = "1"

    def __post_init__(self) -> None:
        ids = [p.id for p in self.parameters]
        if len(ids) != len(set(ids)):
            raise ValueError("parameter ids must be unique")
        if sum(parameter.optimizable for parameter in self.parameters) > 20:
            raise ValueError("strategy exceeds the 20 optimizable parameter limit")
        if self.max_signal_combinations < 1:
            raise ValueError("max_signal_combinations must be positive")
        known = set(ids)
        for constraint in self.constraints:
            if set(constraint) != {"left", "op", "right"}:
                raise ValueError("constraint must define left, op and right")
            if constraint["left"] not in known or (
                isinstance(constraint["right"], str) and constraint["right"] not in known
            ):
                raise ValueError("constraint references an unknown parameter")
            if constraint["op"] not in {"lt", "lte", "gt", "gte", "eq", "ne"}:
                raise ValueError("unsupported parameter constraint operator")
            left_spec = next(
                parameter for parameter in self.parameters if parameter.id == constraint["left"]
            )
            right_spec = next(
                (parameter for parameter in self.parameters if parameter.id == constraint["right"]),
                None,
            )
            left, right = (
                left_spec.default,
                right_spec.default if right_spec else constraint["right"],
            )
            if not _constraint_matches(left, constraint["op"], right):
                raise ValueError("parameter defaults violate a declared constraint")


@dataclass(frozen=True)
class OptimizationRunConfig:
    strategy_id: str
    asset_type: str
    start: date
    end: date
    parameters: dict[str, Any] = field(default_factory=dict)
    buy_signals: tuple[str, ...] = ()
    sell_signals: tuple[str, ...] = ()
    seed: int = 0
    max_rounds: int = 10
    candidates_per_round: int = 50
    total_candidates: int = 500


def _constraint_matches(left, operator, right):
    try:
        return {
            "lt": lambda: left < right,
            "lte": lambda: left <= right,
            "gt": lambda: left > right,
            "gte": lambda: left >= right,
            "eq": lambda: left == right,
            "ne": lambda: left != right,
        }[operator]()
    except TypeError as exc:
        raise ValueError("parameter constraint compares incompatible types") from exc
