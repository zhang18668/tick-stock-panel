import multiprocessing
from pathlib import Path

import pytest

from app.strategy_optimizer.lifecycle import RunLifecycle
from app.strategy_optimizer.store import OptimizationRunStore


def _claim_in_process(root, run_id, start, results):
    start.wait()
    results.put(OptimizationRunStore(Path(root)).claim_holdout(run_id, "same-window"))


def test_store_round_trip_and_path_traversal_rejection(tmp_path):
    store = OptimizationRunStore(tmp_path)
    store.create("run-1", {"state": "queued"})
    assert store.read_json("run-1", "manifest.json")["state"] == "queued"
    with pytest.raises(ValueError, match="run id"):
        store.write_json("..", "manifest.json", {})


def test_lifecycle_rejects_terminal_state_transition():
    state = RunLifecycle()
    state.transition("running")
    state.transition("succeeded")
    with pytest.raises(ValueError, match="illegal"):
        state.transition("queued")


def test_holdout_claim_is_idempotent_and_detects_reuse(tmp_path):
    store = OptimizationRunStore(tmp_path)

    assert store.claim_holdout("run1", "strategy:2024:2026") == "first"
    assert store.claim_holdout("run1", "strategy:2024:2026") == "resumed"
    assert store.claim_holdout("run2", "strategy:2024:2026") == "repeated"


def test_concurrent_processes_have_one_first_holdout_claim(tmp_path):
    context = multiprocessing.get_context("spawn")
    start = context.Event()
    results = context.Queue()
    processes = [
        context.Process(target=_claim_in_process, args=(str(tmp_path), f"run-{index}", start, results))
        for index in range(2)
    ]
    for process in processes:
        process.start()
    start.set()
    outcomes = [results.get(timeout=15) for _ in processes]
    for process in processes:
        process.join(timeout=15)

    assert all(process.exitcode == 0 for process in processes)
    assert sorted(outcomes) == ["first", "repeated"]


def test_completed_holdout_claim_restores_saved_result(tmp_path):
    store = OptimizationRunStore(tmp_path)
    key = "strategy:2024:2026"
    assert store.claim_holdout("run-1", key) == "first"
    store.complete_holdout("run-1", key, {"status": "passed", "results": []})

    assert store.claim_holdout("run-1", key) == "completed"
    assert store.get_holdout_result("run-1", key) == {"status": "passed", "results": []}
