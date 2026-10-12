from datetime import date

import pytest

from app.strategy_optimizer.contracts import (
    EvaluationWindow,
    RobustCandidate,
    RobustGates,
    SegmentMetrics,
    SegmentObservation,
)
from app.strategy_optimizer.robust_scoring import (
    annualize,
    percentile_ranks,
    score_development,
    score_neighborhood,
)


def test_ties_and_single_candidate_are_neutral():
    assert percentile_ranks((4.0,)) == (0.5,)
    assert percentile_ranks((1.0, 2.0, 2.0)) == (0.0, 0.75, 0.75)


def test_annualization_rejects_invalid_nav():
    with pytest.raises(ValueError):
        annualize(0.0, 365)
    assert annualize(1.1, 365) == pytest.approx(0.1)


def test_complete_candidate_is_scored_and_relative_gate_boundary_is_inclusive():
    windows = tuple(
        EvaluationWindow(f"d-{index}", date(2020, index, 1), date(2020, index, 28), "development")
        for index in (1, 2, 3)
    )
    candidate = RobustCandidate(
        "candidate-a",
        {"x": 1},
        (),
        (),
        tuple(
            SegmentObservation(
                window.id,
                SegmentMetrics(0.1, 0.1, 30, delta),
            )
            for window, delta in zip(windows, (0.01, 0.0, -0.03), strict=True)
        ),
    )

    (ranked,) = score_development(
        (candidate,),
        RobustGates(all_segment_percentile=0.5, strong_segment_percentile=0.5),
    )

    assert ranked.base_score == pytest.approx(0.5)
    assert ranked.segment_scores == (0.5, 0.5, 0.5)
    assert ranked.eligible
    assert ranked.robust_score is None


def test_incomplete_segment_cannot_become_a_zero_score_recommendation():
    candidate = RobustCandidate(
        "candidate-a",
        {"x": 1},
        (),
        (),
        tuple(SegmentObservation(f"d-{index}", None, "no trades") for index in range(1, 4)),
    )

    (ranked,) = score_development((candidate,), RobustGates())

    assert ranked.base_score is None
    assert not ranked.eligible
    assert ranked.failures


def test_zero_trade_candidate_is_not_rankable_when_minimum_gate_is_zero():
    candidate = RobustCandidate(
        "no-trades", {"x": 1}, (), (),
        tuple(
            SegmentObservation(window_id, SegmentMetrics(0.0, 0.0, 0, 0.0))
            for window_id in ("d-1", "d-2", "d-3")
        ),
    )

    (ranked,) = score_development(
        (candidate,),
        RobustGates(min_trades=0, min_positive_segments=1,
                    all_segment_percentile=0, strong_segment_percentile=0),
    )

    assert ranked.base_score is None
    assert not ranked.eligible
    assert "segment 1: no trades" in ranked.failures


def test_baseline_floor_is_inclusive_but_lower_values_fail():
    windows = tuple(
        EvaluationWindow(f"d-{index}", date(2020, index, 1), date(2020, index, 28), "development")
        for index in (1, 2, 3)
    )

    def candidate(candidate_id, last_delta):
        deltas = (0.02, 0.01, last_delta)
        return RobustCandidate(
            candidate_id,
            {"x": 1},
            (),
            (),
            tuple(
                SegmentObservation(window.id, SegmentMetrics(0.1, 0.1, 30, delta))
                for window, delta in zip(windows, deltas, strict=True)
            ),
        )

    gates = RobustGates(all_segment_percentile=0.0, strong_segment_percentile=0.0)
    at_floor, below_floor = score_development(
        (candidate("at-floor", -0.03), candidate("below-floor", -0.03001)), gates
    )

    assert "relative baseline floor not met" not in at_floor.failures
    assert "relative baseline floor not met" in below_floor.failures


def test_neighborhood_score_requires_complete_evidence_and_uses_stability():
    windows = tuple(
        EvaluationWindow(f"d-{index}", date(2020, index, 1), date(2020, index, 28), "development")
        for index in (1, 2, 3)
    )

    def candidate(candidate_id):
        return RobustCandidate(
            candidate_id,
            {"x": 1},
            (),
            (),
            tuple(
                SegmentObservation(window.id, SegmentMetrics(0.1, 0.1, 30, 0.01))
                for window in windows
            ),
        )

    gate = RobustGates(all_segment_percentile=0.0, strong_segment_percentile=0.0)
    ranked = score_development((candidate("center"), candidate("neighbor")), gate)
    center = score_neighborhood(ranked[0], (ranked[1],), gate)

    assert center.stability == 1.0
    assert center.robust_score == pytest.approx(
        0.5 * min(center.segment_scores) + 0.3 * sum(center.segment_scores) / 3 + 0.2
    )


def test_neighborhood_scores_use_the_frozen_main_candidate_distribution():
    windows = tuple(
        EvaluationWindow(f"d-{index}", date(2020, index, 1), date(2020, index, 28), "development")
        for index in (1, 2, 3)
    )

    def candidate(candidate_id, annualized_return):
        return RobustCandidate(
            candidate_id,
            {"x": annualized_return},
            (),
            (),
            tuple(
                SegmentObservation(window.id, SegmentMetrics(annualized_return, 0.1, 30, 0.01))
                for window in windows
            ),
        )

    gates = RobustGates(all_segment_percentile=0.0, strong_segment_percentile=0.0)
    main = (candidate("main-low", 0.1), candidate("main-mid", 0.2), candidate("main-high", 0.3))
    first = score_development(
        (candidate("neighbor", 0.15),), gates, reference_candidates=main
    )[0]
    with_other_neighbors = score_development(
        (candidate("neighbor", 0.15), candidate("other", 0.25)),
        gates,
        reference_candidates=main,
    )[0]

    assert first.segment_scores == with_other_neighbors.segment_scores
    assert first.segment_percentiles == with_other_neighbors.segment_percentiles
