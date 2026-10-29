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


def test_platform_configuration_rejects_regular_account():
    from types import SimpleNamespace
    from uuid import uuid4

    import pytest
    from fastapi import HTTPException

    from app.api.settings import _require_platform_configuration_access
    from app.user_system.context import CurrentUser

    user = CurrentUser(id=uuid4(), email="user@example.com", role="user", session_id=uuid4())
    request = SimpleNamespace(state=SimpleNamespace(current_user=user))
    with pytest.raises(HTTPException) as error:
        _require_platform_configuration_access(request)
    assert error.value.status_code == 403


def test_platform_configuration_allows_standalone_and_admin():
    from types import SimpleNamespace
    from uuid import uuid4

    from app.api.settings import _require_platform_configuration_access
    from app.user_system.context import CurrentUser

    _require_platform_configuration_access(SimpleNamespace(state=SimpleNamespace()))
    user = CurrentUser(id=uuid4(), email="admin@example.com", role="admin", session_id=uuid4())
    _require_platform_configuration_access(SimpleNamespace(state=SimpleNamespace(current_user=user)))


def test_assistant_preferences_do_not_inherit_platform_auto_approval(monkeypatch, tmp_path):
    path = tmp_path / "preferences.json"
    original = '{"assistant_auto_approve_actions": true, "assistant_mask_enabled": false}'
    path.write_text(original, encoding="utf-8")
    monkeypatch.setattr(preferences, "_path", lambda: path)
    preferences._invalidate_cache()
    token = settings_context.activate({}, {})
    try:
        assert preferences.get_assistant_auto_approve_actions() is False
        assert preferences.get_assistant_mask_enabled() is True
        preferences.set_assistant_auto_approve_actions(True)
        preferences.set_assistant_mask_enabled(False)
        assert settings_context.current().preference_updates == {
            "assistant_auto_approve_actions": True,
            "assistant_mask_enabled": False,
        }
        assert path.read_text(encoding="utf-8") == original
    finally:
        settings_context.reset(token)
        preferences._invalidate_cache()
