from __future__ import annotations

from bisect import bisect_left
from datetime import date
from itertools import pairwise

from .contracts import EvaluationWindow, RobustTimePlan


def build_time_plan(
    start: date,
    end: date,
    trading_dates: tuple[date, ...],
    boundaries: tuple[date, ...],
    layout: str,
) -> RobustTimePlan:
    """Split a range on an authoritative, ordered trading-date sequence."""
    if start > end:
        raise ValueError("invalid date range")
    expected_boundaries = {"holdout": 4, "diagnostic": 3}.get(layout)
    if expected_boundaries is None:
        raise ValueError("layout must be 'holdout' or 'diagnostic'")
    if len(boundaries) != expected_boundaries:
        raise ValueError(f"{layout} layout requires {expected_boundaries} boundaries")

    dates = tuple(day for day in trading_dates if start <= day <= end)
    if not dates:
        raise ValueError("no trading dates in requested range")
    if any(left >= right for left, right in pairwise(trading_dates)):
        raise ValueError("trading dates must be strictly increasing")

    cuts = [bisect_left(dates, boundary) for boundary in boundaries]
    if cuts != sorted(set(cuts)) or cuts[0] != 0:
        raise ValueError("invalid normalized boundaries")
    if cuts[-1] >= len(dates):
        raise ValueError("time window has no trading dates")

    development_count = 3
    development_cuts = cuts[:development_count]
    development_ends = [*development_cuts[1:], cuts[-1] if layout == "holdout" else len(dates)]
    development = []
    for index, (left, right) in enumerate(zip(development_cuts, development_ends, strict=True), 1):
        if left >= right:
            raise ValueError("development window has no trading dates")
        development.append(
            EvaluationWindow(
                id=f"development-{index}",
                start=dates[left],
                end=dates[right - 1],
                role="development",
            )
        )

    holdout = None
    if layout == "holdout":
        left = cuts[-1]
        if left >= len(dates):
            raise ValueError("holdout window has no trading dates")
        holdout = EvaluationWindow(
            id="holdout-1",
            start=dates[left],
            end=dates[-1],
            role="holdout",
        )
    return RobustTimePlan(tuple(development), holdout)
