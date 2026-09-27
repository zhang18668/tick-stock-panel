from types import SimpleNamespace
from uuid import uuid4

from app.persistence.models import UserStrategyConfig, UserStrategyInstallation
from app.strategy.access import can_access_strategy
from app.user_system.context import CurrentUser


def _user(role: str) -> CurrentUser:
    return CurrentUser(id=uuid4(), email=f"{role}@example.com", role=role, session_id=uuid4())


def _strategy(strategy_id: str, source: str, visibility: str | None = None):
    meta = {"id": strategy_id}
    if visibility is not None:
        meta["visibility_group"] = visibility
    return SimpleNamespace(meta=meta, source=source)


def test_private_builtin_is_admin_only_in_multi_user_mode() -> None:
    strategy = _strategy("private_builtin", "builtin", "private")

    assert can_access_strategy(strategy, None) is True
    assert can_access_strategy(strategy, _user("admin")) is True
    assert can_access_strategy(strategy, _user("user")) is False


def test_installed_marketplace_builtin_is_visible_only_to_owner() -> None:
    strategy = _strategy("paid_builtin", "builtin", "tianya")

    assert can_access_strategy(strategy, _user("user"), {"paid_builtin"}) is True
    assert can_access_strategy(strategy, _user("user"), set()) is False


def test_strategy_config_and_installation_models_keep_separate_contracts() -> None:
    assert {"user_id", "strategy_id", "overrides"} <= set(UserStrategyConfig.__table__.columns.keys())
    assert set(UserStrategyInstallation.__table__.primary_key.columns.keys()) == {
        "user_id", "strategy_id",
    }
    assert "overrides" not in UserStrategyInstallation.__table__.columns


def test_public_builtin_remains_visible_to_regular_users() -> None:
    assert can_access_strategy(_strategy("public_builtin", "builtin"), _user("user")) is True


def test_all_private_groups_are_admin_only() -> None:
    for visibility in ("private", "diya", "tianya", "douyin", "board_pullback"):
        strategy = _strategy(f"{visibility}_builtin", "builtin", visibility)
        assert can_access_strategy(strategy, _user("admin")) is True
        assert can_access_strategy(strategy, _user("user")) is False


def test_user_strategy_remains_owner_scoped() -> None:
    strategy = _strategy("mine", "custom")

    assert can_access_strategy(strategy, _user("user"), {"mine"}) is True
    assert can_access_strategy(strategy, _user("user"), set()) is False
