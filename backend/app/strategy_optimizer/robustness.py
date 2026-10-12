from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import asdict, replace

from .contracts import (
    RobustCandidate,
    RobustGates,
    SegmentMetrics,
    SegmentObservation,
)
from .neighborhood import count_legal_neighbors, generate_neighbors
from .robust_scoring import score_development, score_neighborhood
from .search import Candidate


class RobustnessRunner:
    """Run fixed candidates against development windows and freeze eligible results."""

    def __init__(self, evaluate, search_service):
        self.evaluate = evaluate
        self.search_service = search_service

    def run(self, request: dict, progress_cb, cancel_event: threading.Event) -> dict:
        plan = request["time_plan"]
        windows = tuple(plan.development)
        if len(windows) != 3 or any(window.role != "development" for window in windows):
            raise ValueError("robust search requires three development windows")
        gates = request.get("gates", RobustGates())
        if isinstance(gates, dict):
            gates = RobustGates(**gates)
        if not isinstance(gates, RobustGates):
            raise ValueError("invalid robust gates")

        cache: dict[tuple, SegmentObservation] = {}
        progress_cb({"type": "stage", "stage": "preflight"})
        baseline_candidate = request.get("baseline_candidate") or Candidate(
            dict(request.get("baseline_parameters", {})),
            tuple(request.get("baseline_buy_signals", ())),
            tuple(request.get("baseline_sell_signals", ())),
        )
        progress_cb({"type": "stage", "stage": "baselines"})
        baseline_segments = self._evaluate_windows(
            baseline_candidate, windows, cache, cancel_event, progress_cb, "baseline", curve=False
        )
        if cancel_event.is_set():
            return self._cancelled_result()
        if len(baseline_segments) != 3 or any(segment.metrics is None for segment in baseline_segments):
            failures = "; ".join(
                f"{segment.window_id}: {segment.failure or 'required metrics unavailable'}"
                for segment in baseline_segments if segment.metrics is None
            )
            raise ValueError(
                "default baseline cannot be evaluated across all development windows"
                + (f": {failures}" if failures else "")
            )

        references = {}
        for reference in request.get("reference_candidates", ()):
            reference_id, candidate = reference
            references[str(reference_id)] = self._evaluate_windows(
                candidate,
                windows,
                cache,
                cancel_event,
                progress_cb,
                f"reference:{reference_id}",
                curve=False,
            )
            if cancel_event.is_set():
                return self._cancelled_result()

        progress_cb({"type": "stage", "stage": "search"})
        main_budget = int(request.get("total_candidates", 500))
        batch_size = int(request.get("candidates_per_round", 50))
        max_rounds = int(request.get("max_rounds", 10))
        if not 1 <= main_budget <= 500 or not 1 <= batch_size <= 50 or not 1 <= max_rounds <= 10:
            raise ValueError("robust search budget is outside supported limits")
        candidates: dict[tuple, RobustCandidate] = {}
        resume_state = request.get("resume_state") or {}
        if resume_state:
            if resume_state.get("version") != 1 or resume_state.get("input_fingerprint") != request.get("input_fingerprint"):
                raise ValueError("robust checkpoint does not match the frozen task")
            for payload in resume_state.get("candidates", ()):
                restored = self._candidate_from_payload(payload)
                key = (tuple(sorted(restored.parameters.items())), restored.buy_signals, restored.sell_signals)
                candidates[key] = restored
                self.search_service.seen.add(key)
            examined = int(resume_state.get("examined", len(candidates)))
            search_round = int(resume_state.get("round", 0))
            self.search_service.round_index = search_round
            if resume_state.get("random_state"):
                self.search_service.random.setstate(_tuple_tree(resume_state["random_state"]))
            previous_ranked = self._feedback_rows(score_development(tuple(candidates.values()), gates)) if candidates else []
        else:
            examined = 0
            search_round = 0
            previous_ranked = []
        stop_reason = "budget_exhausted"
        for round_number in range(search_round + 1, max_rounds + 1):
            if cancel_event.is_set():
                return self._cancelled_result(candidates, examined)
            count = min(batch_size, main_budget - examined)
            if count <= 0:
                break
            batch = (
                self.search_service.first_round(count)
                if round_number == 1
                else self.search_service.next_round(previous_ranked, count)
            )
            batch = [candidate for candidate in batch if candidate.key not in candidates]
            if not batch:
                stop_reason = "search_space_exhausted"
                break
            for candidate in batch:
                observations = self._evaluate_windows(
                    candidate,
                    windows,
                    cache,
                    cancel_event,
                    progress_cb,
                    "candidate",
                    curve=False,
                )
                if cancel_event.is_set():
                    return self._cancelled_result(candidates, examined)
                robust_candidate = self._candidate_with_baseline(
                    candidate, observations, baseline_segments
                )
                candidates[candidate.key] = robust_candidate
            examined += len(batch)
            ranked = score_development(tuple(candidates.values()), gates)
            previous_ranked = self._feedback_rows(ranked)
            progress_cb(
                {
                    "type": "round_complete",
                    "round": round_number,
                    "rounds": max_rounds,
                    "evaluated": examined,
                    "budget": main_budget,
                    "best_training_score": max(
                        (row.base_score for row in ranked if row.base_score is not None),
                        default=None,
                    ),
                }
            )
            progress_cb(
                {
                    "type": "checkpoint",
                    "checkpoint": {
                        "version": 1,
                        "stage": "search",
                        "input_fingerprint": request.get("input_fingerprint"),
                        "examined": examined,
                        "round": round_number,
                        "random_state": self.search_service.random.getstate(),
                        "candidates": [self._candidate_payload(row) for row in candidates.values()],
                    },
                }
            )
            if examined >= main_budget:
                break
        if cancel_event.is_set():
            return self._cancelled_result(candidates, examined)
        if not candidates:
            stop_reason = "search_space_exhausted"
            ranked = ()
        else:
            ranked = score_development(tuple(candidates.values()), gates)

        progress_cb({"type": "stage", "stage": "neighborhood"})
        neighborhood_budget = min(200, int(request.get("neighbor_budget", 200)))
        center_limit = min(10, int(request.get("neighbor_centers", 10)))
        if neighborhood_budget < 0 or center_limit < 0:
            raise ValueError("neighborhood budget must be non-negative")
        centers = sorted(
            (row for row in ranked if row.base_score is not None),
            key=lambda row: (-row.base_score, row.candidate.candidate_id),
        )[:center_limit]
        scored_centers = {row.candidate.candidate_id: row for row in ranked}
        verified_center_ids: set[str] = set()
        neighbor_used = 0
        neighbor_cache_hits = 0
        neighborhood_coverage = []
        main_distribution = tuple(
            row.candidate for row in ranked if row.base_score is not None
        )
        for center in centers:
            if cancel_event.is_set():
                return self._cancelled_result(candidates, examined, neighbor_used)
            center_candidate = Candidate(
                    center.candidate.parameters,
                    center.candidate.buy_signals,
                    center.candidate.sell_signals,
                )
            parameters = tuple(self.search_service.parameters)
            constraints = tuple(self.search_service.constraints)
            base_values = dict(self.search_service.base_values)
            legal_count = count_legal_neighbors(
                center_candidate, parameters, constraints, base_values
            )
            neighbors = generate_neighbors(
                center_candidate,
                parameters,
                constraints,
                base_values,
                limit=min(20, neighborhood_budget - neighbor_used),
            )
            cached_neighbors = sum(
                all((neighbor.key, window.id, False) in cache for window in windows)
                for neighbor in neighbors
            )
            neighbor_cache_hits += cached_neighbors
            neighborhood_coverage.append(
                {
                    "center_candidate_id": center.candidate.candidate_id,
                    "legal_neighbors": legal_count,
                    "selected_neighbors": len(neighbors),
                    "cached_neighbors": cached_neighbors,
                }
            )
            neighbor_candidates = []
            for neighbor in neighbors:
                observations = self._evaluate_windows(
                    neighbor,
                    windows,
                    cache,
                    cancel_event,
                    progress_cb,
                    "neighbor",
                    curve=False,
                )
                neighbor_used += 1
                if cancel_event.is_set():
                    return self._cancelled_result(candidates, examined, neighbor_used)
                neighbor_candidates.append(
                    self._candidate_with_baseline(neighbor, observations, baseline_segments)
                )
            if neighbor_candidates:
                neighbor_ranked = score_development(
                    tuple(neighbor_candidates), gates, reference_candidates=main_distribution
                )
                scored_centers[center.candidate.candidate_id] = score_neighborhood(
                    center, neighbor_ranked, gates
                )
                verified_center_ids.add(center.candidate.candidate_id)
            else:
                scored_centers[center.candidate.candidate_id] = score_neighborhood(
                    center, (), gates
                )
            if neighbor_used >= neighborhood_budget:
                break

        progress_cb({"type": "stage", "stage": "frozen"})
        order = sorted(
            (
                row
                for row in scored_centers.values()
                if row.eligible and row.robust_score is not None
                and row.candidate.candidate_id in verified_center_ids
            ),
            key=lambda row: (
                -row.robust_score,
                max(segment.metrics.max_drawdown for segment in row.candidate.segments),
                -min(segment.metrics.baseline_delta for segment in row.candidate.segments),
                row.candidate.candidate_id,
            ),
        )
        top3 = order[:3]
        progress_cb({"type": "done", "stage": "frozen", "done": len(top3), "total": 3})
        return {
            "cancelled": False,
            "stop_reason": stop_reason,
            "baseline": self._observations_payload(baseline_segments),
            "references": {
                key: self._observations_payload(value) for key, value in references.items()
            },
            "candidates": [self._ranked_payload(row) for row in ranked],
            "candidate_details": [self._candidate_payload(row) for row in candidates.values()],
            "frozen_candidate_ids": [row.candidate.candidate_id for row in top3],
            "top3": [self._ranked_payload(row) for row in top3],
            "evaluated_candidates": examined,
            "budgets": {
                "main_limit": main_budget,
                "main_used": examined,
                "neighborhood_limit": neighborhood_budget,
                "neighborhood_used": neighbor_used,
                "neighborhood_cache_hits": neighbor_cache_hits,
                "neighborhood_centers": center_limit,
                "neighborhood_coverage": neighborhood_coverage,
            },
            "robust_result": {
                "version": 1,
                "time_plan": {
                    "development": [self._window_payload(row) for row in windows],
                    "holdout": request.get("holdout_window"),
                    "diagnostics": [],
                },
                "baseline": self._observations_payload(baseline_segments),
                "references": {
                    key: self._observations_payload(value) for key, value in references.items()
                },
                "candidates": [self._ranked_payload(row) for row in ranked],
                "top3": [self._ranked_payload(row) for row in top3],
                "frozen_candidate_ids": [row.candidate.candidate_id for row in top3],
                "verified_candidate_ids": sorted(verified_center_ids),
                "holdout": {"status": "pending" if request.get("holdout_window") else "not_applicable", "usage": request.get("holdout_usage", "unknown"), "results": []},
                "diagnostics": [],
                "budgets": {
                    "main_limit": main_budget,
                    "main_used": examined,
                    "neighborhood_limit": neighborhood_budget,
                    "neighborhood_used": neighbor_used,
                    "neighborhood_coverage": neighborhood_coverage,
                },
            },
        }

    @staticmethod
    def _window_payload(window):
        return {"id": window.id, "start": window.start.isoformat(), "end": window.end.isoformat(), "role": window.role}

    @staticmethod
    def _candidate_from_payload(payload):
        segments = []
        for item in payload.get("segments", ()):
            raw_metrics = item.get("metrics")
            metrics = SegmentMetrics(**raw_metrics) if raw_metrics else None
            segments.append(SegmentObservation(item["window_id"], metrics, item.get("failure")))
        return RobustCandidate(
            str(payload["candidate_id"]), dict(payload.get("parameters", {})),
            tuple(payload.get("buy_signals", ())), tuple(payload.get("sell_signals", ())), tuple(segments),
        )

    def _evaluate_windows(self, candidate, windows, cache, cancel_event, progress_cb, label, *, curve):
        observations = []
        for index, window in enumerate(windows, 1):
            if cancel_event.is_set():
                break
            key = (candidate.key, window.id, curve)
            observation = cache.get(key)
            if observation is None:
                try:
                    observation = self.evaluate(candidate, window, curve)
                    if observation.window_id != window.id:
                        observation = SegmentObservation(
                            window.id, None, "evaluation returned mismatched window"
                        )
                except Exception as exc:  # noqa: BLE001 - isolate candidate calculation failures
                    observation = SegmentObservation(window.id, None, str(exc))
                cache[key] = observation
            observations.append(observation)
            progress_cb(
                {
                    "type": "candidate_progress",
                    "candidate": label,
                    "window": window.id,
                    "done": index,
                    "total": len(windows),
                }
            )
        return tuple(observations)

    @staticmethod
    def _candidate_with_baseline(candidate, observations, baseline_segments):
        by_window = {row.window_id: row for row in baseline_segments}
        adjusted = []
        for observation in observations:
            baseline = by_window.get(observation.window_id)
            if observation.metrics is None or baseline is None or baseline.metrics is None:
                adjusted.append(observation)
                continue
            adjusted.append(
                SegmentObservation(
                    observation.window_id,
                    replace(
                        observation.metrics,
                        baseline_delta=(
                            observation.metrics.annualized_return
                            - baseline.metrics.annualized_return
                        ),
                    ),
                    observation.failure,
                )
            )
        key = hashlib.sha256(
            json.dumps(
                [candidate.parameters, candidate.buy_signals, candidate.sell_signals],
                sort_keys=True,
                default=str,
            ).encode()
        ).hexdigest()[:16]
        return RobustCandidate(
            key,
            dict(candidate.parameters),
            tuple(candidate.buy_signals),
            tuple(candidate.sell_signals),
            tuple(adjusted),
        )

    @staticmethod
    def _feedback_rows(ranked):
        ordered = sorted(
            ranked,
            key=lambda row: (
                not row.eligible,
                len(row.failures),
                -(row.base_score if row.base_score is not None else float("-inf")),
                row.candidate.candidate_id,
            ),
        )
        return [
            {
                "parameters": row.candidate.parameters,
                "buy_signals": row.candidate.buy_signals,
                "sell_signals": row.candidate.sell_signals,
                "score": row.base_score if row.base_score is not None else float("-inf"),
            }
            for row in ordered
        ]

    @staticmethod
    def _observations_payload(observations):
        return [
            {
                "window_id": row.window_id,
                "metrics": asdict(row.metrics) if row.metrics is not None else None,
                "failure": row.failure,
            }
            for row in observations
        ]

    @classmethod
    def _candidate_payload(cls, candidate):
        return {
            "candidate_id": candidate.candidate_id,
            "parameters": candidate.parameters,
            "buy_signals": list(candidate.buy_signals),
            "sell_signals": list(candidate.sell_signals),
            "segments": cls._observations_payload(candidate.segments),
        }

    @classmethod
    def _ranked_payload(cls, ranked):
        return {
            **cls._candidate_payload(ranked.candidate),
            "segment_scores": list(ranked.segment_scores),
            "segment_percentiles": list(ranked.segment_percentiles),
            "base_score": ranked.base_score,
            "robust_score": ranked.robust_score,
            "stability": ranked.stability,
            "eligible": ranked.eligible,
            "failures": list(ranked.failures),
        }

    @staticmethod
    def _cancelled_result(candidates=None, examined=0, neighbor_used=0):
        return {
            "cancelled": True,
            "stop_reason": "cancelled",
            "candidates": [],
            "candidate_details": [
                RobustnessRunner._candidate_payload(candidate)
                for candidate in (candidates or {}).values()
            ],
            "frozen_candidate_ids": [],
            "top3": [],
            "budgets": {"main_used": examined, "neighborhood_used": neighbor_used},
        }


def _tuple_tree(value):
    return tuple(_tuple_tree(item) for item in value) if isinstance(value, list) else value
