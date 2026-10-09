import json
import threading
import time

from app.strategy_optimizer.manager import OptimizationJobManager
from app.strategy_optimizer.store import OptimizationRunStore


def wait_for_state(manager, run_id, state):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        record = manager.get(run_id)
        if record["state"] == state:
            return record
        time.sleep(0.01)
    raise AssertionError(f"run did not reach {state}: {manager.get(run_id)}")


def test_manager_persists_events_and_restores_active_run_as_interrupted(tmp_path):
    store = OptimizationRunStore(tmp_path)
    manager = OptimizationJobManager(store, lambda config, progress, cancel: {"top3": []})
    record = manager.create({"input_fingerprint": "same"})
    finished = wait_for_state(manager, record["run_id"], "succeeded")
    manager._event(record["run_id"], {"type": "round_complete", "round": 1})
    restored = OptimizationJobManager(store, lambda config, progress, cancel: {"top3": []})
    assert restored.get(record["run_id"])["state"] == "succeeded"
    assert restored.events(record["run_id"])[0]["event_id"] == 1
    assert (
        json.loads((tmp_path / record["run_id"] / "events.jsonl").read_text().splitlines()[0])[
            "type"
        ]
        == "round_complete"
    )
    assert finished["result"] == {"top3": []}


def test_manager_marks_interrupted_process_work_for_manual_resume(tmp_path):
    store = OptimizationRunStore(tmp_path)
    store.create("stale", {"run_id": "stale", "state": "running", "config": {}, "events": []})
    manager = OptimizationJobManager(
        store, lambda config, progress, cancel: {"resumed": config.get("resume_state")}
    )
    assert manager.get("stale")["state"] == "interrupted"
    resumed = manager.resume("stale")
    assert resumed["state"] == "queued"
    assert wait_for_state(manager, "stale", "succeeded")["result"] == {"resumed": None}


def test_manager_cancellation_prevents_result_publication(tmp_path):
    entered = threading.Event()

    def evaluator(config, progress, cancel):
        entered.set()
        while not cancel.is_set():
            time.sleep(0.01)
        return {"top3": [{"score": 1}]}

    manager = OptimizationJobManager(OptimizationRunStore(tmp_path), evaluator)
    run = manager.create({})
    assert entered.wait(2)
    manager.cancel(run["run_id"])
    result = wait_for_state(manager, run["run_id"], "cancelled")
    assert "result" not in result
