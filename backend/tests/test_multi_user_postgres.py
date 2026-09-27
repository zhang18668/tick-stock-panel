from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.persistence.models import UserSetting
from app.persistence.repositories.backtests import PostgresBacktestRepository
from app.persistence.repositories.billing import PostgresBillingRepository
from app.persistence.repositories.monitoring import PostgresMonitoringRepository
from app.persistence.repositories.strategies import PostgresStrategyRepository
from app.persistence.repositories.user_settings import PostgresUserSettingsRepository
from app.persistence.repositories.watchlists import PostgresWatchlistRepository
from app.user_system.service import (
    authenticate_user,
    create_session,
    register_user,
    resolve_session,
    revoke_session,
)

pytestmark = pytest.mark.asyncio


@pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL is not set")
async def test_watchlists_are_isolated_by_user_in_postgresql() -> None:
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    async with engine.connect() as connection:
        transaction = await connection.begin()
        session = AsyncSession(bind=connection, expire_on_commit=False)
        try:
            suffix = uuid.uuid4().hex
            user_a = await register_user(
                session,
                email=f"a-{suffix}@example.com",
                password="password-for-user-a",
            )
            user_b = await register_user(
                session,
                email=f"b-{suffix}@example.com",
                password="password-for-user-b",
            )
            authenticated = await authenticate_user(
                session,
                email=user_a.email.upper(),
                password="password-for-user-a",
            )
            assert authenticated is not None
            token, session_record = await create_session(
                session,
                user=user_a,
                ip="127.0.0.1",
                user_agent="pytest",
            )
            current_user = await resolve_session(session, token)
            assert current_user is not None
            assert current_user.id == user_a.id
            repository = PostgresWatchlistRepository(session)

            await repository.add(user_a.id, "600000.SH", "user-a-note")
            await repository.add(user_b.id, "600000.SH", "user-b-note")
            await repository.add(user_b.id, "000001.SZ", "second-symbol")

            list_a = await repository.list(user_a.id)
            list_b = await repository.list(user_b.id)

            assert [(item.symbol, item.note) for item in list_a] == [
                ("600000.SH", "user-a-note")
            ]
            assert [(item.symbol, item.note) for item in list_b] == [
                ("000001.SZ", "second-symbol"),
                ("600000.SH", "user-b-note"),
            ]

            await repository.clear(user_a.id)
            assert await repository.list(user_a.id) == []
            assert len(await repository.list(user_b.id)) == 2

            strategies = PostgresStrategyRepository(session)
            strategy_id_a = f"custom_{suffix[:12]}_a"
            strategy_id_b = f"custom_{suffix[:12]}_b"
            await strategies.save(
                user_a.id,
                strategy_id_a,
                "custom",
                "META = {}",
                {"id": strategy_id_a},
            )
            await strategies.save(
                user_b.id,
                strategy_id_b,
                "custom",
                "META = {}",
                {"id": strategy_id_b},
            )
            assert await strategies.owned_ids(user_a.id) == frozenset({strategy_id_a})
            assert await strategies.get(user_a.id, strategy_id_b) is None
            assert await strategies.get(user_b.id, strategy_id_a) is None
            assert await strategies.delete(user_a.id, strategy_id_a) is True
            assert await strategies.owned_ids(user_a.id) == frozenset()
            assert await strategies.owned_ids(user_b.id) == frozenset({strategy_id_b})

            await strategies.save_config(
                user_a.id, "builtin_shared", {"params": {"window": 5}}
            )
            await strategies.save_config(
                user_b.id, "builtin_shared", {"params": {"window": 20}}
            )
            assert (await strategies.list_configs(user_a.id))["builtin_shared"] == {
                "params": {"window": 5}
            }
            assert (await strategies.list_configs(user_b.id))["builtin_shared"] == {
                "params": {"window": 20}
            }
            await strategies.delete_config(user_a.id, "builtin_shared")
            assert "builtin_shared" not in await strategies.list_configs(user_a.id)
            assert "builtin_shared" in await strategies.list_configs(user_b.id)

            monitoring = PostgresMonitoringRepository(session)
            rule_a = f"rule_{suffix[:12]}_a"
            rule_b = f"rule_{suffix[:12]}_b"
            await monitoring.save_rule(user_a.id, {"id": rule_a, "enabled": True})
            await monitoring.save_rule(user_b.id, {"id": rule_b, "enabled": True})
            assert [rule["id"] for rule in await monitoring.list_rules(user_a.id)] == [rule_a]
            assert [rule["id"] for rule in await monitoring.list_rules(user_b.id)] == [rule_b]

            await monitoring.append_alerts(
                user_a.id,
                [{"ts": 1001, "rule_id": rule_a, "source": "price", "type": "warn"}],
            )
            await monitoring.append_alerts(
                user_b.id,
                [{"ts": 1002, "rule_id": rule_b, "source": "price", "type": "warn"}],
            )
            assert [event["ts"] for event in await monitoring.list_alerts(user_a.id)] == [1001]
            assert [event["ts"] for event in await monitoring.list_alerts(user_b.id)] == [1002]
            assert await monitoring.clear_alerts(user_a.id) == 1
            assert await monitoring.count_alerts(user_a.id) == 0
            assert await monitoring.count_alerts(user_b.id) == 1

            backtests = PostgresBacktestRepository(session)
            await backtests.save(
                user_a.id,
                f"run-{suffix[:12]}",
                "strategy",
                {"strategy_id": strategy_id_a},
                {"run_id": f"run-{suffix[:12]}", "stats": {"return": 0.1}},
                strategy_id=strategy_id_a,
            )
            assert len(await backtests.list(user_a.id)) == 1
            assert await backtests.list(user_b.id) == []
            assert await backtests.get(user_b.id, f"run-{suffix[:12]}") is None

            billing = PostgresBillingRepository(session)
            plans = await billing.list_plans()
            assert {plan["code"] for plan in plans} >= {"trial", "pro_monthly", "pro_yearly"}
            prices = {plan["code"]: plan["price_cents"] for plan in plans}
            assert prices["pro_monthly"] == 19900
            assert prices["pro_yearly"] == 199900
            now = datetime.now(UTC)
            trial = await billing.subscription(user_b.id)
            assert trial is not None and trial["plan"]["code"] == "trial"
            trial_end = datetime.fromisoformat(trial["current_period_end"])
            assert timedelta(hours=23, minutes=59) < trial_end - now < timedelta(days=1, minutes=1)
            assert await billing.effective_entitlements(user_b.id, trial_end + timedelta(seconds=1)) == {}
            assigned = await billing.assign(
                user_a.id, "pro_monthly", now, now + timedelta(days=30)
            )
            assert assigned["plan"]["code"] == "pro_monthly"
            assert (await billing.effective_entitlements(user_a.id, now))["max_strategies"] == 100
            assert (await billing.effective_entitlements(user_b.id, now))["max_strategies"] == 3

            order = await billing.create_order(
                user_b.id, "pro_yearly", "alipay", now + timedelta(minutes=15)
            )
            assert order.amount_cents == 199900
            assert await billing.fulfill_order(
                order.out_trade_no, "alipay", 199900, f"trade-{suffix}", now
            )
            assert not await billing.fulfill_order(
                order.out_trade_no, "alipay", 199900, f"trade-{suffix}", now
            )
            assert (await billing.subscription(user_b.id))["plan"]["code"] == "pro_yearly"

            user_settings = PostgresUserSettingsRepository(session)
            await user_settings.apply(
                user_a.id, {"nav_hidden": ["data"]}, {"ai_api_key": "secret-a"}, set()
            )
            await user_settings.apply(
                user_b.id, {"nav_hidden": ["review"]}, {"ai_api_key": "secret-b"}, set()
            )
            prefs_a, secrets_a = await user_settings.load(user_a.id)
            prefs_b, secrets_b = await user_settings.load(user_b.id)
            assert prefs_a["nav_hidden"] == ["data"]
            assert prefs_b["nav_hidden"] == ["review"]
            assert secrets_a["ai_api_key"] == "secret-a"
            assert secrets_b["ai_api_key"] == "secret-b"
            stored_settings = await session.get(UserSetting, user_a.id)
            assert stored_settings is not None
            assert "secret-a" not in (stored_settings.secrets_encrypted or "")

            await revoke_session(session, session_record.id)
            assert await resolve_session(session, token) is None
        finally:
            await session.close()
            await transaction.rollback()
    await engine.dispose()
