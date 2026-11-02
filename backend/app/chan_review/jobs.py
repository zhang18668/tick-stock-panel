"""Bounded repository scans; only the coordinator may publish archive files."""
from __future__ import annotations

import logging
import multiprocessing as mp
import os
import threading
import time
from contextlib import suppress
from datetime import timedelta
from pathlib import Path
from queue import Empty, Full

import polars as pl

from app.chan_review.contracts import ReviewRunRequest
from app.chan_review.store import ChanReviewArchive, digest
from app.enriched_generation import get_enriched_generation
from app.services.chan_analysis import ENGINE_CONFIG, REVISION, ChanBar, iter_chan_frames
from app.services.heavy_job_limiter import shared_heavy_job_limiter
from app.services.mining_jobs import ACTIVE_RUN_STATUSES, MiningRunStore
from app.services.mining_process_lock import MiningProcessLock, MiningProcessLockError

logger = logging.getLogger(__name__)


def _calculate(data_dir, owner, input_hash, period, dates, cancel, output):
    try:
        rows = ChanReviewArchive(Path(data_dir)).read_input(owner, input_hash)
        for day, frame in iter_chan_frames(rows, period, observed_dates=set(dates), cancel_event=cancel):
            frame["period"] = period
            frame["observed_as_of"] = day
            while not cancel.is_set():
                try:
                    output.put(("frame", frame), timeout=.2)
                    break
                except Full:
                    continue
            if cancel.is_set():
                break
        output.put(("done", None), timeout=2)
    except Exception:
        logger.exception("chan review worker failed")
        with suppress(Full, OSError):
            output.put(("error", "chan.py无法可靠计算此标的"), timeout=2)


def _calculate_loop(data_dir, owner, period, cancel, tasks, output):
    while not cancel.is_set():
        try:
            task = tasks.get(timeout=.2)
        except Empty:
            continue
        if task is None:
            return
        input_hash, dates = task
        _calculate(data_dir, owner, input_hash, period, dates, cancel, output)


