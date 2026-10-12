from datetime import date

import pytest

from app.strategy_optimizer.time_plan import build_time_plan


def test_split_uses_trading_dates_and_is_disjoint():
    days = tuple(date(2020, 1, n) for n in range(1, 11))

    plan = build_time_plan(
        days[0], days[-1], days, (days[0], days[3], days[6], days[8]), "holdout"
    )

    assert [(window.start, window.end) for window in plan.development] == [
        (days[0], days[2]),
        (days[3], days[5]),
        (days[6], days[7]),
    ]
    assert (plan.holdout.start, plan.holdout.end) == (days[8], days[9])


def test_diagnostic_layout_uses_three_disjoint_windows_without_holdout():
    days = tuple(date(2020, 1, n) for n in range(1, 11))

    plan = build_time_plan(days[0], days[-1], days, (days[0], days[3], days[6]), "diagnostic")

    assert [(window.start, window.end) for window in plan.development] == [
        (days[0], days[2]),
        (days[3], days[5]),
        (days[6], days[9]),
    ]
    assert plan.holdout is None


@pytest.mark.parametrize(
    ("boundaries", "layout"),
    [
        ((date(2020, 1, 1), date(2020, 1, 4)), "holdout"),
        ((date(2020, 1, 1), date(2020, 1, 4), date(2020, 1, 7)), "unknown"),
        ((date(2020, 1, 4), date(2020, 1, 1), date(2020, 1, 7)), "diagnostic"),
    ],
)
def test_rejects_invalid_layout_or_boundaries(boundaries, layout):
    days = tuple(date(2020, 1, n) for n in range(1, 11))

    with pytest.raises(ValueError):
        build_time_plan(days[0], days[-1], days, boundaries, layout)
