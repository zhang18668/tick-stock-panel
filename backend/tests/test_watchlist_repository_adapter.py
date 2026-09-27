from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from app.persistence.repositories.watchlists import WatchlistRecord
from app.services.watchlist_repository import UserWatchlistRepository


@pytest.mark.asyncio
async def test_user_adapter_always_scopes_queries_to_authenticated_user() -> None:
    user_id = uuid.uuid4()
    record = WatchlistRecord(
        symbol="600000.SH",
        asset_type="stock",
        note="bank",
        position=0,
        added_at=datetime.now(UTC),
    )
    inner = AsyncMock()
    inner.list.return_value = [record]
    inner.add.return_value = [record]
    inner.remove.return_value = []
    inner.move_to_top.return_value = [record]
    inner.clear.return_value = 1
    repository = UserWatchlistRepository(inner, user_id)

    assert (await repository.list())[0]["symbol"] == "600000.SH"
    await repository.add("600000.SH", "bank")
    await repository.remove("600000.SH")
    await repository.move_to_top("600000.SH")
    assert await repository.clear() == 1

    inner.list.assert_awaited_once_with(user_id)
    inner.add.assert_awaited_once_with(user_id, "600000.SH", "bank")
    inner.remove.assert_awaited_once_with(user_id, "600000.SH")
    inner.move_to_top.assert_awaited_once_with(user_id, "600000.SH")
    inner.clear.assert_awaited_once_with(user_id)


@pytest.mark.asyncio
async def test_two_adapters_cannot_substitute_each_others_user_id() -> None:
    user_a = uuid.uuid4()
    user_b = uuid.uuid4()
    inner = AsyncMock()
    inner.list.return_value = []

    await UserWatchlistRepository(inner, user_a).list()
    await UserWatchlistRepository(inner, user_b).list()

    assert [call.args[0] for call in inner.list.await_args_list] == [user_a, user_b]
