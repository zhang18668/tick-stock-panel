"""Immutable daily repository view, pinned briefly without pausing live quotes."""
import os
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

import polars as pl

from app.enriched_generation import enriched_read_lock
from app.parquet import scan_enriched_parquet
from app.polars_guard import guarded_collect


@dataclass(frozen=True)
class DailySnapshot:
    generation: str
    paths: tuple[str, ...]

    def get_daily_batch(self, symbols: list[str], start: date, end: date, columns=None) -> pl.DataFrame:
        if not self.paths:
            return pl.DataFrame()
        query = scan_enriched_parquet(list(self.paths), hive_partitioning=True).filter(
            pl.col("symbol").is_in(symbols) & (pl.col("date") >= start) & (pl.col("date") <= end))
        query = query.sort(["symbol", "date"])
        if columns:
            query = query.select(columns)
        return guarded_collect(query)


@contextmanager
def daily_snapshot(data_dir: Path, start: date, end: date, *, cancel_event=None):
    root = Path(data_dir) / ".daily_snapshots"
    root.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="read-", dir=root) as temporary:
        paths = []
        with enriched_read_lock(Path(data_dir), cancel_event=cancel_event) as generation:
            for partition in sorted((Path(data_dir) / "kline_daily_enriched").glob("date=*")):
                day = date.fromisoformat(partition.name.removeprefix("date="))
                if not start <= day <= end:
                    continue
                for path in sorted(partition.glob("*.parquet")):
                    if cancel_event is not None and cancel_event.is_set():
                        raise InterruptedError("已取消行情快照准备")
                    target = Path(temporary) / partition.name / path.name
                    target.parent.mkdir(exist_ok=True)
                    # Publishers replace files atomically; hard links keep the
                    # old inode readable while real-time updates replace paths.
                    os.link(path, target)
                    paths.append(str(target))
        yield DailySnapshot(generation, tuple(paths))
