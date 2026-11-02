"""Immutable, owner-scoped archive; market data never becomes an execution signal."""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import re
import tempfile
from collections import defaultdict
from functools import lru_cache
from pathlib import Path

import polars as pl

from app.market_time import cn_now
from app.services.fs_utils import atomic_write_parquet, atomic_write_text


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()).hexdigest()


@lru_cache(maxsize=128)
def _manifest(path: str, mtime_ns: int) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


class ChanReviewArchive:
    def __init__(self, data_dir: Path):
        self.root = (Path(data_dir) / "research" / "chan_review" / "archives").resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _owner(self, owner: str) -> Path:
        if not owner or not isinstance(owner, str):
            raise ValueError("缺少归档用户")
        path = (self.root / digest(owner)).resolve()
        if self.root not in path.parents:
            raise ValueError("归档目录越界")
        path.mkdir(exist_ok=True)
        return path

    def _run(self, owner: str, run_id: str) -> Path:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", run_id):
            raise ValueError("非法任务ID")
        root = self._owner(owner)
        path = (root / "observations" / run_id).resolve()
        if root not in path.parents:
            raise ValueError("归档路径越界")
        return path

    def _blob_path(self, owner: str, blob_id: str) -> Path:
        if not re.fullmatch(r"[a-f0-9]{64}", blob_id):
            raise ValueError("非法快照ID")
        root = self._owner(owner)
        path = (root / "blobs" / (blob_id + ".json.gz")).resolve()
        if root not in path.parents:
            raise ValueError("快照路径越界")
        return path

    def _put(self, owner: str, value) -> str:
        blob_id = digest(value)
        path = self._blob_path(owner, blob_id)
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(prefix=".blob-", dir=path.parent)
            try:
                with os.fdopen(fd, "wb") as stream:
                    stream.write(gzip.compress(json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode(), mtime=0))
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(tmp, path)
            finally:
                if os.path.exists(tmp):
                    os.unlink(tmp)
        return blob_id

    def _get(self, owner: str, blob_id: str):
        path = self._blob_path(owner, blob_id)
        try:
            result = json.loads(gzip.decompress(path.read_bytes()))
        except FileNotFoundError as exc:
            raise KeyError(blob_id) from exc
        if digest(result) != blob_id:
            raise ValueError("快照完整性校验失败")
        return result

    def save_input(self, owner: str, rows: list[dict]) -> str:
        return self._put(owner, {"kind": "input", "rows": rows})

    def read_input(self, owner: str, input_hash: str) -> list[dict]:
        return self._get(owner, input_hash)["rows"]

    def save_observation(self, owner: str, run_id: str, symbol: str,
                         name: str, source: str, frame: dict,
                         input_hash: str, left_censored: bool) -> dict:
        run = self._run(owner, run_id)
        self._blob_path(owner, input_hash)
        if source not in {"observed", "backfill"}:
            raise ValueError("非法归档来源")
        observed = frame.get("observed_as_of") or frame["asOf"]
        if not observed or any(row["date"] > observed for row in frame["rows"]):
            raise ValueError("当时快照不能包含未来K线")
        # Content-addressed row chunks preserve the exact historical indicators
        # and price basis while sharing unchanged history across daily frames.
        chunks = [self._put(owner, frame["rows"][i:i + 64]) for i in range(0, len(frame["rows"]), 64)]
        snapshot_id = self._put(owner, {"kind": "snapshot", "symbol": symbol, "period": frame.get("period", "day"),
            "observed_as_of": observed, "input_hash": input_hash, "row_chunks": chunks,
            "analysis": {k: v for k, v in frame.items() if k != "rows"}})
        identity = digest([run_id, symbol, source, frame.get("period", "day"), observed])
        target = run / (identity + ".parquet")
        if target.exists():
            old = pl.read_parquet(target)
            if old["snapshot_id"][0] != snapshot_id:
                raise ValueError("同一次观测已存在不同快照，不能覆盖")
            return {"snapshot_id": snapshot_id, "count": old.filter(pl.col("point_type") != "").height}
        if (run / "committed.json").exists():
            raise ValueError("已发布任务不可修改")
        base = {"run_id": run_id, "symbol": symbol, "name": name, "source": source,
                "period": frame.get("period", "day"), "observed_as_of": observed,
                "engine_revision": frame["engine"]["revision"], "config_hash": digest(frame["engine"]["config"]),
                "snapshot_id": snapshot_id, "input_hash": input_hash, "left_censored": left_censored,
                "created_at": cn_now().isoformat()}
        signals = [s for s in frame["structures"] if s["kind"] == "signal" and s["label"].startswith("B")]
        records = [{**base, "id": digest([identity, s["label"], s["end"]]), "point_type": s["label"][1:],
                    "point_date": s["end"]["date"], "point_price": float(s["end"]["price"]), "structure_id": s["id"]}
                   for s in signals]
        if not records:
            records = [{**base, "id": "", "point_type": "", "point_date": "", "point_price": 0.0, "structure_id": ""}]
        run.mkdir(parents=True, exist_ok=True)
        atomic_write_parquet(pl.DataFrame(records), target)
        return {"snapshot_id": snapshot_id, "count": len(signals)}

    def publish_run(self, owner: str, run_id: str, coverage: dict) -> None:
        run = self._run(owner, run_id)
        run.mkdir(parents=True, exist_ok=True)
        marker = run / "committed.json"
        if marker.exists():
            return
        partitions = defaultdict(list)
        for path in run.glob("*.parquet"):
            symbol = pl.read_parquet(path, columns=["symbol"])["symbol"][0]
            partitions[symbol].append(path.name)
        atomic_write_text(marker, json.dumps({**coverage, "partitions": dict(partitions)}, ensure_ascii=False, allow_nan=False))
        # Build small signal-episode partitions once at publication. HTTP reads
        # scan this index, never replay millions of repeated daily observations.
        root = self._owner(owner) / "index"
        root.mkdir(exist_ok=True)
        catalog = root / "catalog.json"
        entries = json.loads(catalog.read_text(encoding="utf-8")) if catalog.exists() else {}
        for symbol in partitions:
            events = self._episodes(owner, {"symbol": symbol})
            if events:
                key = digest(events) + ".parquet"
                if not (root / key).exists():
                    atomic_write_parquet(pl.DataFrame(events), root / key)
                entries[symbol] = key
            else:
                entries.pop(symbol, None)
        # Switching the catalog is atomic: readers see the old or new index.
        atomic_write_text(catalog, json.dumps(entries, ensure_ascii=False))

    def compact_symbol(self, owner: str, run_id: str, symbol: str) -> None:
        """One partition per completed stock, rather than one file per day."""
        run = self._run(owner, run_id)
        if (run / "committed.json").exists():
            raise ValueError("已发布任务不可修改")
        partition = run / (digest([run_id, symbol, "partition"]) + ".partition.parquet")
        paths = [p for p in run.glob("*.parquet") if not p.name.endswith(".partition.parquet")
                 and pl.read_parquet(p, columns=["symbol"])["symbol"][0] == symbol]
        if partition.exists():
            paths.append(partition)
        if len(paths) <= 1:
            return
        target = partition
        atomic_write_parquet(pl.concat([pl.read_parquet(p) for p in paths]), target)
        for path in paths:
            if path != target:
                path.unlink()

    def discard_symbol(self, owner: str, run_id: str, symbol: str) -> None:
        run = self._run(owner, run_id)
        if (run / "committed.json").exists():
            raise ValueError("已发布任务不可修改")
        partition = run / (digest([run_id, symbol, "partition"]) + ".partition.parquet")
        partition.unlink(missing_ok=True)
        for path in run.glob("*.parquet"):
            if path.name.endswith(".partition.parquet"):
                continue
            if pl.read_parquet(path, columns=["symbol"])["symbol"][0] == symbol:
                path.unlink()

    def reuse_observations(self, owner: str, prior: str, run_id: str, symbol: str) -> None:
        source, target = self._run(owner, prior), self._run(owner, run_id)
        if (target / "committed.json").exists():
            raise ValueError("已发布任务不可修改")
        target.mkdir(parents=True, exist_ok=True)
        for path in source.glob("*.parquet"):
            if path.name.endswith(".partition.parquet") and path.name != digest([prior, symbol, "partition"]) + ".partition.parquet":
                continue
            data = pl.read_parquet(path)
            if data["symbol"][0] == symbol:
                atomic_write_parquet(data.with_columns(pl.lit(run_id).alias("run_id")), target / (digest([run_id, symbol, "partition"]) + ".partition.parquet") if path.name.endswith(".partition.parquet") else target / path.name)

    def _observation_query(self, owner: str, filters: dict | None = None):
        root = self._owner(owner)
        markers = list((root / "observations").glob("*/committed.json"))
        coverage, paths = {}, []
        for marker in markers:
            item = _manifest(str(marker), marker.stat().st_mtime_ns)
            coverage[marker.parent.name] = item
            selected = [(filters["symbol"], item["partitions"].get(filters["symbol"], []))] if filters and filters.get("symbol") else item["partitions"].items()
            for _symbol, names in selected:
                for name in names:
                    if not re.fullmatch(r"[a-f0-9]{64}(?:\.partition)?\.parquet", name):
                        raise ValueError("非法归档分区")
                    paths.append(str(marker.parent / name))
        if not paths:
            return None, coverage
        query = pl.scan_parquet(paths)
        for key in ("source", "period", "symbol", "engine_revision", "config_hash", "point_type", "point_date"):
            if filters and filters.get(key):
                query = query.filter(pl.col(key) == filters[key])
        if filters and filters.get("observed_start"):
            query = query.filter(pl.col("observed_as_of") >= filters["observed_start"])
        if filters and filters.get("observed_end"):
            query = query.filter(pl.col("observed_as_of") <= filters["observed_end"])
        return query, coverage

    def _read_rows(self, owner: str, filters: dict | None = None) -> list[dict]:
        query, coverage = self._observation_query(owner, filters)
        if query is None:
            return []
        rows = query.collect().to_dicts()
        for row in rows:
            row["partial"] = bool(coverage[row["run_id"]].get("partial", False))
        return rows

    def _episodes(self, owner: str, filters: dict | None = None) -> list[dict]:
        rows = self._read_rows(owner, filters)
        groups = defaultdict(list)
        for row in rows:
            groups[(row["symbol"], row["source"], row["period"], row["engine_revision"], row["config_hash"])].append(row)
        result = []
        for records in groups.values():
            days = defaultdict(list)
            for row in sorted(records, key=lambda r: (r["created_at"], r["id"])):
                days[row["observed_as_of"]].append(row)
            active = {}
            for day in sorted(days):
                observations = {}
                for row in days[day]:
                    observations.setdefault((row["run_id"], row["snapshot_id"]), []).append(row)
                # Revisions are ordered observations, not a union: a corrected
                # negative observation must close the old signal, not erase it.
                for version in observations.values():
                    current = {(r["point_type"], r["point_date"]): r for r in version if r["point_type"]}
                    for key in list(active):
                        if key not in current:
                            active.pop(key)["status"] = "not_seen"
                    for key, row in current.items():
                        if key in active:
                            active[key]["last_seen"] = day
                        else:
                            event = {**row, "first_seen": day, "last_seen": day, "category": row["point_type"][0],
                                     "status": "observed", "signal_status": "形态信号"}
                            result.append(event)
                            active[key] = event
        return result

    def _index_query(self, owner: str):
        root = self._owner(owner) / "index"
        catalog = root / "catalog.json"
        if not catalog.exists():
            return None
        entries = json.loads(catalog.read_text(encoding="utf-8"))
        paths = []
        for name in entries.values():
            if not re.fullmatch(r"[a-f0-9]{64}\.parquet", name):
                raise ValueError("非法信号索引")
            paths.append(str(root / name))
        return pl.scan_parquet(paths) if paths else None

    def list_signals(self, owner: str, filters: dict, page: int = 1, page_size: int = 30) -> dict:
        if page < 1 or not 1 <= page_size <= 100:
            raise ValueError("非法分页参数")
        query = self._index_query(owner)
        counts = {c: 0 for c in ("1", "2", "3")}
        if query is None:
            return {"items": [], "total": 0, "counts": counts, "page": page, "page_size": page_size}
        for key in ("source", "period", "symbol", "engine_revision", "point_type"):
            if filters.get(key):
                query = query.filter(pl.col(key) == filters[key])
        field = "point_date" if filters.get("date_field") == "point_date" else "first_seen"
        if filters.get("start"):
            query = query.filter(pl.col(field) >= filters["start"])
        if filters.get("end"):
            query = query.filter(pl.col(field) <= filters["end"])
        if filters.get("q"):
            query = query.filter((pl.col("symbol") + pl.col("name")).str.to_lowercase().str.contains(str(filters["q"]).lower(), literal=True))
        counts.update({r["category"]: r["len"] for r in query.group_by("category").len().collect().to_dicts()})
        if filters.get("category"):
            query = query.filter(pl.col("category") == filters["category"])
        total = query.select(pl.len()).collect().item()
        items = query.sort(["first_seen", "symbol", "point_type", "id"], descending=True).slice((page - 1) * page_size, page_size).collect().to_dicts()
        return {"items": items, "total": total, "counts": counts,
                "page": page, "page_size": page_size}

    def get_signal(self, owner: str, signal_id: str) -> dict:
        if not re.fullmatch(r"[a-f0-9]{64}", signal_id):
            raise ValueError("非法信号ID")
        query = self._index_query(owner)
        if query is not None:
            found = query.filter(pl.col("id") == signal_id).limit(1).collect().to_dicts()
            if found:
                item = found[0]
                rows = self._read_rows(owner, {**{k: item[k] for k in ("symbol", "source", "period", "engine_revision", "config_hash", "point_type", "point_date")},
                                               "observed_start": item["first_seen"], "observed_end": item["last_seen"]})
                versions = {r["snapshot_id"]: {k: r[k] for k in ("observed_as_of", "snapshot_id", "created_at", "run_id")}
                            for r in rows if r["point_type"] == item["point_type"] and r["point_date"] == item["point_date"]
                            and r["config_hash"] == item["config_hash"] and item["first_seen"] <= r["observed_as_of"] <= item["last_seen"]}
                return {**item, "observations": sorted(versions.values(), key=lambda v: (v["observed_as_of"], v["created_at"]))}
        raise KeyError(signal_id)

    def get_snapshot(self, owner: str, snapshot_id: str) -> dict:
        self._blob_path(owner, snapshot_id)
        payload = self._get(owner, snapshot_id)
        if not isinstance(payload, dict) or payload.get("kind") != "snapshot":
            raise KeyError(snapshot_id)
        query, _ = self._observation_query(owner, {"symbol": payload["symbol"]})
        if query is None or query.filter(pl.col("snapshot_id") == snapshot_id).select("snapshot_id").limit(1).collect().is_empty():
            raise KeyError(snapshot_id)
        rows = [row for chunk in payload["row_chunks"] for row in self._get(owner, chunk)]
        return {**payload["analysis"], "rows": rows, "snapshot_id": snapshot_id,
                "symbol": payload["symbol"], "period": payload["period"], "observed_as_of": payload["observed_as_of"]}
