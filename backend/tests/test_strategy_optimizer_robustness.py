import threading
from datetime import date

from app.strategy_optimizer.contracts import (
    EvaluationWindow,
    RobustGates,
    RobustTimePlan,
    SegmentMetrics,
    SegmentObservation,
)
from app.strategy_optimizer.robustness import RobustnessRunner
from app.strategy_optimizer.search import Candidate


class FakeSearch:
    def __init__(self):
        self.parameters = ()
        self.constraints = ()
        self.base_values = {}
        self.seen = set()
        self.prior_scores = []
        self.next_candidates = []

    def first_round(self, limit):
        candidates = [Candidate({"x": 1}), Candidate({"x": 2})]
        return candidates[:limit]

    def next_round(self, previous, limit):
        self.prior_scores.append([row["score"] for row in previous])
        return self.next_candidates[:limit]


def windows():
    return RobustTimePlan(
        tuple(
            EvaluationWindow(f"dev-{index}", date(2020, index, 1), date(2020, index, 28), "development")
            for index in (1, 2, 3)
        ),
        EvaluationWindow("holdout", date(2021, 1, 1), date(2021, 12, 31), "holdout"),
    )


def test_search_evaluates_each_candidate_on_all_development_windows_only():
    calls = []

    def evaluate(candidate, window, include_curve):
        calls.append((candidate.parameters, window.id, include_curve))
        return SegmentObservation(
            window.id,
            SegmentMetrics(0.1, 0.05, 30, 0.0),
        )

    runner = RobustnessRunner(evaluate, FakeSearch())
    result = runner.run(
        {
            "time_plan": windows(),
            "gates": RobustGates(all_segment_percentile=0, strong_segment_percentile=0),
            "total_candidates": 2,
            "candidates_per_round": 2,
            "max_rounds": 1,
            "neighbor_centers": 0,
            "baseline_parameters": {"x": 1},
        },
        lambda _event: None,
        threading.Event(),
    )

    assert result["stop_reason"] == "budget_exhausted"
    assert len(result["candidates"]) == 2
    assert all(window_id.startswith("dev-") for _, window_id, _ in calls)
    assert all(not include_curve for _, _, include_curve in calls)
    assert {parameters["x"] for parameters, _, _ in calls} == {1, 2}


def test_candidate_failure_is_preserved_and_does_not_skip_later_segments():
    calls = []

    def evaluate(candidate, window, include_curve):
        calls.append(window.id)
        if candidate.parameters["x"] == 2 and window.id == "dev-1":
            raise RuntimeError("broken segment")
        return SegmentObservation(window.id, SegmentMetrics(0.1, 0.05, 30, 0.0))

    result = RobustnessRunner(evaluate, FakeSearch()).run(
        {
            "time_plan": windows(),
            "gates": RobustGates(all_segment_percentile=0, strong_segment_percentile=0),
            "total_candidates": 2,
            "candidates_per_round": 2,
            "max_rounds": 1,
            "neighbor_centers": 0,
            "baseline_parameters": {"x": 1},
        },
        lambda _event: None,
        threading.Event(),
    )

    failed = next(row for row in result["candidate_details"] if row["parameters"]["x"] == 2)
    assert failed["segments"][0]["failure"] == "broken segment"
    assert calls.count("dev-2") >= 2
    assert calls.count("dev-3") >= 2


def test_next_round_uses_cumulative_candidate_scores_and_references_are_cached():
    calls = []

    def evaluate(candidate, window, include_curve):
        calls.append((candidate.parameters, window.id))
        value = 0.1 if candidate.parameters["x"] != 9 else 0.2
        return SegmentObservation(window.id, SegmentMetrics(value, 0.05, 30, 0.0))

    search = FakeSearch()
    search.next_candidates = [Candidate({"x": 3})]
    RobustnessRunner(evaluate, search).run(
        {
            "time_plan": windows(),
            "gates": RobustGates(all_segment_percentile=0, strong_segment_percentile=0),
            "total_candidates": 3,
            "candidates_per_round": 2,
            "max_rounds": 2,
            "neighbor_centers": 0,
            "baseline_parameters": {"x": 1},
            "reference_candidates": [("reference-1", Candidate({"x": 9}))],
        },
        lambda _event: None,
        threading.Event(),
    )

    assert len(search.prior_scores[0]) == 2
    assert all(value == search.prior_scores[0][0] for value in search.prior_scores[0])
    assert sum(parameters == {"x": 9} for parameters, _window in calls) == 3
