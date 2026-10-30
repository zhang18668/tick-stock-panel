from datetime import date, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.custom.chan_analysis import router
from app.services.chan_analysis import analyze


def bars(n=150):
    import math

    return [
        {
            "date": str(date(2025, 1, 1) + timedelta(days=i)),
            "open": (v := 100 + 20 * math.sin(i * 0.4) + 10 * math.sin(i * 0.08)),
            "close": v + 0.5,
            "high": v + 2,
            "low": v - 2,
            "volume": 1000,
        }
        for i in range(n)
    ]


def test_upstream_engine_produces_real_structures_and_metrics():
    result = analyze(bars(), "day")
    assert result["engine"]["name"] == "chan.py"
    assert result["engine"]["revision"] == "f8ca3b5e44d7166e2abd756a8e7fa816c79faebe"
    strokes = [s for s in result["structures"] if s["kind"] == "stroke"]
    assert len(strokes) >= 6
    # First peak is Jan 5: 100 + 20*sin(1.6) + 10*sin(.32) + high offset 2.
    assert strokes[0]["start"]["date"] == "2025-01-05"
    assert strokes[0]["start"]["price"] == pytest.approx(125.13713766699128)
    assert any(s["kind"] == "center" for s in result["structures"])
    assert any(s["kind"] == "segment" for s in result["structures"])
    assert all(s["confirmedAt"] is None or s["confirmedAt"] >= s["end"]["date"] for s in result["structures"])
    assert "macd_hist" in result["rows"][-1]
    assert all(s["confirmedAt"] is None for s in result["structures"] if s["kind"] == "signal")


def test_weekly_aggregation_and_latest_week_is_not_confirming_evidence():
    data = [
        {"date": "2025-12-29", "open": 10, "high": 12, "low": 10, "close": 12, "volume": 10},
        {"date": "2026-01-02", "open": 11, "high": 15, "low": 11, "close": 15, "volume": 20},
        {"date": "2026-01-05", "open": 13, "high": 16, "low": 13, "close": 16, "volume": 10},
    ]
    result = analyze(data, "week")
    assert len(result["rows"]) == 2
    assert result["rows"][0] | {} == {
        "date": "2026-01-02", "open": 10, "high": 15, "low": 10, "close": 15,
        "volume": 30, "macd_dif": 0, "macd_dea": 0, "macd_hist": 0,
    }
    assert result["warnings"]


def test_cutoff_never_reads_later_rows_and_empty_is_safe():
    assert analyze([], "day")["structures"] == []
    first = analyze(bars()[:70], "day")
    assert max(r["date"] for r in first["rows"]) == "2025-03-11"
    assert all(s["end"]["index"] < 70 for s in first["structures"])
    assert all(s["confirmedAt"] is None or s["confirmedAt"] <= "2025-03-11" for s in first["structures"])


def test_stateless_api_validates_and_exposes_current_engine():
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    response = client.post("/api/custom/chan/analyze", json={"symbol": "600000.SH", "period": "day", "rows": bars(20)})
    assert response.status_code == 200
    assert response.json()["symbol"] == "600000.SH"
    assert response.json()["engine"]["name"] == "chan.py"
    for rows in [[{**bars(1)[0], "low": 999}], [bars(1)[0], bars(1)[0]]]:
        assert client.post("/api/custom/chan/analyze", json={"symbol": "600000.SH", "rows": rows}).status_code == 422
    assert client.post("/api/custom/chan/analyze", json={"symbol": "x", "period": "minute", "rows": []}).status_code == 422
    assert client.post("/api/custom/chan/analyze", json={"symbol": "x", "rows": bars(2001)}).status_code == 422


def test_vendor_sources_have_only_declared_namespace_rewrites():
    import hashlib
    import json
    import re
    from pathlib import Path

    root = Path(__file__).parents[1] / "app" / "vendor" / "chanpy"
    manifest = json.loads((root / "UPSTREAM.json").read_text(encoding="utf-8"))
    for relative, expected in manifest["sha256"].items():
        source = (root / relative).read_bytes()
        # Original Git checkout has LF endings; only declared import prefixes change.
        original = re.sub(rb"(?m)^(\s*from )app\.vendor\.chanpy\.", rb"\1", source)
        assert hashlib.sha256(original).hexdigest() == expected, relative
    assert "MIT License" in (root / "LICENSE").read_text()


def test_current_day_cannot_confirm_structure_until_close_and_prefix_is_causal():
    from datetime import datetime
    from zoneinfo import ZoneInfo

    now = datetime(2025, 3, 11, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    prefix = analyze(bars(69), "day", now=now)
    current = analyze(bars(70), "day", now=now)
    assert current["asOf"] == "2025-03-10"
    assert current["structures"] == prefix["structures"]
    assert len(current["rows"]) == 70
    future = analyze(bars(150), "day")
    sure_strokes = {s["id"]: s for s in prefix["structures"] if s["kind"] == "stroke" and s["confirmedAt"]}
    for s in future["structures"]:
        if s["id"] in sure_strokes:
            assert s["confirmedAt"] == sure_strokes[s["id"]]["confirmedAt"]


def test_custom_module_is_discovered_without_modifying_main(monkeypatch):
    from app.extensions.loader import configure_backend_extensions

    monkeypatch.setattr("app.extensions.loader._custom_module_names", lambda: ["app.custom.chan_analysis"])
    app = FastAPI()
    registry, errors = configure_backend_extensions(app)
    assert not errors
    assert "chan.analysis" in registry.extension_ids()
    assert TestClient(app).post("/api/custom/chan/analyze", json={"symbol": "600000.SH", "rows": []}).json()["structures"] == []


def test_weekly_confirmation_date_matches_historical_cutoff_availability():
    data = bars(240)
    full = analyze(data, "week")
    fractals = [s for s in full["structures"] if s["kind"] == "fractal" and s["confirmedAt"]]
    assert fractals
    for structure in fractals[:4]:
        cutoff_rows = [r for r in data if r["date"] <= structure["confirmedAt"]]
        snapshot = analyze(cutoff_rows, "week")
        assert structure["id"] in {s["id"] for s in snapshot["structures"]}, structure
