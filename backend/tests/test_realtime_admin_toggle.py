from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.api.settings import RealtimeQuotesPrefs, update_realtime_quotes


def _request(role: str):
    return SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(quote_service=None)),
        state=SimpleNamespace(current_user=SimpleNamespace(is_admin=role == "admin")),
    )


def test_disable_request_keeps_global_realtime_quotes_enabled():
    request = _request("admin")
    request.app.state.quote_service = MagicMock()
    request.app.state.quote_service.is_realtime_allowed.return_value = True
    request.app.state.quote_service.realtime_mode.return_value = "full_market"
    with patch("app.services.preferences.save") as save:
        result = update_realtime_quotes(RealtimeQuotesPrefs(realtime_quotes_enabled=False), request)
    assert result["realtime_quotes_enabled"] is True
    save.assert_called_once_with({"realtime_quotes_enabled": True})
    request.app.state.quote_service.enable.assert_called_once_with()
    request.app.state.quote_service.disable.assert_not_called()
