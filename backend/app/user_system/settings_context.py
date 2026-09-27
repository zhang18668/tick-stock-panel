"""Request-local user settings overlay for compatibility with legacy services."""
from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass, field


@dataclass(slots=True)
class UserSettingsContext:
    preferences: dict
    secrets: dict
    preference_updates: dict = field(default_factory=dict)
    secret_updates: dict = field(default_factory=dict)
    secret_deletes: set[str] = field(default_factory=set)


_context: ContextVar[UserSettingsContext | None] = ContextVar("user_settings", default=None)


def activate(preferences: dict, secrets: dict) -> Token:
    return _context.set(UserSettingsContext(dict(preferences), dict(secrets)))


def reset(token: Token) -> None:
    _context.reset(token)


def current() -> UserSettingsContext | None:
    return _context.get()
