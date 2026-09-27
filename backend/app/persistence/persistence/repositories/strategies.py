"""User-owned strategy persistence; shared market data is intentionally absent."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.persistence.models import UserStrategy, UserStrategyConfig


@dataclass(frozen=True, slots=True)
class UserStrategyRecord:
    strategy_id: str
    source: str
    code: str
    strategy_meta: dict
    updated_at: datetime


class PostgresStrategyRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def owned_ids(self, user_id: UUID) -> frozenset[str]:
        result = await self._session.scalars(
            select(UserStrategy.strategy_id).where(UserStrategy.user_id == user_id)
        )
        return frozenset(result)

    async def get(self, user_id: UUID, strategy_id: str) -> UserStrategyRecord | None:
        item = await self._session.scalar(
            select(UserStrategy).where(
                UserStrategy.user_id == user_id,
                UserStrategy.strategy_id == strategy_id,
            )
        )
        return self._record(item) if item is not None else None

    async def save(
        self,
        user_id: UUID,
        strategy_id: str,
        source: str,
        code: str,
        strategy_meta: dict,
    ) -> UserStrategyRecord:
        item = await self._session.scalar(
            select(UserStrategy).where(
                UserStrategy.user_id == user_id,
                UserStrategy.strategy_id == strategy_id,
            )
        )
        if item is None:
            item = UserStrategy(
                user_id=user_id,
                strategy_id=strategy_id,
                source=source,
                code=code,
                strategy_meta=strategy_meta,
            )
            self._session.add(item)
        else:
            item.source = source
            item.code = code
            item.strategy_meta = strategy_meta
        await self._session.flush()
        await self._session.refresh(item)
        return self._record(item)

    async def delete(self, user_id: UUID, strategy_id: str) -> bool:
        result = await self._session.execute(
            delete(UserStrategy).where(
                UserStrategy.user_id == user_id,
                UserStrategy.strategy_id == strategy_id,
            )
        )
        return bool(result.rowcount)

    async def list_configs(self, user_id: UUID) -> dict[str, dict]:
        result = await self._session.scalars(
            select(UserStrategyConfig).where(UserStrategyConfig.user_id == user_id)
        )
        return {item.strategy_id: dict(item.overrides) for item in result}

    async def save_config(self, user_id: UUID, strategy_id: str, overrides: dict) -> None:
        item = await self._session.scalar(
            select(UserStrategyConfig).where(
                UserStrategyConfig.user_id == user_id,
                UserStrategyConfig.strategy_id == strategy_id,
            )
        )
        if item is None:
            self._session.add(
                UserStrategyConfig(
                    user_id=user_id,
                    strategy_id=strategy_id,
                    overrides=overrides,
                )
            )
        else:
            item.overrides = overrides
        await self._session.flush()

    async def delete_config(self, user_id: UUID, strategy_id: str) -> bool:
        result = await self._session.execute(
            delete(UserStrategyConfig).where(
                UserStrategyConfig.user_id == user_id,
                UserStrategyConfig.strategy_id == strategy_id,
            )
        )
        return bool(result.rowcount)

    @staticmethod
    def _record(item: UserStrategy) -> UserStrategyRecord:
        return UserStrategyRecord(
            strategy_id=item.strategy_id,
            source=item.source,
            code=item.code,
            strategy_meta=dict(item.strategy_meta),
            updated_at=item.updated_at,
        )
