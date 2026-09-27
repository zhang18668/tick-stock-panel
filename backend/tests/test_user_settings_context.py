from app import secrets_store
from app.services import preferences
from app.user_system import settings_context


def test_request_preferences_overlay_does_not_write_global_file(monkeypatch):
    monkeypatch.setattr(preferences, "_path", lambda: type("Missing", (), {"exists": lambda self: False})())
    token = settings_context.activate({"nav_hidden": ["data"]}, {})
    try:
        assert preferences.get_nav_hidden() == ["data"]
        preferences.save({"nav_hidden": ["review"]})
        context = settings_context.current()
        assert context.preference_updates == {"nav_hidden": ["review"]}
    finally:
        settings_context.reset(token)


def test_platform_secrets_ignore_user_overrides(monkeypatch, tmp_path):
    path = tmp_path / "secrets.json"
    path.write_text('{"ai_api_key":"global-ai","tickflow_api_key":"global-tf"}', encoding="utf-8")
    monkeypatch.setattr(secrets_store, "_path", lambda: path)
    token = settings_context.activate(
        {},
        {"ai_api_key": "user-ai", "tickflow_api_key": "user-tf", "feishu_webhook_url": "user-hook"},
    )
    try:
        assert secrets_store.get_ai_key() == "global-ai"
        assert secrets_store.get_tickflow_key() == "global-tf"
        assert secrets_store.load()["feishu_webhook_url"] == "user-hook"
    finally:
        settings_context.reset(token)
