from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.custom import chan_review
from app.user_system.context import CurrentUser


@pytest.fixture
def client(tmp_path, monkeypatch):
    from tests.test_chan_review_jobs import Repo

    monkeypatch.setattr(chan_review.settings, "app_mode", "multi_user")
    app = FastAPI()
    app.state.repo = Repo(tmp_path)

    @app.middleware("http")
    async def identity(request, call_next):
        value = request.headers.get("x-test-user")
        if value:
            request.state.current_user = CurrentUser(UUID(value), "", "user", UUID(int=0))
        return await call_next(request)

    app.include_router(chan_review.router)
    with TestClient(app) as result:
        yield result
    if hasattr(app.state, "chan_review_jobs"):
        app.state.chan_review_jobs.shutdown()


def test_auth_and_input_validation(client):
    assert client.get("/api/custom/chan-review/signals").status_code == 401
    headers = {"x-test-user": str(UUID(int=1))}
    assert client.get("/api/custom/chan-review/signals", headers=headers).json()["total"] == 0
    assert client.post("/api/custom/chan-review/runs", headers=headers, json={"source": "backfill", "start": "2025-03-10", "end": "2025-03-01"}).status_code == 422
    assert client.post("/api/custom/chan-review/runs", headers=headers, json={"source": "backfill", "start": "2025-03-01", "end": "2025-03-02", "owner_scope": "other"}).status_code == 422
    assert client.get("/api/custom/chan-review/signals?page_size=999", headers=headers).status_code == 422


def test_owners_cannot_read_or_cancel_others_runs(client):
    a = {"x-test-user": str(UUID(int=1))}
    b = {"x-test-user": str(UUID(int=2))}
    body = {"source": "backfill", "scope": "symbols", "symbols": ["600000.SH"], "start": "2025-03-01", "end": "2025-03-05"}
    response = client.post("/api/custom/chan-review/runs", headers=a, json=body)
    assert response.status_code == 200, response.text
    run = response.json()
    assert client.get(f"/api/custom/chan-review/runs/{run['run_id']}", headers=b).status_code == 404
    assert client.post(f"/api/custom/chan-review/runs/{run['run_id']}/cancel", headers=b).status_code == 404
    assert client.get("/api/custom/chan-review/runs", headers=b).json()["items"] == []
    assert client.get("/api/custom/chan-review/snapshots/" + "a" * 64, headers=b).status_code == 404
