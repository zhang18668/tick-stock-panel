"""PostgreSQL persistence for isolated user settings."""
from __future__ import annotations

import json
import os
from contextlib import suppress
from uuid import UUID

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.persistence.models import UserSetting


def _fernet() -> Fernet:
    path = settings.data_dir / "user_data" / "user-settings.key"
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_bytes(Fernet.generate_key())
        with suppress(OSError):
            os.chmod(path, 0o600)
    return Fernet(path.read_bytes().strip())


def _decrypt(value: str | None) -> dict:
    if not value:
        return {}
    try:
        return json.loads(_fernet().decrypt(value.encode()).decode())
    except (InvalidToken, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError("cannot decrypt user settings") from exc


def _encrypt(value: dict) -> str | None:
    if not value:
        return None
    return _fernet().encrypt(json.dumps(value, ensure_ascii=False).encode()).decode()


class PostgresUserSettingsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def load(self, user_id: UUID) -> tuple[dict, dict]:
        row = await self._session.get(UserSetting, user_id)
        return (dict(row.preferences), _decrypt(row.secrets_encrypted)) if row else ({}, {})

    async def apply(
        self, user_id: UUID, preference_updates: dict,
        secret_updates: dict, secret_deletes: set[str],
    ) -> None:
        if not preference_updates and not secret_updates and not secret_deletes:
            return
        row = await self._session.scalar(
            select(UserSetting).where(UserSetting.user_id == user_id).with_for_update()
        )
        if row is None:
            row = UserSetting(user_id=user_id, preferences={})
            self._session.add(row)
        preferences = dict(row.preferences or {})
        preferences.update(preference_updates)
        secrets = _decrypt(row.secrets_encrypted)
        secrets.update(secret_updates)
        for key in secret_deletes:
            secrets.pop(key, None)
        row.preferences = preferences
        row.secrets_encrypted = _encrypt(secrets)
        await self._session.flush()
