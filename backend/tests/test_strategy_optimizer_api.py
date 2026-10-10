from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.custom.strategy_optimizer import build_router
from app.strategy_optimizer.manager import OptimizationJobManager
from app.strategy_optimizer.store import OptimizationRunStore


class FakeStrategy:
    def __init__(self):
        self.meta = {
            "id": "demo",
            "name": "Demo",
            "asset_type": "stock",
            "params": [
                {
                    "id": "window",
                    "label": "Window",
                    "type": "int",
                    "default": 10,
                    "min": 2,
                    "max": 30,
                    "step": 1,
                }
            ],
        }
        self.entry_signals = ["buy_a"]
        self.exit_signals = ["sell_a"]
        self.file_path = None
        self.source = "custom"


class FakeEngine:
    def __init__(self):
        self.strategy = FakeStrategy()

    def get(self, strategy_id):
        if strategy_id != "demo":
            raise ValueError("unknown strategy")
        return self.strategy

    def strategy_definitions(self):
        return (self.strategy,)


class FakeRepo:
    store = SimpleNamespace(data_dir=None)

    def get_matrix_data_generation(self, asset_type):
        return "generation-1"


def make_client(tmp_path):
    app = FastAPI()

    @app.middleware("http")
    async def copy_test_user(request, call_next):
        if hasattr(app.state, "test_user"):
            request.state.current_user = app.state.test_user
            request.state.owned_strategy_ids = app.state.test_owned_ids
        return await call_next(request)

    app.state.strategy_engine = FakeEngine()
    repo = FakeRepo()
    repo.store = SimpleNamespace(data_dir=tmp_path)
    app.state.repo = repo
    app.include_router(build_router())
    return TestClient(app)


def test_strategy_and_contract_endpoints_expose_only_declared_ranges(tmp_path):
    client = make_client(tmp_path)
    strategies = client.get("/api/custom/strategy-optimizer/strategies")
    contract = client.get("/api/custom/strategy-optimizer/strategies/demo/contract")
    assert strategies.status_code == 200
    assert strategies.json()[0]["optimizable"] is True
    assert contract.json()["parameters"][0]["minimum"] == 2


def test_run_request_rejects_unknown_strategy_and_unknown_fields(tmp_path):
    client = make_client(tmp_path)
    base = {"strategy_id": "demo", "start": "2024-01-01", "end": "2025-12-31"}
    assert (
        client.post(
            "/api/custom/strategy-optimizer/runs", json={**base, "unknown": True}
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/custom/strategy-optimizer/runs", json={**base, "strategy_id": "absent"}
        ).status_code
        == 404
    )


def test_private_strategy_and_run_endpoints_are_owner_scoped(tmp_path):
    client = make_client(tmp_path)
    client.app.state.test_user = SimpleNamespace(id="alice", is_admin=False)
    client.app.state.test_owned_ids = frozenset()
    response = client.get("/api/custom/strategy-optimizer/strategies/demo/contract")
    assert response.status_code == 404
    assert client.get("/api/custom/strategy-optimizer/strategies").json() == []


def test_create_run_uses_manager_and_persists_owner_scope(tmp_path):
    client = make_client(tmp_path)
    client.app.state.strategy_optimizer_manager = OptimizationJobManager(
        OptimizationRunStore(tmp_path / "runs"),
        lambda config, progress, cancel: {"top3": [], "candidates": []},
    )
    response = client.post(
        "/api/custom/strategy-optimizer/runs",
        json={"strategy_id": "demo", "start": "2022-01-01", "end": "2025-12-31"},
    )
    assert response.status_code == 202
    record = response.json()
    assert record["config"]["owner_scope"] == "standalone"
    assert record["run_id"] in {
        item["run_id"] for item in client.get("/api/custom/strategy-optimizer/runs").json()
    }


def test_save_recommendations_creates_independent_strategies_from_passed_candidates(tmp_path, monkeypatch):
    from app.api import strategy as strategy_api

    saved = []

    def save_strategy(req, request):
        saved.append(req)
        return {"ok": True, "strategy_id": req.strategy_id, "meta": {"name": req.name}}

    async def persist_strategy(_request, _result):
        return None

    monkeypatch.setattr(strategy_api, "_save_strategy_code", save_strategy)
    monkeypatch.setattr(strategy_api, "_persist_user_strategy", persist_strategy)
    client = make_client(tmp_path)
    source = tmp_path / "demo.py"
    source.write_text('META = {"id": "demo", "name": "Demo", "params": [{"id": "window", "type": "int", "default": 10, "min": 2, "max": 30, "step": 1}]}\nENTRY_SIGNALS = ["buy_a"]\nEXIT_SIGNALS = ["sell_a"]\n', encoding="utf-8")
    client.app.state.strategy_engine.get("demo").file_path = source
    run_id = "a1b2c3d4e5f6"
    client.app.state.strategy_optimizer_manager = SimpleNamespace(get=lambda _run_id: {
        "run_id": run_id, "state": "succeeded",
        "config": {"strategy_id": "demo", "owner_scope": "standalone"},
        "result": {"top3": [
            {"parameters": {"window": 12}, "buy_signals": ["buy_a"], "sell_signals": ["sell_a"]},
            {"parameters": {"window": 15}, "buy_signals": ["buy_a"], "sell_signals": ["sell_a"]},
        ]},
    })

    response = client.post(f"/api/custom/strategy-optimizer/runs/{run_id}/save")

    assert response.status_code == 200
    assert [item.strategy_id for item in saved] == [
        f"custom_opt_{run_id[:12]}_top1",
        f"custom_opt_{run_id[:12]}_top2",
    ]
    assert [item.name for item in saved] == ["Demo-top1", "Demo-top2"]
    assert [item.mode for item in saved] == ["create", "create"]
    assert "'default': 12" in saved[0].code
    assert 'ENTRY_SIGNALS = [\'buy_a\']' in saved[0].code
    assert "'default': 15" in saved[1].code
