"""PostgreSQL watchlist repository.

Every query is explicitly scoped by user_id. Shared quote and enriched-market
lookups remain in the existing global KlineRepository.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.persistence.models import User, WatchlistItem


@dataclass(frozen=True, slots=True)
class WatchlistRecord:
    symbol: str
    asset_type: str
    note: str
    position: int
    added_at: datetime


class PostgresWatchlistRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list(self, user_id: UUID) -> list[WatchlistRecord]:
        result = await self._session.scalars(
            select(WatchlistItem)
            .where(WatchlistItem.user_id == user_id)
            .order_by(WatchlistItem.position, WatchlistItem.added_at.desc())
        )
        return [self._record(item) for item in result]

    async def add(
        self, user_id: UUID, symbol: str, note: str = "", asset_type: str = "stock"
    ) -> list[WatchlistRecord]:
        await self._lock_user(user_id)
        existing = await self._session.scalar(
            select(WatchlistItem).where(
                WatchlistItem.user_id == user_id,
                WatchlistItem.symbol == symbol,
                WatchlistItem.asset_type == asset_type,
            )
        )
        await self._session.execute(
            update(WatchlistItem)
            .where(WatchlistItem.user_id == user_id)
            .values(position=WatchlistItem.position + 1)
        )
        if existing is None:
            self._session.add(
                WatchlistItem(
                    user_id=user_id,
                    symbol=symbol,
                    asset_type=asset_type,
                    note=note,
                    position=0,
                )
            )
        else:
            existing.note = note
            existing.position = 0
            existing.added_at = func.now()
        await self._session.flush()
        return await self.list(user_id)

    async def remove(self, user_id: UUID, symbol: str) -> list[WatchlistRecord]:
        await self._lock_user(user_id)
        position = await self._session.scalar(
            select(WatchlistItem.position).where(
                WatchlistItem.user_id == user_id, WatchlistItem.symbol == symbol
            )
        )
        await self._session.execute(
            delete(WatchlistItem).where(
                WatchlistItem.user_id == user_id, WatchlistItem.symbol == symbol
            )
        )
        if position is not None:
            await self._session.execute(
                update(WatchlistItem)
                .where(
                    WatchlistItem.user_id == user_id,
                    WatchlistItem.position > position,
                )
                .values(position=WatchlistItem.position - 1)
            )
        await self._session.flush()
        return await self.list(user_id)

    async def move_to_top(self, user_id: UUID, symbol: str) -> list[WatchlistRecord]:
        await self._lock_user(user_id)
        item = await self._session.scalar(
            select(WatchlistItem).where(
                WatchlistItem.user_id == user_id, WatchlistItem.symbol == symbol
            )
        )
        if item is None or item.position == 0:
            return await self.list(user_id)
        previous_position = item.position
        await self._session.execute(
            update(WatchlistItem)
            .where(
                WatchlistItem.user_id == user_id,
                WatchlistItem.position < previous_position,
            )
            .values(position=WatchlistItem.position + 1)
        )
        item.position = 0
        await self._session.flush()
        return await self.list(user_id)

    async def clear(self, user_id: UUID) -> int:
        await self._lock_user(user_id)
        result = await self._session.execute(
            delete(WatchlistItem).where(WatchlistItem.user_id == user_id)
        )
        return int(result.rowcount or 0)

    async def _lock_user(self, user_id: UUID) -> None:
        """Serialize ordering mutations for one user without blocking other users."""
        await self._session.execute(
            select(User.id).where(User.id == user_id).with_for_update()
        )

    @staticmethod
    def _record(item: WatchlistItem) -> WatchlistRecord:
        return WatchlistRecord(
            symbol=item.symbol,
            asset_type=item.asset_type,
            note=item.note,
            position=item.position,
            added_at=item.added_at,
        )
