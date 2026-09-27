"""Transactional strategy marketplace ownership and installation state."""
from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.persistence.models import (
    StrategyListing,
    UserStrategyInstallation,
    UserStrategyPurchase,
)


class PostgresStrategyMarketplaceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_published(self) -> list[StrategyListing]:
        rows = await self._session.scalars(
            select(StrategyListing)
            .where(StrategyListing.status == "published")
            .order_by(StrategyListing.published_at.desc())
        )
        return list(rows)

    async def get(self, strategy_id: str, *, lock: bool = False) -> StrategyListing | None:
        query = select(StrategyListing).where(StrategyListing.strategy_id == strategy_id)
        if lock:
            query = query.with_for_update()
        return await self._session.scalar(query)

    async def publish(
        self, strategy_id: str, title: str, description: str,
        points_price: int, sale_points_price: int | None = None,
        sale_label: str | None = None,
    ) -> StrategyListing:
        item = await self.get(strategy_id, lock=True)
        if item is None:
            item = StrategyListing(strategy_id=strategy_id, title=title)
            self._session.add(item)
        item.title = title
        item.description = description
        item.points_price = points_price
        item.sale_points_price = sale_points_price
        item.sale_label = sale_label
        item.status = "published"
        item.published_at = item.published_at or datetime.now(UTC)
        await self._session.flush()
        return item

    async def purchased_ids(self, user_id: UUID) -> frozenset[str]:
        rows = await self._session.scalars(
            select(UserStrategyPurchase.strategy_id).where(UserStrategyPurchase.user_id == user_id)
        )
        return frozenset(rows)

    async def installed_ids(self, user_id: UUID) -> frozenset[str]:
        rows = await self._session.scalars(
            select(UserStrategyInstallation.strategy_id).where(UserStrategyInstallation.user_id == user_id)
        )
        return frozenset(rows)

    async def record_purchase(
        self, user_id: UUID, strategy_id: str, amount: int,
    ) -> bool:
        existing = await self._session.scalar(
            select(UserStrategyPurchase.id).where(
                UserStrategyPurchase.user_id == user_id,
                UserStrategyPurchase.strategy_id == strategy_id,
            )
        )
        if existing is not None:
            return False
        self._session.add(UserStrategyPurchase(
            user_id=user_id, strategy_id=strategy_id,
            amount=amount,
        ))
        await self._session.flush()
        return True

    async def install(self, user_id: UUID, strategy_id: str) -> bool:
        existing = await self._session.get(UserStrategyInstallation, (user_id, strategy_id))
        if existing is not None:
            return False
        self._session.add(UserStrategyInstallation(user_id=user_id, strategy_id=strategy_id))
        await self._session.flush()
        return True

    async def uninstall(self, user_id: UUID, strategy_id: str) -> bool:
        result = await self._session.execute(delete(UserStrategyInstallation).where(
            UserStrategyInstallation.user_id == user_id,
            UserStrategyInstallation.strategy_id == strategy_id,
        ))
        return bool(result.rowcount)
