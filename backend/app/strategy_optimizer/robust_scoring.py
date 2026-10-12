from __future__ import annotations

import math
from itertools import pairwise

from .contracts import RankedCandidate, RobustCandidate, RobustGates


def annualize(ending_nav: float, elapsed_days: int) -> float:
    if not math.isfinite(ending_nav) or ending_nav <= 0:
        raise ValueError("ending NAV must be finite and positive")
    if elapsed_days < 1:
        raise ValueError("elapsed days must be positive")
    return ending_nav ** (365.0 / elapsed_days) - 1.0


def percentile_ranks(values: tuple[float, ...]) -> tuple[float, ...]:
    if not values:
        return ()
    if any(not math.isfinite(value) for value in values):
        raise ValueError("percentile values must be finite")
    if len(values) == 1:
        return (0.5,)
    ordered = sorted(enumerate(values), key=lambda item: item[1])
    ranks = [0.0] * len(values)
    left = 0
    while left < len(ordered):
        right = left + 1
        while right < len(ordered) and ordered[right][1] == ordered[left][1]:
            right += 1
        percentile = ((left + right - 1) / 2) / (len(ordered) - 1)
        for original_index, _ in ordered[left:right]:
            ranks[original_index] = percentile
        left = right
    return tuple(ranks)


def _percentile_against(value: float, reference: tuple[float, ...]) -> float:
    if not reference:
        raise ValueError("percentile reference must not be empty")
    ranks = percentile_ranks(reference)
    ordered = sorted(zip(reference, ranks, strict=True))
    if len(ordered) == 1:
        return 0.5
    for reference_value in sorted({item[0] for item in ordered}):
        if value == reference_value:
            tied = [rank for candidate, rank in ordered if candidate == value]
            return sum(tied) / len(tied)
    if value < ordered[0][0]:
        return 0.0
    if value > ordered[-1][0]:
        return 1.0
    for (left, left_rank), (right, right_rank) in pairwise(ordered):
        if left < value < right:
            fraction = (value - left) / (right - left)
            return left_rank + fraction * (right_rank - left_rank)
    raise AssertionError("percentile interpolation did not find a range")


