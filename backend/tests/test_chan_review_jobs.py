import time
from datetime import date
from types import SimpleNamespace

import polars as pl
import pytest

from app.chan_review.contracts import ReviewRunRequest
from app.chan_review.jobs import ChanReviewJobs
from app.enriched_generation import bump_enriched_generation
from tests.test_chan_analysis import bars


class Repo:
    def __init__(self, root):
        self.store = SimpleNamespace(data_dir=root)
        self.change_generation = False
        self.calls = []

    def get_instruments(self):
        return pl.DataFrame({"symbol": ["600000.SH", "000001.SZ"], "name": ["浦发银行", "平安银行"]})

    def get_daily_batch(self, symbols, start, end, columns=None):
        self.calls.append(list(symbols))
        if self.change_generation:
            bump_enriched_generation(self.store.data_dir, "stock")
        return pl.DataFrame([{**r, "symbol": "600000.SH", "date": date.fromisoformat(r["date"])} for r in bars(150)])


def request(**extra):
    return ReviewRunRequest(source="backfill", scope="symbols", symbols=["600000.SH"], start="2025-03-01", end="2025-03-05", **extra)


def wait_done(jobs, run, owner="alice"):
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        result = jobs.get(owner, run["run_id"])
        if result["status"] not in {"queued", "running", "cancelling"}:
            return result
        time.sleep(.05)
    raise AssertionError("job did not terminate")


def test_real_worker_persists_history_and_survives_manager_reopen(tmp_path):
    repo = Repo(tmp_path)
    jobs = ChanReviewJobs(tmp_path)
    try:
        run = jobs.create("alice", request(), repo)
        result = wait_done(jobs, run)
        assert result["status"] == "succeeded", result
        assert result["summary"]["completed"] == 1
        assert repo.calls == [["600000.SH"]]
        signals = jobs.archive.list_signals("alice", {"source": "backfill"}, 1, 100)
        assert signals["total"] > 0
        item = signals["items"][0]
        assert max(r["date"] for r in jobs.archive.get_snapshot("alice", item["snapshot_id"])["rows"]) <= item["first_seen"]
        with pytest.raises(KeyError):
            jobs.get("bob", run["run_id"])
    finally:
        jobs.shutdown()
    reopened = ChanReviewJobs(tmp_path)
    try:
        assert reopened.get("alice", run["run_id"])["status"] == "succeeded"
    finally:
        reopened.shutdown()


def test_generation_change_publishes_no_mixed_results(tmp_path):
    repo = Repo(tmp_path)
    repo.change_generation = True
    jobs = ChanReviewJobs(tmp_path)
    try:
        result = wait_done(jobs, jobs.create("alice", request(), repo))
        assert result["status"] == "failed"
        assert jobs.archive.list_signals("alice", {}, 1, 30)["total"] == 0
    finally:
        jobs.shutdown()


def test_scope_unknown_assets_and_observed_history_rejected(tmp_path):
    jobs = ChanReviewJobs(tmp_path)
    try:
        with pytest.raises(ValueError):
            jobs.create("alice", ReviewRunRequest(source="backfill", scope="symbols", symbols=["bad"], start="2025-03-01", end="2025-03-05"), Repo(tmp_path))
        with pytest.raises(ValueError):
            ReviewRunRequest(source="observed", start="2025-03-01", end="2025-03-05")
    finally:
        jobs.shutdown()


def test_retry_reuses_completed_checkpoints_and_rejects_changed_generation(tmp_path):
    repo = Repo(tmp_path)
    jobs = ChanReviewJobs(tmp_path)
    try:
        first = wait_done(jobs, jobs.create("alice", request(), repo))
        assert first["status"] == "succeeded"
        def no_calculation(*args):
            raise AssertionError("completed checkpoints must not be recomputed")
        jobs._frames = no_calculation
        retry = wait_done(jobs, jobs.create("alice", request(resume_from=first["run_id"]), repo))
        assert retry["summary"]["completed"] == 1
        assert jobs.archive.list_signals("alice", {}, 1, 100)["total"] > 0
        bump_enriched_generation(tmp_path, "stock")
        with pytest.raises(ValueError, match="未改变"):
            jobs.create("alice", request(resume_from=first["run_id"]), repo)
    finally:
        jobs.shutdown()


def test_cancel_queued_and_second_manager_does_not_interrupt_live_coordinator(tmp_path):
    import threading

    from app.services.heavy_job_limiter import shared_heavy_job_limiter

    repo = Repo(tmp_path)
    jobs = ChanReviewJobs(tmp_path)
    release, entered = threading.Event(), threading.Event()
    def occupy():
        with shared_heavy_job_limiter.slot("exclusive"):
            entered.set()
            release.wait(15)
    thread = threading.Thread(target=occupy)
    thread.start()
    assert entered.wait(5)
    reopened = None
    try:
        run = jobs.create("alice", request(), repo)
        reopened = ChanReviewJobs(tmp_path)
        assert reopened.get("alice", run["run_id"])["status"] == "queued"
        jobs.cancel("alice", run["run_id"])
        assert wait_done(jobs, run)["status"] == "cancelled"
        assert repo.calls == []
    finally:
        release.set()
        thread.join(5)
        jobs.shutdown()
        if reopened:
            reopened.shutdown()


