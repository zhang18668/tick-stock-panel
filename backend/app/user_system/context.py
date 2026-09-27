"""Immutable authenticated-user context."""
from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class CurrentUser:
    id: UUID
    email: str
    role: str
    session_id: UUID

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"
