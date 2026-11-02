"""Owner-scoped Chan archives, registered through the existing extension API."""
import threading
from datetime import date
from typing import Literal

import anyio
import polars as pl
from fastapi import APIRouter, HTTPException, Query, Request

from app.chan_review.contracts import ReviewRunRequest
from app.chan_review.jobs import ChanReviewJobs
from app.config import settings
from app.extensions import BACKEND_EXTENSION_API_VERSION, BackendExtensionRegistrar
from app.market_time import cn_today
from app.services.chan_analysis import ChanBar, _weekly
from app.services.watchlist_repository import WatchlistStore
from app.user_system.context import CurrentUser
from app.vendor.chanpy.Math.MACD import CMACD

EXTENSION_ID = "chan.review"
EXTENSION_API_VERSION = BACKEND_EXTENSION_API_VERSION
router = APIRouter(prefix="/api/custom/chan-review", tags=["chan-review"])
_guard = threading.Lock()
_managers: set[ChanReviewJobs] = set()


def _context(request):
    user = getattr(request.state, "current_user", None)
    if settings.app_mode == "multi_user" and not isinstance(user, CurrentUser):
        raise HTTPException(401, "请先登录")
    owner = str(user.id) if isinstance(user, CurrentUser) else "standalone"
    repo = getattr(request.app.state, "repo", None)
    if repo is None:
        raise HTTPException(503, "行情仓库尚未就绪")
    with _guard:
        if not hasattr(request.app.state, "chan_review_jobs"):
            request.app.state.chan_review_jobs = ChanReviewJobs(repo.store.data_dir)
            _managers.add(request.app.state.chan_review_jobs)
    return owner, request.app.state.chan_review_jobs, repo


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except KeyError as exc:
        raise HTTPException(404, "归档或任务不存在") from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/runs")
async def create_run(body: ReviewRunRequest, request: Request, watchlist: WatchlistStore):
    owner, jobs, repo = _context(request)
    if body.scope == "watchlist":
        body = body.model_copy(update={"symbols": [item["symbol"] for item in await watchlist.list()]})
    return await anyio.to_thread.run_sync(lambda: _call(jobs.create, owner, body, repo))


@router.get("/runs")
def list_runs(request: Request):
    owner, jobs, _ = _context(request)
    return {"items": jobs.list(owner)}


@router.get("/runs/{run_id}")
def get_run(run_id: str, request: Request):
    owner, jobs, _ = _context(request)
    return _call(jobs.get, owner, run_id)


@router.post("/runs/{run_id}/cancel")
def cancel_run(run_id: str, request: Request):
    owner, jobs, _ = _context(request)
    return _call(jobs.cancel, owner, run_id)


@router.get("/signals")
def list_signals(request: Request, source: Literal["observed", "backfill"] | None = None,
                 period: Literal["day", "week"] | None = None,
                 category: Literal["1", "2", "3"] | None = None,
                 point_type: Literal["1", "1p", "2", "2s", "3a", "3b"] | None = None,
                 date_field: Literal["first_seen", "point_date"] = "first_seen",
                 start: date | None = None,
                 end: date | None = None,
                 q: str = Query("", max_length=100), page: int = Query(1, ge=1),
                 page_size: int = Query(30, ge=1, le=100)):
    owner, jobs, _ = _context(request)
    if start and end and start > end:
        raise HTTPException(422, "起始日期不能晚于结束日期")
    filters = dict(source=source, period=period, category=category, point_type=point_type,
                   date_field=date_field, start=start.isoformat() if start else None, end=end.isoformat() if end else None, q=q)
    return _call(jobs.archive.list_signals, owner, filters, page, page_size)


@router.get("/signals/{signal_id}")
def get_signal(signal_id: str, request: Request):
    owner, jobs, _ = _context(request)
    return _call(jobs.archive.get_signal, owner, signal_id)


@router.get("/snapshots/{snapshot_id}")
def get_snapshot(snapshot_id: str, request: Request):
    owner, jobs, _ = _context(request)
    return _call(jobs.archive.get_snapshot, owner, snapshot_id)


@router.get("/signals/{signal_id}/following")
def get_following(signal_id: str, request: Request):
    owner, jobs, repo = _context(request)
    signal = _call(jobs.archive.get_signal, owner, signal_id)
    snapshot = _call(jobs.archive.get_snapshot, owner, signal["snapshot_id"])
    start = date.fromisoformat(snapshot["rows"][0]["date"])
    data = repo.get_daily_batch([signal["symbol"]], start, cn_today(),
                                columns=["symbol", "date", "open", "high", "low", "close", "volume"])
    rows = [{k: str(r[k])[:10] if k == "date" else r[k] for k in ("date", "open", "high", "low", "close", "volume")}
            for r in data.filter((pl.col("symbol") == signal["symbol"]) & (pl.col("date") <= cn_today())).sort("date").to_dicts()] if not data.is_empty() else []
    # This view uses today's adjusted price basis, and deliberately carries no
    # old price-coordinate structures. The historical view remains immutable.
    rows = [ChanBar.model_validate(r).model_dump(mode="json") for r in rows[-2000:]]
    if len({r["date"] for r in rows}) != len(rows):
        raise HTTPException(422, "行情日期重复，不能可靠展示后续走势")
    rows = _weekly(rows) if signal["period"] == "week" else rows
    metric = CMACD()
    for row in rows:
        macd = metric.add(row["close"])
        row.update(macd_dif=macd.DIF, macd_dea=macd.DEA, macd_hist=macd.macd)
    return {"rows": rows, "symbol": signal["symbol"], "period": signal["period"]}


def setup(registrar: BackendExtensionRegistrar) -> None:
    registrar.include_router(router)


def shutdown() -> None:
    for manager in list(_managers):
        manager.shutdown()
    _managers.clear()