def test_duplicate_dates_fail_stock_and_publish_no_false_success(tmp_path):
    repo = Repo(tmp_path)
    original = repo.get_daily_batch
    repo.get_daily_batch = lambda *a, **kw: pl.concat([data := original(*a, **kw), data.head(1)])
    jobs = ChanReviewJobs(tmp_path)
    try:
        run = wait_done(jobs, jobs.create("alice", request(), repo))
        assert run["status"] == "failed"
        assert run["summary"]["failed"] == 1
        assert "重复" in run["summary"]["errors"][0]["message"]
        assert jobs.archive.list_signals("alice", {}, 1, 30)["total"] == 0
    finally:
        jobs.shutdown()


def test_overlong_window_is_a_failed_run_without_published_results(tmp_path):
    repo = Repo(tmp_path)
    repo.get_daily_batch = lambda *a, **kw: pl.DataFrame([{**r, "symbol": "600000.SH", "date": date.fromisoformat(r["date"])} for r in bars(300)])
    jobs = ChanReviewJobs(tmp_path)
    try:
        body = ReviewRunRequest(source="backfill", scope="symbols", symbols=["600000.SH"], start="2025-01-01", end="2025-12-31")
        run = wait_done(jobs, jobs.create("alice", body, repo))
        assert run["status"] == "failed"
        assert "252" in run["error"]
        assert jobs.archive.list_signals("alice", {}, 1, 30)["total"] == 0
    finally:
        jobs.shutdown()


def test_observed_before_close_and_future_dates_rejected(monkeypatch):
    from datetime import datetime

    from app.chan_review import contracts
    from app.market_time import CN_TZ

    monkeypatch.setattr(contracts, "cn_now", lambda: datetime(2026, 10, 30, 10, tzinfo=CN_TZ))
    with pytest.raises(ValueError, match="15:30"):
        ReviewRunRequest(source="observed", start="2026-10-30", end="2026-10-30")
    with pytest.raises(ValueError, match="未来"):
        ReviewRunRequest(source="backfill", start="2026-10-31", end="2026-10-31")


def test_one_spawn_worker_is_reused_across_stocks(tmp_path, monkeypatch):
    import multiprocessing

    from app.chan_review import jobs as module

    context = multiprocessing.get_context("spawn")
    spawned = []
    def process(**kwargs):
        spawned.append(kwargs["target"])
        return context.Process(**kwargs)
    monkeypatch.setattr(module.mp, "get_context", lambda _: SimpleNamespace(Event=context.Event, Queue=context.Queue, Process=process))
    repo = Repo(tmp_path)
    original = repo.get_daily_batch
    def data(*args, **kwargs):
        first = original(*args, **kwargs)
        return pl.concat([first, first.with_columns(pl.lit("000001.SZ").alias("symbol"))])
    repo.get_daily_batch = data
    jobs = ChanReviewJobs(tmp_path)
    try:
        body = ReviewRunRequest(source="backfill", scope="market", start="2025-03-01", end="2025-03-05")
        run = wait_done(jobs, jobs.create("alice", body, repo))
        assert run["summary"]["completed"] == 2
        assert len(spawned) == 1
    finally:
        jobs.shutdown()


def test_stock_save_failure_cannot_contaminate_next_stock_frames(tmp_path, monkeypatch):
    repo = Repo(tmp_path)
    def data(*args, **kwargs):
        first = pl.DataFrame([{**r, "symbol": "000001.SZ", "date": date.fromisoformat(r["date"])} for r in bars(150)])
        second = first.with_columns(pl.lit("600000.SH").alias("symbol"), *[(pl.col(k) * 10).alias(k) for k in ("open", "high", "low", "close")])
        return pl.concat([first, second])
    repo.get_daily_batch = data
    jobs = ChanReviewJobs(tmp_path)
    save_observation = jobs.archive.save_observation
    def save(owner, run_id, symbol, *args):
        if symbol == "000001.SZ":
            raise OSError("injected first-stock save failure")
        return save_observation(owner, run_id, symbol, *args)
    monkeypatch.setattr(jobs.archive, "save_observation", save)
    try:
        body = ReviewRunRequest(source="backfill", scope="market", start="2025-03-01", end="2025-03-05")
        run = wait_done(jobs, jobs.create("alice", body, repo))
        assert run["summary"]["failed"] == 1
        assert run["summary"]["completed"] == 1
        signals = jobs.archive.list_signals("alice", {}, 1, 100)["items"]
        assert signals
        for item in signals:
            assert item["symbol"] == "600000.SH"
            assert min(r["close"] for r in jobs.archive.get_snapshot("alice", item["snapshot_id"])["rows"]) > 500
    finally:
        jobs.shutdown()


def test_observed_resume_keeps_original_date_after_weekend(tmp_path, monkeypatch):
    from datetime import datetime

    from app.chan_review import contracts
    from app.market_time import CN_TZ

    monkeypatch.setattr(contracts, "cn_now", lambda: datetime(2025, 3, 5, 16, tzinfo=CN_TZ))
    jobs = ChanReviewJobs(tmp_path)
    try:
        original = ReviewRunRequest(source="observed", scope="symbols", symbols=["600000.SH"], start="2025-03-05", end="2025-03-05")
        first = wait_done(jobs, jobs.create("alice", original, Repo(tmp_path)))
        monkeypatch.setattr(contracts, "cn_now", lambda: datetime(2025, 3, 10, 10, tzinfo=CN_TZ))
        resume = ReviewRunRequest(**{**original.model_dump(), "resume_from": first["run_id"]})
        retry = wait_done(jobs, jobs.create("alice", resume, Repo(tmp_path)))
        assert retry["status"] == "succeeded"
        assert retry["request"]["end"] == "2025-03-05"
        with pytest.raises(KeyError):
            jobs.create("bob", resume, Repo(tmp_path))
    finally:
        jobs.shutdown()
