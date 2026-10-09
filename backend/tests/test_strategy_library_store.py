from __future__ import annotations

import json
import threading

import pytest

from app.services import preferences
from app.strategy_library.contracts import BacktestPeriod
from app.strategy_library.store import StrategyLibraryStore
from app.user_system import settings_context


@pytest.fixture
def prefs_path(tmp_path, monkeypatch):
    path = tmp_path / "user_data" / "preferences.json"
    path.parent.mkdir(parents=True)
    monkeypatch.setattr(preferences, "_path", lambda: path)
    preferences._invalidate_cache()
    yield path
    preferences._invalidate_cache()


def test_strategy_library_preferences_are_user_scoped(prefs_path):
    prefs_path.write_text(
        json.dumps({"strategy_library_groups": [{"id": "global", "name": "global"}]}),
        encoding="utf-8",
    )
    store = StrategyLibraryStore()

    token_a = settings_context.activate({}, {})
    try:
        store.save_groups([{"id": "g-a", "name": "用户 A", "order": 0, "strategy_ids": []}])
        store.save_task({"id": "task-a", "user_id": "user-a", "state": "completed"})
        assert [group.id for group in store.get_groups()] == ["g-a"]
        assert [task["id"] for task in store.get_tasks()] == ["task-a"]
    finally:
        settings_context.reset(token_a)

    token_b = settings_context.activate({}, {})
    try:
        assert store.get_groups() == []
        assert store.get_tasks() == []
    finally:
        settings_context.reset(token_b)


def test_saving_result_preserves_unknown_preference_keys(prefs_path):
    prefs_path.write_text(json.dumps({"unrelated_user_key": {"keep": True}}), encoding="utf-8")
    store = StrategyLibraryStore()
    summary = {
        "period": "3m",
        "actual_start": "2026-07-01",
        "actual_end": "2026-10-01",
        "total_return": 0.12,
        "updated_at": "2026-10-01T12:00:00+08:00",
    }

    store.save_result("builtin_x", BacktestPeriod.THREE_MONTHS, summary)

    stored = json.loads(prefs_path.read_text(encoding="utf-8"))
    assert stored["unrelated_user_key"] == {"keep": True}
    assert stored["strategy_library_results"]["builtin_x"]["3m"]["total_return"] == 0.12


def test_failed_summary_does_not_replace_last_success(prefs_path, monkeypatch):
    store = StrategyLibraryStore()
    valid_summary = {
        "period": "3m",
        "actual_start": "2026-07-01",
        "actual_end": "2026-10-01",
        "total_return": 0.12,
    }
    store.save_result("builtin_x", BacktestPeriod.THREE_MONTHS, valid_summary)

    def fail_save(_updates):
        raise OSError("disk full")

    monkeypatch.setattr(preferences, "save", fail_save)
    with pytest.raises(OSError, match="disk full"):
        store.save_result(
            "builtin_x",
            BacktestPeriod.THREE_MONTHS,
            {"period": "3m", "total_return": 0.21},
        )

    assert json.loads(prefs_path.read_text(encoding="utf-8"))["strategy_library_results"][
        "builtin_x"
    ]["3m"]["total_return"] == 0.12


def test_task_history_is_bounded_and_keeps_running_jobs(prefs_path):
    store = StrategyLibraryStore()
    for index in range(12):
        store.save_task({
            "id": f"done-{index}",
            "state": "completed",
            "updated_at": f"2026-10-{index + 1:02d}T00:00:00+00:00",
        })
    store.save_task({"id": "active", "state": "running", "updated_at": "2026-10-20"})

    task_ids = {task["id"] for task in store.get_tasks()}
    assert "active" in task_ids
    assert len(task_ids) == 11


def test_background_store_uses_snapshot_and_persists_only_preference_updates():
    updates = []
    store = StrategyLibraryStore(
        initial_preferences={"unrelated": {"preserve": True}},
        persist_updates=lambda value: updates.append(value),
    )
    errors = []

    def save_from_worker():
        try:
            store.save_task({"id": "worker-task", "state": "running"})
        except Exception as exc:  # pragma: no cover - asserted below
            errors.append(exc)

    thread = threading.Thread(target=save_from_worker)
    thread.start()
    thread.join(5)

    assert not errors
    assert updates == [{"strategy_library_tasks": {"worker-task": {"id": "worker-task", "state": "running"}}}]
    assert store.get_tasks()[0]["id"] == "worker-task"
