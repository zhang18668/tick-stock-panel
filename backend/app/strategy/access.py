"""Shared strategy visibility rules for HTTP entry points."""
from __future__ import annotations

from collections.abc import Collection
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from app.strategy.engine import StrategyDef


class UserContext(Protocol):
    is_admin: bool


def can_access_strategy(
    strategy: StrategyDef,
    current_user: UserContext | None,
    owned_strategy_ids: Collection[str] = (),
) -> bool:
    """Standalone sees all; grouped private built-ins are admin-only in multi-user mode."""
    if current_user is None:
        return True
    if strategy.source == "builtin":
        return strategy.meta.get("visibility_group") not in {
            "private",
            "diya",
            "tianya",
            "douyin",
            "board_pullback",
        } or current_user.is_admin or strategy.meta["id"] in owned_strategy_ids
    return strategy.meta["id"] in owned_strategy_ids
