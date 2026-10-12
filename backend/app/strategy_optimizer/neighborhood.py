from __future__ import annotations

import math

from .contracts import ParameterSpec, _constraint_matches
from .search import Candidate


def generate_neighbors(
    center: Candidate,
    parameters: tuple[ParameterSpec, ...],
    constraints: tuple[dict, ...],
    base_values: dict,
    limit: int = 20,
) -> tuple[Candidate, ...]:
    if limit < 0:
        raise ValueError("neighbor limit must be non-negative")
    specs = {parameter.id: parameter for parameter in parameters}
    rows: list[Candidate] = []
    seen: set[tuple] = set()
    for parameter_id in sorted(specs):
        parameter = specs[parameter_id]
        if parameter.type not in {"int", "float"} or not parameter.optimizable:
            continue
        current = center.parameters.get(parameter_id)
        if not parameter.validate_value(current):
            continue
        minimum = float(parameter.minimum)
        maximum = float(parameter.maximum)
        step = float(parameter.step)
        raw_index = (float(current) - minimum) / step
        index = round(raw_index)
        if not math.isclose(raw_index, index, abs_tol=1e-8):
            continue
        max_index = math.floor((maximum - minimum) / step + 1e-8)
        for direction in (-1, 1):
            neighbor_index = index + direction
            if not 0 <= neighbor_index <= max_index:
                continue
            value = minimum + neighbor_index * step
            value = round(value) if parameter.type == "int" else round(value, 8)
            if not parameter.validate_value(value):
                continue
            candidate_values = {**center.parameters, parameter_id: value}
            constraint_values = {**base_values, **candidate_values}
            valid = True
            for constraint in constraints:
                right = constraint["right"]
                if isinstance(right, str) and right in constraint_values:
                    right = constraint_values[right]
                if not _constraint_matches(
                    constraint_values[constraint["left"]], constraint["op"], right
                ):
                    valid = False
                    break
            if not valid:
                continue
            candidate = Candidate(
                candidate_values,
                center.buy_signals,
                center.sell_signals,
            )
            if candidate.key in seen:
                continue
            seen.add(candidate.key)
            rows.append(candidate)
    return tuple(rows[:limit])


def count_legal_neighbors(
    center: Candidate,
    parameters: tuple[ParameterSpec, ...],
    constraints: tuple[dict, ...],
    base_values: dict,
) -> int:
    """Count the complete legal neighborhood before applying any coverage cap."""
    return len(generate_neighbors(center, parameters, constraints, base_values, limit=2**31 - 1))
