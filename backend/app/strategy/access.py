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
    """Strategies are shared across accounts; user-specific group settings are separate."""
    return True