class ChanReviewJobs:
    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.store = MiningRunStore(self.data_dir, namespace="chan_review")
        self.archive = ChanReviewArchive(self.data_dir)
        self.lock_dir = self.data_dir / "research" / "chan_review"
        self._guard = threading.RLock()
        self._active = {}
        self._closed = False
        lock = MiningProcessLock(self.lock_dir)
        try:
            lock.acquire(role="chan-review-recovery")
        except MiningProcessLockError:
            pass
        else:
            # A second app instance can open while the first is still queued
            # for the shared limiter, before it owns the writer lock.
            import psutil
            for path in self.store.runs_root.glob("*/manifest.json"):
                item = self.store.get(path.parent.name)
                if item and item["status"] in ACTIVE_RUN_STATUSES:
                    pid = item["request"].get("coordinator_pid")
                    started = item["request"].get("coordinator_started")
                    try:
                        alive = pid and psutil.Process(pid).create_time() == started
                    except psutil.Error:
                        alive = False
                    if not alive:
                        self.store.transition_status(item["run_id"], "interrupted", error="服务中断，可续跑已完成的标的")
            lock.release()

    def get(self, owner, run_id):
        item = self.store.get(run_id)
        if not item or item["request"].get("owner_scope") != owner:
            raise KeyError(run_id)
        return {**item, "summary": self.store.read_summary(run_id)}

    def list(self, owner):
        # Store limits apply after owner filtering, never before it.
        items = []
        for path in self.store.runs_root.glob("*/manifest.json"):
            item = self.store.get(path.parent.name)
            if item and item["request"].get("owner_scope") == owner:
                items.append(self.get(owner, item["run_id"]))
        return sorted(items, key=lambda i: i["created_at"], reverse=True)[:100]

    def create(self, owner, body: ReviewRunRequest, repo):
        instruments = repo.get_instruments()
        if instruments.is_empty() or not {"symbol", "name"} <= set(instruments.columns):
            raise ValueError("本地尚无股票名录，请先同步基础数据")
        if "asset_type" in instruments.columns:
            instruments = instruments.filter(pl.col("asset_type") == "stock")
        names = dict(instruments.select("symbol", "name").iter_rows())
        symbols = sorted(set(body.symbols if body.scope != "market" else names))
        if not symbols or any(s not in names for s in symbols):
            raise ValueError("请选择有效的股票范围；未知代码或非股票不能扫描")
        generation = get_enriched_generation(self.data_dir, "stock")
        fingerprint = {"generation": generation, "engine_revision": REVISION, "config": digest(ENGINE_CONFIG)}
        import psutil
        request = {**body.model_dump(mode="json"), "symbols": symbols, "owner_scope": owner,
                   "coordinator_pid": os.getpid(), "coordinator_started": psutil.Process().create_time()}
        if body.resume_from:
            prior = self.get(owner, body.resume_from)
            def comparable(r):
                return {k: v for k, v in r.items() if k not in {"resume_from", "coordinator_pid", "coordinator_started"}}
            if prior["status"] in ACTIVE_RUN_STATUSES or prior["data_fingerprint"] != fingerprint or comparable(prior["request"]) != comparable(request):
                raise ValueError("仅可在数据、规则和范围未改变时续跑已结束任务")
        with self._guard:
            if self._closed or any(self.get(owner, rid)["status"] in ACTIVE_RUN_STATUSES for rid, (_, _, who) in self._active.items() if who == owner):
                raise ValueError("已有任务进行中或服务正在关闭")
            if len(self._active) >= 8:
                raise ValueError("任务队列已满，请稍后重试")
            run = self.store.create(request, fingerprint)
            cancel = mp.get_context("spawn").Event()
            thread = threading.Thread(target=self._run, args=(owner, run, body, repo, names, cancel), daemon=True)
            self._active[run["run_id"]] = (thread, cancel, owner)
            thread.start()
        return self.get(owner, run["run_id"])

    def cancel(self, owner, run_id):
        with self._guard:
            item = self.get(owner, run_id)
            if item["status"] in ACTIVE_RUN_STATUSES:
                if run_id not in self._active:
                    raise ValueError("任务由另一服务进程处理，请稍后重试")
                self._active[run_id][1].set()
                if item["status"] != "cancelling":
                    self.store.transition_status(run_id, "cancelling")
        return self.get(owner, run_id)

    def _unchanged(self, run):
        if get_enriched_generation(self.data_dir, "stock") != run["data_fingerprint"]["generation"]:
            raise ValueError("扫描期间行情数据版本发生变化，未发布混合结果；请重新扫描")

    def _new_worker(self, owner, period, cancel):
        context = mp.get_context("spawn")
        tasks, output = context.Queue(maxsize=1), context.Queue(maxsize=2)
        process = context.Process(target=_calculate_loop, args=(str(self.data_dir), owner, period, cancel, tasks, output), daemon=True)
        process.start()
        return process, tasks, output

    @staticmethod
    def _stop_worker(worker):
        if worker is None:
            return
        process, tasks, output = worker
        with suppress(Full, OSError):
            tasks.put(None, timeout=.2)
        process.join(timeout=2)
        if process.is_alive():
            process.terminate()
            process.join(timeout=3)
        for queue in (tasks, output):
            queue.close()
            queue.cancel_join_thread()

    def _frames(self, owner, input_hash, period, dates, cancel, worker):
        process, tasks, output = worker
        tasks.put((input_hash, dates), timeout=2)
        deadline = time.monotonic() + 300
        while not cancel.is_set():
            if time.monotonic() > deadline:
                process.terminate()
                process.join(timeout=3)
                raise ValueError("单只股票计算超时，已停止计算进程")
            try:
                kind, payload = output.get(timeout=.2)
            except Empty:
                if not process.is_alive():
                    raise ValueError("计算进程意外退出") from None
                continue
            if kind == "done":
                return
            if kind == "error":
                raise ValueError(payload)
            yield payload

    def _run(self, owner, run, body, repo, names, cancel):
        rid = run["run_id"]
        summary = {"planned": len(run["request"]["symbols"]), "completed": 0, "failed": 0, "missing": 0,
                   "processed": 0, "completed_symbols": [], "errors": [], "partial": False,
                   "scope_note": "当前股票名录；不保证覆盖历史退市股或历史成分，无完整历史时不能视为无幸存者偏差"}
        lock = MiningProcessLock(self.lock_dir)
        worker = None
        try:
            with shared_heavy_job_limiter.slot("exclusive", cancel_event=cancel):
                while not cancel.is_set():
                    try:
                        lock.acquire(role="chan-review-writer")
                        break
                    except MiningProcessLockError:
                        cancel.wait(.2)
                if cancel.is_set():
                    self.store.transition_status(rid, "cancelled")
                    return
                with self._guard:
                    if cancel.is_set():
                        self.store.transition_status(rid, "cancelled")
                        return
                    self.store.transition_status(rid, "running")
                prior_completed = []
                if body.resume_from:
                    prior_completed = self.store.read_summary(body.resume_from).get("completed_symbols", [])
                symbols = run["request"]["symbols"]
                all_dates = set()
                for offset in range(0, len(symbols), 100):
                    if cancel.is_set():
                        break
                    self._unchanged(run)
                    chunk = symbols[offset:offset + 100]
                    data = repo.get_daily_batch(chunk, body.start - timedelta(days=1095), body.end,
                                                columns=["symbol", "date", "open", "high", "low", "close", "volume"])
                    self._unchanged(run)
                    for symbol in chunk:
                        if cancel.is_set():
                            break
                        try:
                            if symbol in prior_completed:
                                self.archive.reuse_observations(owner, body.resume_from, rid, symbol)
                            else:
                                raw = data.filter(pl.col("symbol") == symbol).sort("date").to_dicts() if not data.is_empty() else []
                                rows = [{k: (str(row[k])[:10] if k == "date" else row[k]) for k in ("date", "open", "high", "low", "close", "volume")} for row in raw if str(row["date"])[:10] <= body.end.isoformat()]
                                rows = rows[-2000:]
                                rows = [ChanBar.model_validate(r).model_dump(mode="json") for r in rows]
                                dates = [r["date"] for r in rows if r["date"] >= body.start.isoformat()]
                                if len({r["date"] for r in rows}) != len(rows):
                                    raise ValueError("K线日期重复")
                                all_dates.update(dates)
                                if len(all_dates) > 252:
                                    raise OverflowError("一次最多补算252个实际交易日，请缩短日期范围")
                                if not dates:
                                    summary["missing"] += 1
                                    summary["processed"] += 1
                                    continue
                                input_hash = self.archive.save_input(owner, rows)
                                if worker is None or not worker[0].is_alive():
                                    self._stop_worker(worker)
                                    worker = self._new_worker(owner, body.period, cancel)
                                for frame in self._frames(owner, input_hash, body.period, dates, cancel, worker):
                                    frame["coverage"] = {"input_start": rows[0]["date"], "input_end": rows[-1]["date"],
                                                         "pre_window_rows": sum(r["date"] < dates[0] for r in rows),
                                                         "input_limit": 2000, "price_basis": "enriched前复权"}
                                    self.archive.save_observation(owner, rid, symbol, names[symbol], body.source, frame, input_hash,
                                                                  frame["observed_as_of"] == dates[0])
                                if cancel.is_set():
                                    self.archive.discard_symbol(owner, rid, symbol)
                                    break
                            self.archive.compact_symbol(owner, rid, symbol)
                            summary["completed"] += 1
                            summary["completed_symbols"].append(symbol)
                        except Exception as exc:
                            # A consumer/write failure can leave the producer's
                            # remaining frames in its queue. Never reuse it.
                            self._stop_worker(worker)
                            worker = None
                            if isinstance(exc, OverflowError):
                                raise ValueError(str(exc)) from exc
                            logger.exception("chan review failed for %s", symbol)
                            self.archive.discard_symbol(owner, rid, symbol)
                            summary["failed"] += 1
                            summary["errors"].append({"symbol": symbol, "message": str(exc) if isinstance(exc, ValueError) else "计算失败，请检查服务日志"})
                        summary["processed"] += 1
                        self.store.write_summary(rid, summary)
                self._unchanged(run)
                summary["partial"] = summary["completed"] != summary["planned"]
                self.store.write_summary(rid, summary)
                # Only complete symbols become visible; interrupted symbol frames
                # are checkpoints but cannot imply a complete observation window.
                self.archive.publish_run(owner, rid, summary)
                with self._guard:
                    self.store.transition_status(rid, "cancelled" if cancel.is_set() else "failed" if summary["partial"] else "succeeded",
                                                 error="部分标的失败或缺少行情" if summary["partial"] and not cancel.is_set() else None)
        except Exception as exc:
            logger.exception("chan review run failed")
            with self._guard:
                item = self.store.get(rid)
                if item and item["status"] in ACTIVE_RUN_STATUSES:
                    self.store.transition_status(rid, "cancelled" if cancel.is_set() else "failed",
                                                 error=str(exc) if isinstance(exc, ValueError) else "扫描失败，请查看服务日志")
        finally:
            self._stop_worker(worker)
            lock.release()
            with self._guard:
                self._active.pop(rid, None)

    def shutdown(self):
        with self._guard:
            self._closed = True
            active = list(self._active.values())
            for _, event, _ in active:
                event.set()
        for thread, _, _ in active:
            thread.join(timeout=6)
