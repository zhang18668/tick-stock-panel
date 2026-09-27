"""User-scoped backtest result persistence."""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.persistence.models import UserBacktestRun


class PostgresBacktestRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(
        self,
        user_id: UUID,
        run_id: str,
        run_type: str,
        request_data: dict,
        result_data: dict,
        strategy_id: str | None = None,
        status: str = "completed",
    ) -> None:
        item = await self._session.scalar(
            select(UserBacktestRun).where(
                UserBacktestRun.user_id == user_id,
                UserBacktestRun.run_id == run_id,
            )
        )
        if item is None:
            self._session.add(
                UserBacktestRun(
                    user_id=user_id,
                    run_id=run_id,
                    run_type=run_type,
                    strategy_id=strategy_id,
                    status=status,
                    request_data=request_data,
                    result_data=result_data,
                )
            )
        else:
            item.status = status
            item.result_data = result_data
        await self._session.flush()

    async def list(self, user_id: UUID, limit: int = 100) -> list[dict]:
        result = await self._session.scalars(
            select(UserBacktestRun)
            .where(UserBacktestRun.user_id == user_id)
            .order_by(UserBacktestRun.created_at.desc())
            .limit(limit)
        )
        return [self._record(item) for item in result]

    async def get(self, user_id: UUID, run_id: str) -> dict | None:
        item = await self._session.scalar(
            select(UserBacktestRun).where(
                UserBacktestRun.user_id == user_id,
                UserBacktestRun.run_id == run_id,
            )
        )
        return self._record(item) if item is not None else None

    async def delete(self, user_id: UUID, run_id: str) -> bool:
        result = await self._session.execute(
            delete(UserBacktestRun).where(
                UserBacktestRun.user_id == user_id,
                UserBacktestRun.run_id == run_id,
            )
        )
        return bool(result.rowcount)

    @staticmethod
    def _record(item: UserBacktestRun) -> dict:
        return {
            "run_id": item.run_id,
            "run_type": item.run_type,
            "strategy_id": item.strategy_id,
            "status": item.status,
            "request": dict(item.request_data),
            "result": dict(item.result_data),
            "created_at": item.created_at.isoformat(),
        }
