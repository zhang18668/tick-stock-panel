from __future__ import annotations

STATES = {"queued", "running", "succeeded", "failed", "cancelling", "cancelled", "interrupted"}
TRANSITIONS = {
    "queued": {"running", "cancelled", "interrupted"},
    "running": {"succeeded", "failed", "cancelling", "interrupted"},
    "cancelling": {"cancelled", "interrupted"},
    "interrupted": {"queued"},
    "failed": {"queued"},
    "succeeded": set(),
    "cancelled": set(),
}


class RunLifecycle:
    def __init__(self, state="queued"):
        if state not in STATES:
            raise ValueError("unknown run state")
        self.state = state

    def transition(self, target: str) -> str:
        if target not in TRANSITIONS[self.state]:
            raise ValueError(f"illegal run transition: {self.state} -> {target}")
        self.state = target
        return target
