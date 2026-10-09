from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.custom.strategy_optimizer import build_router
from app.strategy_optimizer.manager import OptimizationJobManager
from app.strategy_optimizer.store import OptimizationRunStore


class FakeStrategy:
    def __init__(self):
        self.strategy_id = "demo"
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
    def get(self, strategy_id):
        if strategy_id != "demo":
            raise ValueError("unknown strategy")
        return FakeStrategy()

    def strategy_definitions(self):
        return (FakeStrategy(),)


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
