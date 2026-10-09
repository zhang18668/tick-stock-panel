from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import settings
from app.services import ai_provider


def test_settings_endpoint_returns_configuration_summary(monkeypatch):
    monkeypatch.setattr(settings.secrets_store, "get_tickflow_key", lambda: "")
    monkeypatch.setattr(settings.secrets_store, "get_ai_config", lambda _key, default=None: default)
    monkeypatch.setattr(settings.secrets_store, "get_ai_key", lambda: "")
    monkeypatch.setattr(settings.secrets_store, "mask", lambda value: None if not value else "masked")
    monkeypatch.setattr(settings.tf_client, "current_mode", lambda: "free")
    monkeypatch.setattr(settings.tf_client, "current_endpoint", lambda: "https://example.test")
    monkeypatch.setattr(settings, "tier_label", lambda: "Free")
    monkeypatch.setattr(settings, "probe_log", lambda: [])
    monkeypatch.setattr(settings, "missing_caps", lambda: [])
    monkeypatch.setattr(settings, "extras_caps", lambda: [])
    monkeypatch.setattr("app.services.preferences.get_onboarding_completed", lambda: True)
    monkeypatch.setattr(ai_provider, "ai_configured", lambda _provider: False)
    for name in (
        "current_ai_model",
        "current_codex_command",
        "current_codex_model",
        "current_codex_reasoning_effort",
        "current_openai_model",
        "current_openai_reasoning_effort",
        "current_ai_context_window",
        "current_ai_max_output_tokens",
        "current_ai_round_checkpoint",
    ):
        monkeypatch.setattr(ai_provider, name, lambda: None)

    app = FastAPI()
    app.include_router(settings.router)
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/api/settings")

    assert response.status_code == 200
    assert response.json()["mode"] == "free"
