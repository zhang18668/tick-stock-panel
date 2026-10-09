from __future__ import annotations

import copy
import threading
from collections.abc import Callable

from app.services import preferences
from app.strategy_library.contracts import (
    BacktestPeriod,
    StrategyGroup,
    StrategyResultSummary,
)


class StrategyLibraryStore:
    """Persist manual groups and compact successful results in user preferences."""

    def __init__(
        self,
        *,
        initial_preferences: dict | None = None,
        persist_updates: Callable[[dict], None] | None = None,
    ) -> None:
        self._snapshot = copy.deepcopy(initial_preferences) if initial_preferences is not None else None
        self._persist_updates = persist_updates
        self._lock = threading.RLock()

    def _load_preferences(self) -> dict:
        if self._snapshot is None:
            return preferences.load()
        with self._lock:
            return copy.deepcopy(self._snapshot)

    def _save_preferences(self, updates: dict) -> None:
        if self._snapshot is None:
            preferences.save(updates)
            return
        with self._lock:
            next_snapshot = copy.deepcopy(self._snapshot)
        next_snapshot.update(copy.deepcopy(updates))
        if self._persist_updates is not None:
            self._persist_updates(copy.deepcopy(updates))
        with self._lock:
            self._snapshot = next_snapshot

    def get_groups(self) -> list[StrategyGroup]:
        raw_groups = self._load_preferences().get("strategy_library_groups", [])
        if not isinstance(raw_groups, list):
            return []
        groups: list[StrategyGroup] = []
        seen_ids: set[str] = set()
        for item in raw_groups:
            if not isinstance(item, dict):
                continue
            try:
                group = StrategyGroup.from_dict(item)
            except (TypeError, ValueError):
                continue
            if group.id in seen_ids:
                continue
            seen_ids.add(group.id)
            groups.append(group)
        return sorted(groups, key=lambda group: (group.order, group.id))

    def save_groups(self, groups: list[StrategyGroup | dict]) -> None:
        normalized = [
            group if isinstance(group, StrategyGroup) else StrategyGroup.from_dict(group)
            for group in groups
        ]
        group_ids = [group.id for group in normalized]
        if len(group_ids) != len(set(group_ids)):
            raise ValueError("group ids must be unique")
        strategy_ids = [strategy_id for group in normalized for strategy_id in group.strategy_ids]
        if len(strategy_ids) != len(set(strategy_ids)):
            raise ValueError("a strategy can belong to only one group")
        self._save_preferences({"strategy_library_groups": [group.to_dict() for group in normalized]})

    def get_results(self) -> dict[str, dict[BacktestPeriod, StrategyResultSummary]]:
        raw_results = self._load_preferences().get("strategy_library_results", {})
        if not isinstance(raw_results, dict):
            return {}
        results: dict[str, dict[BacktestPeriod, StrategyResultSummary]] = {}
        for strategy_id, periods in raw_results.items():
            if not isinstance(strategy_id, str) or not strategy_id or not isinstance(periods, dict):
                continue
            parsed: dict[BacktestPeriod, StrategyResultSummary] = {}
            for period_key, raw_summary in periods.items():
                try:
                    period = BacktestPeriod(period_key)
                    if not isinstance(raw_summary, dict):
                        continue
                    parsed[period] = StrategyResultSummary.from_dict(raw_summary, period)
                except (TypeError, ValueError, KeyError):
                    continue
            if parsed:
                results[strategy_id] = parsed
        return results

    def save_result(
        self,
        strategy_id: str,
        period: BacktestPeriod,
        summary: StrategyResultSummary | dict,
    ) -> None:
        if not isinstance(strategy_id, str) or not strategy_id.strip():
            raise ValueError("strategy id must be a non-empty string")
        selected_period = BacktestPeriod(period)
        normalized = (
            summary
            if isinstance(summary, StrategyResultSummary)
            else StrategyResultSummary.from_dict(summary, selected_period)
        )
        if normalized.status != "completed":
            raise ValueError("only completed summaries can replace stored results")

        all_results = self._load_preferences().get("strategy_library_results", {})
        all_results = dict(all_results) if isinstance(all_results, dict) else {}
        strategy_results = all_results.get(strategy_id)
        strategy_results = dict(strategy_results) if isinstance(strategy_results, dict) else {}
        strategy_results[selected_period.value] = normalized.to_dict()
        all_results[strategy_id.strip()] = strategy_results
        self._save_preferences({"strategy_library_results": all_results})

    def get_tasks(self) -> list[dict]:
        raw_tasks = self._load_preferences().get("strategy_library_tasks", {})
        if isinstance(raw_tasks, list):
            tasks = [item for item in raw_tasks if isinstance(item, dict)]
        elif isinstance(raw_tasks, dict):
            tasks = [
                item for item in raw_tasks.values()
                if isinstance(item, dict) and isinstance(item.get("id"), str)
            ]
        else:
            return []
        return sorted(tasks, key=lambda item: str(item.get("updated_at", "")))

    def save_task(self, task: dict) -> None:
        if not isinstance(task, dict) or not isinstance(task.get("id"), str):
            raise ValueError("task record must include an id")
        raw_tasks = self._load_preferences().get("strategy_library_tasks", {})
        tasks = dict(raw_tasks) if isinstance(raw_tasks, dict) else {}
        tasks[task["id"]] = task
        active = {
            task_id: value for task_id, value in tasks.items()
            if isinstance(value, dict) and value.get("state") in {"queued", "running"}
        }
        completed = sorted(
            (
                (task_id, value) for task_id, value in tasks.items()
                if task_id not in active and isinstance(value, dict)
            ),
            key=lambda pair: str(pair[1].get("updated_at", "")),
            reverse=True,
        )[:10]
        retained = {**active, **dict(completed)}
        self._save_preferences({"strategy_library_tasks": retained})
