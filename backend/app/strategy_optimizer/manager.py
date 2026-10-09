from __future__ import annotations

import copy
import threading
import time
import uuid
from datetime import UTC, datetime

from app.services.heavy_job_limiter import HeavyJobCancelledError, shared_heavy_job_limiter

from .lifecycle import STATES, RunLifecycle
from .store import OptimizationRunStore


class OptimizationJobManager:
    def __init__(
        self, store: OptimizationRunStore, evaluator=None, *, shutdown_timeout: float = 5.0
    ):
        self.store = store
        self.evaluator = evaluator
        self.shutdown_timeout = shutdown_timeout
        self._runs = {}
        self._cancel_events = {}
        self._threads = {}
        self._lock = threading.RLock()
        self._load_existing()

    def _load_existing(self):
        for path in self.store.root.iterdir():
            if not path.is_dir():
                continue
            try:
                record = self.store.read_json(path.name, "manifest.json")
            except (OSError, ValueError):
                continue
            if (
                not isinstance(record, dict)
                or record.get("run_id") != path.name
                or record.get("state") not in STATES
                or not isinstance(record.get("config"), dict)
            ):
                continue
            if record.get("state") in {"queued", "running", "cancelling"}:
                record["state"] = RunLifecycle(record["state"]).transition("interrupted")
                self.store.write_json(path.name, "manifest.json", record)
            self._runs[path.name] = record
            self._cancel_events[path.name] = threading.Event()
            try:
                persisted_events = self.store.read_jsonl(path.name, "events.jsonl")
            except OSError:
                persisted_events = []
            persisted_events = [
                event
                for event in persisted_events
                if isinstance(event, dict) and isinstance(event.get("event_id"), int)
            ]
            if persisted_events:
                record["events"] = persisted_events[-200:]
                record["last_event_id"] = max(
                    event.get("event_id", 0) for event in persisted_events
                )

    def shutdown(self):
        with self._lock:
            for run_id, event in self._cancel_events.items():
                state = self._runs[run_id]["state"]
                if state == "queued":
                    event.set()
                    self._runs[run_id]["cancel"] = True
                    self._runs[run_id]["state"] = RunLifecycle(state).transition("cancelled")
                    self._persist(self._runs[run_id])
                elif state in {"running", "cancelling"}:
                    event.set()
                    self._runs[run_id]["cancel"] = True
                    self._runs[run_id]["state"] = RunLifecycle(state).transition("cancelling")
                    self._persist(self._runs[run_id])
            threads = tuple(self._threads.values())
        deadline = time.monotonic() + self.shutdown_timeout
        for thread in threads:
            thread.join(max(0.0, deadline - time.monotonic()))

    def create(self, config: dict) -> dict:
        run_id = uuid.uuid4().hex
        record = {
            "run_id": run_id,
            "state": "queued",
            "config": config,
            "created_at": datetime.now(UTC).isoformat(),
            "events": [],
        }
        with self._lock:
            active = sum(
                item["state"] in {"queued", "running", "cancelling"} for item in self._runs.values()
            )
            if active >= 20:
                raise RuntimeError("optimization queue is full")
            self.store.create(run_id, record)
            self._runs[run_id] = record
            self._cancel_events[run_id] = threading.Event()
            thread = threading.Thread(target=self._run, args=(run_id,), daemon=True)
            self._threads[run_id] = thread
        thread.start()
        return self.get(run_id)

    def get(self, run_id: str) -> dict:
        with self._lock:
            if run_id not in self._runs:
                raise KeyError(run_id)
            return copy.deepcopy(self._runs[run_id])

    def list(self) -> list[dict]:
        with self._lock:
            return copy.deepcopy(list(self._runs.values()))

    def events(self, run_id: str, after: int = 0) -> list[dict]:
        with self._lock:
            return copy.deepcopy(
                [
                    event
                    for event in self._runs[run_id].get("events", [])
                    if event.get("event_id", 0) > after
                ]
            )

    def resume(self, run_id: str) -> dict:
        with self._lock:
            record = self._runs[run_id]
            if record["state"] not in {"failed", "interrupted"}:
                raise ValueError("run is not resumable")
            record["state"] = RunLifecycle(record["state"]).transition("queued")
            record.pop("error", None)
            record.pop("result", None)
            record["cancel"] = False
            checkpoints = [
                event.get("checkpoint")
                for event in record.get("events", [])
                if event.get("checkpoint")
            ]
            try:
                checkpoint = self.store.read_json(run_id, "checkpoint.json")
            except (OSError, ValueError):
                checkpoint = checkpoints[-1] if checkpoints else None
            if checkpoint:
                record["config"]["resume_state"] = checkpoint
            self._cancel_events[run_id] = threading.Event()
            self._persist(record)
            thread = threading.Thread(target=self._run, args=(run_id,), daemon=True)
            self._threads[run_id] = thread
            thread.start()
            return copy.deepcopy(record)

    def candidate(self, run_id: str, candidate_id: str):
        with self._lock:
            record = self._runs[run_id]
            candidates = (record.get("result") or {}).get("candidates", [])
            for index, item in enumerate(candidates):
                if str(item.get("candidate_id", index)) == candidate_id:
                    return copy.deepcopy(item)
            raise KeyError(candidate_id)

    def cancel(self, run_id: str) -> dict:
        with self._lock:
            record = self._runs[run_id]
            record["cancel"] = True
            self._cancel_events[run_id].set()
            if record["state"] == "queued":
                record["state"] = RunLifecycle("queued").transition("cancelled")
            elif record["state"] == "running":
                record["state"] = RunLifecycle("running").transition("cancelling")
            self._persist(record)
            return copy.deepcopy(record)

    def _run(self, run_id: str) -> None:
        with self._lock:
            record = self._runs[run_id]
            if record.get("cancel"):
                return
            record["state"] = RunLifecycle(record["state"]).transition("running")
            self._persist(record)
        try:
            if self.evaluator is None:
                raise RuntimeError("strategy optimization gateway is unavailable")
            with shared_heavy_job_limiter.slot("normal", cancel_event=self._cancel_events[run_id]):
                result = self.evaluator(
                    record["config"],
                    lambda event: self._event(run_id, event),
                    self._cancel_events[run_id],
                )
            with self._lock:
                if not record.get("cancel"):
                    record["result"] = result
                    self.store.write_json(run_id, "top3.json", result.get("top3", []))
                    self.store.write_json(run_id, "candidates.json", result.get("candidates", []))
                    record["state"] = RunLifecycle(record["state"]).transition("succeeded")
                    self._persist(record)
                else:
                    record["state"] = RunLifecycle(record["state"]).transition("cancelled")
                    self._persist(record)
        except Exception as exc:
            with self._lock:
                target = (
                    "cancelled"
                    if record.get("cancel") or isinstance(exc, HeavyJobCancelledError)
                    else "failed"
                )
                current = record["state"]
                if target == "cancelled" and current == "running":
                    current = RunLifecycle(current).transition("cancelling")
                record["state"] = RunLifecycle(current).transition(target)
                record["error"] = str(exc)
                self._persist(record)

    def _event(self, run_id, event):
        with self._lock:
            record = self._runs[run_id]
            raw_event = event
            if event.get("type") == "checkpoint" and event.get("checkpoint"):
                self.store.write_json(run_id, "checkpoint.json", event["checkpoint"])
                event = {"type": "checkpoint", "round": event["checkpoint"].get("round")}
            if raw_event.get("type") == "round_complete":
                self.store.append_jsonl(run_id, "rounds.jsonl", raw_event)
            event = {**event, "event_id": record.get("last_event_id", 0) + 1}
            record["last_event_id"] = event["event_id"]
            self.store.append_jsonl(run_id, "events.jsonl", event)
            record.setdefault("events", []).append(event)
            record["events"] = record["events"][-200:]
            self._persist(record)

    def _persist(self, record):
        self.store.write_json(record["run_id"], "manifest.json", record)
