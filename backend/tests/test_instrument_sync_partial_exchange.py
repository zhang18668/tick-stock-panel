"""不完整的交易所响应不能覆盖股票标的维表。"""
from __future__ import annotations

import polars as pl

from app.services import instrument_sync


class _FakeExchanges:
    @staticmethod
    def get_instruments(exchange: str, instrument_type: str):
        assert instrument_type == "stock"
        if exchange == "SH":
            return [{"symbol": "600000.SH", "name": "浦发银行"}]
        if exchange == "SZ":
            raise RuntimeError("temporary provider failure")
        return [{"symbol": "430001.BJ", "name": "特锐德"}]


class _ExchangeClient:
    def __init__(self) -> None:
        self.exchanges = _FakeExchanges()


def test_failed_exchange_does_not_replace_existing_instruments(tmp_path, monkeypatch) -> None:
    target = tmp_path / "instruments" / "instruments.parquet"
    target.parent.mkdir(parents=True)
    existing = pl.DataFrame({
        "symbol": ["600000.SH", "000001.SZ", "430001.BJ"],
        "name": ["浦发银行", "平安银行", "特锐德"],
    })
    existing.write_parquet(target)

    monkeypatch.setattr(instrument_sync, "_fetch_instruments_via_provider", lambda: None)
    monkeypatch.setattr(instrument_sync, "get_client", lambda: _ExchangeClient())

    assert instrument_sync.sync_instruments(tmp_path) == 0
    assert_frame = pl.read_parquet(target)
    assert assert_frame.equals(existing)
