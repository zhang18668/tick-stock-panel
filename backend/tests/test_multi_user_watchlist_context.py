from app.services import watchlist
from app.user_system import settings_context


def test_watchlist_entries_and_groups_are_isolated_by_request_context() -> None:
    user_a = settings_context.activate({}, {})
    try:
        _, group = watchlist.create_group("A组")
        watchlist.add("600000.SH", "A用户", group["id"])
        context_a = settings_context.current()
        assert context_a is not None
        saved_a = dict(context_a.preferences)
    finally:
        settings_context.reset(user_a)

    user_b = settings_context.activate({}, {})
    try:
        assert watchlist.list_symbols() == []
        assert watchlist.list_groups() == []
        watchlist.add("000001.SZ", "B用户")
        assert [row["symbol"] for row in watchlist.list_symbols()] == ["000001.SZ"]
    finally:
        settings_context.reset(user_b)

    restored_a = settings_context.activate(saved_a, {})
    try:
        assert [row["symbol"] for row in watchlist.list_symbols()] == ["600000.SH"]
        assert [group["name"] for group in watchlist.list_groups()] == ["A组"]
    finally:
        settings_context.reset(restored_a)
