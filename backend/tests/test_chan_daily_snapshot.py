from datetime import date
from types import SimpleNamespace

import polars as pl

from app.enriched_generation import EnrichedPublication, get_enriched_generation
from app.tickflow.repository import KlineRepository


def test_pinned_daily_files_survive_live_publication_without_blocking_it(tmp_path):
    path = tmp_path / "kline_daily_enriched/date=2025-03-05/part.parquet"
    path.parent.mkdir(parents=True)
    rows = pl.DataFrame({"symbol": ["600000.SH"], "date": [date(2025, 3, 5)],
                         "open": [10.], "high": [12.], "low": [9.], "close": [11.], "volume": [100.]})
    rows.write_parquet(path)
    original = get_enriched_generation(tmp_path)
    repo = object.__new__(KlineRepository)
    repo.store = SimpleNamespace(data_dir=tmp_path)
    with repo.daily_snapshot(date(2025, 3, 1), date(2025, 3, 5)) as snapshot:
        assert snapshot.generation == original
        publication = EnrichedPublication(tmp_path)
        publication.write_parquet(rows.with_columns(pl.lit(10.5).alias("close")), path)
        publication.commit()
        assert get_enriched_generation(tmp_path) != original
        frozen = snapshot.get_daily_batch(["600000.SH"], date(2025, 3, 1), date(2025, 3, 5), columns=["symbol", "date", "close"])
        assert frozen["close"].to_list() == [11.]
    assert pl.read_parquet(path)["close"].to_list() == [10.5]
    assert not list((tmp_path / ".daily_snapshots").glob("*"))


def test_snapshot_waits_for_publication_and_can_be_cancelled(tmp_path):
    import threading

    import pytest

    from app.enriched_generation import enriched_read_lock

    get_enriched_generation(tmp_path)
    publication = EnrichedPublication(tmp_path)
    publication.begin()
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(InterruptedError), enriched_read_lock(tmp_path, cancel_event=cancel):
        pytest.fail("publishing data must not become a readable snapshot")
    publication.abandon()
    with enriched_read_lock(tmp_path, timeout_s=1) as generation:
        assert generation


def test_hive_date_only_partition_and_snapshot_window(tmp_path):
    for day in (date(2025, 3, 5), date(2025, 3, 6)):
        path = tmp_path / f"kline_daily_enriched/date={day}/part.parquet"
        path.parent.mkdir(parents=True)
        pl.DataFrame({"symbol": ["600000.SH"], "close": [11.]}).write_parquet(path)
    repo = object.__new__(KlineRepository)
    repo.store = SimpleNamespace(data_dir=tmp_path)
    with repo.daily_snapshot(date(2025, 3, 5), date(2025, 3, 5)) as snapshot:
        result = snapshot.get_daily_batch(["600000.SH"], date(2025, 3, 5), date(2025, 3, 5), ["date", "close"])
        assert result["date"].to_list() == [date(2025, 3, 5)]
