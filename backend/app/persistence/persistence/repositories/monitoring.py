"""PostgreSQL persistence for user-scoped monitoring rules and alert events."""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.persistence.models import UserAlertEvent, UserMonitorRule, UserStrategyConfig
from app.persistence.repositories.user_settings import PostgresUserSettingsRepository


class PostgresMonitoringRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_rules(self, user_id: UUID) -> list[dict]:
        result = await self._session.scalars(
            select(UserMonitorRule)
            .where(UserMonitorRule.user_id == user_id)
            .order_by(UserMonitorRule.created_at.desc())
        )
        return [dict(item.rule) for item in result]

    async def list_all_rules(self) -> list[dict]:
        result = await self._session.scalars(
            select(UserMonitorRule).order_by(UserMonitorRule.created_at.desc())
        )
        rules = list(result)
        configs_result = await self._session.scalars(select(UserStrategyConfig))
        configs = {
            (item.user_id, item.strategy_id): dict(item.overrides)
            for item in configs_result
        }
        enriched: list[dict] = []
        settings_repo = PostgresUserSettingsRepository(self._session)
        notification_configs: dict[UUID, dict] = {}
        for item in rules:
            rule = dict(item.rule)
            if item.user_id not in notification_configs:
                preferences, secrets = await settings_repo.load(item.user_id)
                notification_configs[item.user_id] = {
                    "system_notify_enabled": bool(preferences.get("system_notify_enabled", False)),
                    "feishu_webhook_url": secrets.get("feishu_webhook_url", ""),
                    "feishu_webhook_secret": secrets.get("feishu_webhook_secret", ""),
                    "wecom_webhook_url": secrets.get("wecom_webhook_url", ""),
                }
            rule["_notification_config"] = notification_configs[item.user_id]
            strategy_id = rule.get("strategy_id")
            if strategy_id:
                rule["_strategy_overrides"] = configs.get(
                    (item.user_id, str(strategy_id)), {}
                )
            enriched.append(rule)
        return enriched

    async def save_rule(self, user_id: UUID, rule: dict) -> None:
        rule_id = str(rule["id"])
        item = await self._session.scalar(
            select(UserMonitorRule).where(
                UserMonitorRule.user_id == user_id,
                UserMonitorRule.rule_id == rule_id,
            )
        )
        stored = {**rule, "user_id": str(user_id)}
        if item is None:
            self._session.add(
                UserMonitorRule(
                    user_id=user_id,
                    rule_id=rule_id,
                    rule=stored,
                    enabled=bool(rule.get("enabled", True)),
                )
            )
        else:
            item.rule = stored
            item.enabled = bool(rule.get("enabled", True))
        await self._session.flush()

    async def delete_rule(self, user_id: UUID, rule_id: str) -> bool:
        result = await self._session.execute(
            delete(UserMonitorRule).where(
                UserMonitorRule.user_id == user_id,
                UserMonitorRule.rule_id == rule_id,
            )
        )
        return bool(result.rowcount)

    async def append_alerts(self, user_id: UUID, events: list[dict]) -> None:
        self._session.add_all(
            UserAlertEvent(
                user_id=user_id,
                event_ts=int(event["ts"]),
                source=str(event.get("source") or ""),
                event_type=str(event.get("type") or ""),
                rule_id=str(event["rule_id"]) if event.get("rule_id") else None,
                event={**event, "user_id": str(user_id)},
            )
            for event in events
        )
        await self._session.flush()

    async def list_alerts(
        self,
        user_id: UUID,
        limit: int = 5000,
        since_ts: int | None = None,
        source: str | None = None,
        event_type: str | None = None,
    ) -> list[dict]:
        query = select(UserAlertEvent).where(UserAlertEvent.user_id == user_id)
        if since_ts is not None:
            query = query.where(UserAlertEvent.event_ts >= since_ts)
        if source:
            query = query.where(UserAlertEvent.source == source)
        if event_type:
            query = query.where(UserAlertEvent.event_type == event_type)
        result = await self._session.scalars(
            query.order_by(UserAlertEvent.event_ts.desc()).limit(limit)
        )
        return [dict(item.event) for item in result]

    async def delete_alert(self, user_id: UUID, event_ts: int) -> bool:
        event_id = await self._session.scalar(
            select(UserAlertEvent.id)
            .where(
                UserAlertEvent.user_id == user_id,
                UserAlertEvent.event_ts == event_ts,
            )
            .limit(1)
        )
        if event_id is None:
            return False
        await self._session.execute(delete(UserAlertEvent).where(UserAlertEvent.id == event_id))
        return True

    async def clear_alerts(self, user_id: UUID) -> int:
        result = await self._session.execute(
            delete(UserAlertEvent).where(UserAlertEvent.user_id == user_id)
        )
        return int(result.rowcount or 0)

    async def count_alerts(self, user_id: UUID) -> int:
        value = await self._session.scalar(
            select(func.count()).select_from(UserAlertEvent).where(
                UserAlertEvent.user_id == user_id
            )
        )
        return int(value or 0)