def score_development(
    candidates: tuple[RobustCandidate, ...],
    gates: RobustGates,
    *,
    reference_candidates: tuple[RobustCandidate, ...] | None = None,
) -> tuple[RankedCandidate, ...]:
    if not candidates:
        return ()
    segment_count = len(candidates[0].segments)
    if segment_count != 3 or any(len(item.segments) != segment_count for item in candidates):
        raise ValueError("robust development scoring requires three segments per candidate")

    metrics_by_id = {item.candidate_id: [segment.metrics for segment in item.segments] for item in candidates}
    rankable: set[str] = set()
    failure_map: dict[str, list[str]] = {item.candidate_id: [] for item in candidates}
    for item in candidates:
        metrics = metrics_by_id[item.candidate_id]
        if any(value is None for value in metrics):
            failure_map[item.candidate_id].extend(
                segment.failure or "missing segment metrics"
                for segment in item.segments
                if segment.metrics is None
            )
            continue
        typed_metrics = [value for value in metrics if value is not None]
        if any(
            not all(
                math.isfinite(value)
                for value in (
                    row.annualized_return,
                    row.max_drawdown,
                    row.baseline_delta,
                )
            )
            or row.max_drawdown < 0
            or row.trade_count < 0
            for row in typed_metrics
        ):
            failure_map[item.candidate_id].append("invalid segment metrics")
            continue
        rankable.add(item.candidate_id)
        for index, row in enumerate(typed_metrics, 1):
            if row.max_drawdown > gates.max_drawdown:
                failure_map[item.candidate_id].append(f"segment {index}: drawdown exceeds limit")
            if row.trade_count < gates.min_trades:
                failure_map[item.candidate_id].append(f"segment {index}: insufficient trades")

    rankable = {
        candidate_id
        for candidate_id in rankable
        if not any(
            reason.endswith("drawdown exceeds limit") or reason.endswith("insufficient trades")
            for reason in failure_map[candidate_id]
        )
    }
    reference_ranked = (
        score_development(reference_candidates, gates)
        if reference_candidates is not None
        else ()
    )
    per_candidate_scores: dict[str, tuple[float, ...]] = {}
    for segment_index in range(segment_count):
        ids = [item.candidate_id for item in candidates if item.candidate_id in rankable]
        if not ids:
            break
        rows = [metrics_by_id[candidate_id][segment_index] for candidate_id in ids]
        if reference_candidates is None:
            returns = percentile_ranks(tuple(row.annualized_return for row in rows))
            calmars = percentile_ranks(
                tuple(row.annualized_return / max(abs(row.max_drawdown), 0.01) for row in rows)
            )
        else:
            reference_metrics = [
                row.candidate.segments[segment_index].metrics
                for row in reference_ranked
                if row.base_score is not None
            ]
            typed_reference = [row for row in reference_metrics if row is not None]
            if not typed_reference:
                raise ValueError("frozen reference distribution has no scoreable candidates")
            reference_returns = tuple(row.annualized_return for row in typed_reference)
            reference_calmars = tuple(
                row.annualized_return / max(abs(row.max_drawdown), 0.01)
                for row in typed_reference
            )
            returns = tuple(_percentile_against(row.annualized_return, reference_returns) for row in rows)
            calmars = tuple(
                _percentile_against(
                    row.annualized_return / max(abs(row.max_drawdown), 0.01), reference_calmars
                )
                for row in rows
            )
        for candidate_id, return_rank, calmar_rank in zip(ids, returns, calmars, strict=True):
            per_candidate_scores.setdefault(candidate_id, tuple())
            per_candidate_scores[candidate_id] += (0.6 * return_rank + 0.4 * calmar_rank,)

    base_scores: dict[str, float] = {
        candidate_id: 0.625 * min(scores) + 0.375 * (sum(scores) / 3)
        for candidate_id, scores in per_candidate_scores.items()
    }
    q_percentiles_by_segment: list[dict[str, float]] = []
    for segment_index in range(segment_count):
        ids = list(per_candidate_scores)
        if reference_candidates is None:
            percentiles = percentile_ranks(
                tuple(per_candidate_scores[candidate_id][segment_index] for candidate_id in ids)
            )
        else:
            reference_q = tuple(
                row.segment_scores[segment_index]
                for row in reference_ranked
                if row.base_score is not None
            )
            percentiles = tuple(
                _percentile_against(
                    per_candidate_scores[candidate_id][segment_index], reference_q
                )
                for candidate_id in ids
            )
        q_percentiles_by_segment.append(dict(zip(ids, percentiles, strict=True)))

    ranked = []
    for item in candidates:
        failures = failure_map[item.candidate_id]
        scores = per_candidate_scores.get(item.candidate_id, ())
        complete = len(scores) == 3
        metrics = [value for value in metrics_by_id[item.candidate_id] if value is not None]
        if complete:
            if sum(row.baseline_delta >= 0 for row in metrics) < gates.min_positive_segments:
                failures.append("relative baseline gate not met")
            if any(
                row.baseline_delta < gates.min_baseline_delta
                for row in metrics
            ):
                failures.append("relative baseline floor not met")
            ranks = [q_percentiles_by_segment[index][item.candidate_id] for index in range(3)]
            if any(value < gates.all_segment_percentile for value in ranks):
                failures.append("segment percentile gate not met")
            if sum(value >= gates.strong_segment_percentile for value in ranks) < 2:
                failures.append("strong segment percentile gate not met")
        eligible = complete and not failures
        ranked.append(
            RankedCandidate(
                candidate=item,
                segment_scores=scores,
                segment_percentiles=tuple(
                    q_percentiles_by_segment[index].get(item.candidate_id, 0.0)
                    for index in range(3)
                ) if complete else (),
                base_score=base_scores.get(item.candidate_id),
                robust_score=None,
                stability=None,
                eligible=eligible,
                failures=tuple(dict.fromkeys(failures)),
            )
        )
    return tuple(ranked)


def score_neighborhood(
    center: RankedCandidate,
    neighbors: tuple[RankedCandidate, ...],
    gates: RobustGates,
) -> RankedCandidate:
    if not neighbors:
        return RankedCandidate(
            center.candidate,
            center.segment_scores,
            center.segment_percentiles,
            center.base_score,
            None,
            None,
            False,
            tuple(dict.fromkeys((*center.failures, "neighborhood not verified"))),
        )
    if any(any(segment.metrics is None for segment in row.candidate.segments) for row in neighbors):
        return RankedCandidate(
            center.candidate,
            center.segment_scores,
            center.segment_percentiles,
            center.base_score,
            None,
            None,
            False,
            tuple(dict.fromkeys((*center.failures, "neighborhood evidence insufficient"))),
        )
    if center.base_score is None:
        return RankedCandidate(
            center.candidate,
            center.segment_scores,
            center.segment_percentiles,
            None,
            None,
            None,
            False,
            tuple(dict.fromkeys((*center.failures, "center has no development score"))),
        )
    passed = sum(
        row.eligible and row.base_score is not None and row.base_score >= center.base_score * 0.8
        for row in neighbors
    )
    stability = passed / len(neighbors)
    robust_score = (
        0.5 * min(center.segment_scores)
        + 0.3 * (sum(center.segment_scores) / 3)
        + 0.2 * stability
    )
    eligible = center.eligible and stability >= gates.min_stability
    failures = list(center.failures)
    if stability < gates.min_stability:
        failures.append("neighborhood stability gate not met")
    return RankedCandidate(
        center.candidate,
        center.segment_scores,
        center.segment_percentiles,
        center.base_score,
        robust_score,
        stability,
        eligible,
        tuple(dict.fromkeys(failures)),
    )
