from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Any


class OptimizationRunStore:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._holdout_lock = threading.Lock()

    def claim_holdout(self, run_id: str, usage_key: str) -> str:
        """Atomically record a holdout use; retries of the same run are idempotent."""
        self._dir(run_id)
        if not usage_key or not isinstance(usage_key, str):
            raise ValueError("holdout usage key must be non-empty")
        with self._holdout_lock:
            usage_path = self.root / "holdout-usage.json"
            try:
                uses = json.loads(usage_path.read_text(encoding="utf-8"))
            except FileNotFoundError:
                uses = {}
            if not isinstance(uses, dict):
                raise ValueError("holdout usage registry is invalid")
            existing = uses.get(usage_key, [])
            if not isinstance(existing, list):
                raise ValueError("holdout usage registry is invalid")
            if run_id in existing:
                return "first" if existing[0] == run_id else "repeated"
            classification = "first" if not existing else "repeated"
            uses[usage_key] = [*existing, run_id]
            self._write_registry_atomic(usage_path, uses)
            return classification

    @staticmethod
    def _write_registry_atomic(target: Path, data: dict) -> None:
        fd, temp = tempfile.mkstemp(prefix=".holdout-usage.", dir=target.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False, separators=(",", ":"))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, target)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)

    def _dir(self, run_id: str) -> Path:
        if not run_id or Path(run_id).name != run_id or run_id in {".", ".."}:
            raise ValueError("invalid run id")
        path = (self.root / run_id).resolve()
        if self.root not in path.parents:
            raise ValueError("run path escapes store")
        return path

    def create(self, run_id: str, manifest: dict[str, Any]) -> None:
        path = self._dir(run_id)
        path.mkdir()
        self.write_json(run_id, "manifest.json", manifest)

    def write_json(self, run_id: str, name: str, data: Any) -> None:
        path = self._dir(run_id)
        path.mkdir(parents=True, exist_ok=True)
        target = (path / name).resolve()
        if target.parent != path:
            raise ValueError("invalid run file")
        fd, temp = tempfile.mkstemp(prefix=f".{name}.", dir=path)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False, separators=(",", ":"))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, target)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)

    def read_json(self, run_id: str, name: str) -> Any:
        with (self._dir(run_id) / name).open(encoding="utf-8") as handle:
            return json.load(handle)

    def append_jsonl(self, run_id: str, name: str, data: Any) -> None:
        path = self._dir(run_id)
        path.mkdir(parents=True, exist_ok=True)
        target = (path / name).resolve()
        if target.parent != path:
            raise ValueError("invalid run file")
        with target.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        lines = target.read_text(encoding="utf-8").splitlines()
        if len(lines) > 1000:
            temp_data = "\n".join(lines[-1000:]) + "\n"
            self.write_text_atomic(run_id, name, temp_data)

    def write_text_atomic(self, run_id: str, name: str, data: str) -> None:
        path = self._dir(run_id)
        path.mkdir(parents=True, exist_ok=True)
        target = (path / name).resolve()
        if target.parent != path:
            raise ValueError("invalid run file")
        fd, temp = tempfile.mkstemp(prefix=f".{name}.", dir=path)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, target)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)

    def read_jsonl(self, run_id: str, name: str) -> list[Any]:
        target = self._dir(run_id) / name
        if not target.exists():
            return []
        with target.open(encoding="utf-8") as handle:
            rows = []
            for line in handle:
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
            return rows
