import pytest

from app.strategy_optimizer.lifecycle import RunLifecycle
from app.strategy_optimizer.store import OptimizationRunStore


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
