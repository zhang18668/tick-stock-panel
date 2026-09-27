"""Runtime-selected persistence for private watchlist membership."""
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated, Protocol
from uuid import UUID

import anyio
from fastapi import Depends, Request

from app.persistence.repositories.watchlists import PostgresWatchlistRepository, WatchlistRecord


class WatchlistRepository(Protocol):
    async def list(self) -> list[dict]: ...
    async def add(self, symbol: str, note: str = "") -> list[dict]: ...
    async def remove(self, symbol: str) -> list[dict]: ...
    async def move_to_top(self, symbol: str) -> list[dict]: ...
    async def clear(self) -> int: ...


class FileWatchlistRepository:
    """Compatibility adapter for existing standalone Parquet storage."""

    async def list(self) -> list[dict]:
        from app.services import watchlist

        return await anyio.to_thread.run_sync(watchlist.list_symbols)

    async def add(self, symbol: str, note: str = "") -> list[dict]:
        from app.services import watchlist

        return await anyio.to_thread.run_sync(watchlist.add, symbol, note)

    async def remove(self, symbol: str) -> list[dict]:
        from app.services import watchlist

        return await anyio.to_thread.run_sync(watchlist.remove, symbol)

    async def move_to_top(self, symbol: str) -> list[dict]:
        from app.services import watchlist

        return await anyio.to_thread.run_sync(watchlist.move_to_top, symbol)

    async def clear(self) -> int:
        from app.services import watchlist

        return await anyio.to_thread.run_sync(watchlist.clear)


class UserWatchlistRepository:
    def __init__(self, repository: PostgresWatchlistRepository, user_id: UUID) -> None:
        self._repository = repository
        self._user_id = user_id

    async def list(self) -> list[dict]:
        return self._dicts(await self._repository.list(self._user_id))

    async def add(self, symbol: str, note: str = "") -> list[dict]:
        return self._dicts(await self._repository.add(self._user_id, symbol, note))

    async def remove(self, symbol: str) -> list[dict]:
        return self._dicts(await self._repository.remove(self._user_id, symbol))

    async def move_to_top(self, symbol: str) -> list[dict]:
        return self._dicts(await self._repository.move_to_top(self._user_id, symbol))

    async def clear(self) -> int:
        return await self._repository.clear(self._user_id)

    @staticmethod
    def _dicts(items: list[WatchlistRecord]) -> list[dict]:
        return [
            {
                "symbol": item.symbol,
                "added_at": item.added_at.isoformat(),
                "note": item.note,
                "asset_type": item.asset_type,
            }
            for item in items
        ]


async def get_watchlist_repository(request: Request) -> AsyncIterator[WatchlistRepository]:
    # The file adapter delegates to app.services.watchlist. In multi-user mode
    # that service reads/writes the request's PostgreSQL-backed settings context,
    # preserving the richer groups/M:N contract without touching global files.
    yield FileWatchlistRepository()


WatchlistStore = Annotated[WatchlistRepository, Depends(get_watchlist_repository)]
