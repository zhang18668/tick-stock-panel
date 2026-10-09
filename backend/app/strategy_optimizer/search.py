from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any

from .contracts import ParameterSpec, _constraint_matches


@dataclass(frozen=True)
class Candidate:
    parameters: dict[str, Any]
    buy_signals: tuple[str, ...] = ()
    sell_signals: tuple[str, ...] = ()

    @property
    def key(self) -> tuple:
        return (tuple(sorted(self.parameters.items())), self.buy_signals, self.sell_signals)


class AdaptiveSearchService:
    def __init__(
        self,
        parameters: tuple[ParameterSpec, ...],
        buy_signals=(),
        sell_signals=(),
        *,
        seed=0,
        constraints=(),
        base_values=None,
    ):
        self.parameters = parameters
        self.buy_signals = tuple(buy_signals)
        self.sell_signals = tuple(sell_signals)
        self.random = random.Random(seed)
        self.seen: set[tuple] = set()
        self.constraints = tuple(constraints)
        self.base_values = dict(base_values or {})
        self.round_index = 0

    def first_round(self, limit: int) -> list[Candidate]:
        candidates = [
            Candidate(
                {p.id: p.default for p in self.parameters},
                self.buy_signals,
                self.sell_signals,
            )
        ]
        for p in self.parameters:
            if p.type in ("int", "float"):
                midpoint = (float(p.minimum) + float(p.maximum)) / 2
                steps = round((midpoint - float(p.minimum)) / float(p.step))
                midpoint = min(float(p.maximum), float(p.minimum) + steps * float(p.step))
                midpoint = round(midpoint) if p.type == "int" else round(midpoint, 8)
                candidates += [
                    Candidate({**candidates[0].parameters, p.id: p.minimum}),
                    Candidate({**candidates[0].parameters, p.id: midpoint}),
                    Candidate({**candidates[0].parameters, p.id: p.maximum}),
                ]
            elif p.type == "bool":
                candidates.append(Candidate({**candidates[0].parameters, p.id: not p.default}))
            elif p.options:
                candidates.extend(
                    Candidate({**candidates[0].parameters, p.id: value}) for value in p.options
                )
        while len(candidates) < limit:
            candidates.append(self._random_candidate())
        return self._unique(candidates, limit, refill=True)

    def next_round(self, previous: list[dict], limit: int) -> list[Candidate]:
        self.round_index += 1
        ranked = sorted(
            previous, key=lambda item: float(item.get("score", float("-inf"))), reverse=True
        )
        elite = ranked[: min(5, len(ranked))]
        anchor = elite[self.random.randrange(len(elite))].get("parameters", {}) if elite else {}
        out: list[Candidate] = []
        exploit = round(limit * 0.8)
        for _ in range(exploit):
            values = {p.id: self._nearby(p, anchor.get(p.id, p.default)) for p in self.parameters}
            out.append(Candidate(values))
        while len(out) < limit:
            out.append(self._random_candidate())
        return self._unique(out, limit, refill=True)

    def _random_candidate(self):
        return Candidate(
            {p.id: self._random_value(p) for p in self.parameters},
            tuple(
                self.random.sample(self.buy_signals, self.random.randint(0, len(self.buy_signals)))
            )
            if self.buy_signals
            else (),
            tuple(
                self.random.sample(
                    self.sell_signals, self.random.randint(0, len(self.sell_signals))
                )
            )
            if self.sell_signals
            else (),
        )

    def _nearby(self, p: ParameterSpec, value: Any) -> Any:
        if p.type not in ("int", "float"):
            return value if self.random.random() < 0.7 else self._random_value(p)
        span = float(p.maximum) - float(p.minimum)
        radius = span * 0.15 / max(1, self.round_index)
        result = float(value) + self.random.uniform(-radius, radius)
        steps = round((result - float(p.minimum)) / float(p.step))
        result = float(p.minimum) + steps * float(p.step)
        result = max(float(p.minimum), min(float(p.maximum), result))
        if p.type == "int":
            return round(result)
        return round(result, 8)

    def _random_value(self, p: ParameterSpec) -> Any:
        if p.type == "bool":
            return bool(self.random.getrandbits(1))
        if p.type == "enum":
            return self.random.choice(p.options)
        count = int((float(p.maximum) - float(p.minimum)) / float(p.step))
        value = float(p.minimum) + self.random.randint(0, max(0, count)) * float(p.step)
        return round(value) if p.type == "int" else round(value, 8)

    def _unique(self, candidates: list[Candidate], limit: int, *, refill=False) -> list[Candidate]:
        result = []
        index = 0
        attempts = 0
        while index < len(candidates) and len(result) < limit:
            candidate = candidates[index]
            index += 1
            if candidate.key in self.seen or not self._valid(candidate):
                attempts += 1
                if refill and attempts < limit * 100:
                    candidates.append(self._random_candidate())
                continue
            self.seen.add(candidate.key)
            result.append(candidate)
        return result

    def _valid(self, candidate: Candidate) -> bool:
        values = {**self.base_values, **candidate.parameters}
        for constraint in self.constraints:
            right = constraint["right"]
            if isinstance(right, str) and right in values:
                right = values[right]
            if not _constraint_matches(values[constraint["left"]], constraint["op"], right):
                return False
        return True
