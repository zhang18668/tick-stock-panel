"""HTTP authentication and per-request tenant context for the user plugin."""
from __future__ import annotations

from datetime import UTC, datetime

from fastapi import Request
from fastapi.responses import JSONResponse

from app.persistence.database import session_scope
from app.persistence.repositories.billing import PostgresBillingRepository
from app.persistence.repositories.strategies import PostgresStrategyRepository
from app.persistence.repositories.strategy_marketplace import (
    PostgresStrategyMarketplaceRepository,
)
from app.persistence.repositories.user_settings import PostgresUserSettingsRepository
from app.user_system import settings_context
from app.user_system.api import COOKIE_NAME
from app.user_system.service import resolve_session

_PUBLIC_PATHS = {
    "/api/account/register",
    "/api/account/login",
    "/api/account/status",
    "/api/auth/mode",
    "/api/health",
    "/api/billing/webhooks/wechat",
    "/api/billing/webhooks/alipay",
}

_PERSONAL_SETTINGS_PATHS = {
    "/api/settings",
    "/api/settings/onboarding/complete",
    "/api/settings/preferences",
    "/api/settings/preferences/watchlist-columns",
    "/api/settings/preferences/nav-order",
    "/api/settings/preferences/nav-hidden",
    "/api/settings/preferences/screener-result-columns",
    "/api/settings/preferences/realtime-quote-scope",
    "/api/settings/preferences/realtime-watchlist",
    "/api/settings/preferences/indices-nav-pinned",
    "/api/settings/preferences/realtime-monitor",
    "/api/settings/preferences/system-notify",
    "/api/settings/preferences/feishu-webhook",
    "/api/settings/preferences/wecom-webhook",
    "/api/settings/preferences/wecom-bot",
    "/api/settings/preferences/wecom-bot-toggle",
    "/api/settings/preferences/webhook-enabled-default",
    "/api/settings/preferences/webhook-default-channels",
    "/api/settings/preferences/review-push",
}


async def handle_request(request: Request, call_next):
    path = request.url.path
    if not path.startswith("/api/") or path in _PUBLIC_PATHS:
        return await call_next(request)
    if path.startswith("/api/auth/"):
        return JSONResponse(status_code=404, content={"detail": "not found"})

    token = request.cookies.get(COOKIE_NAME, "")
    context_token = None
    current_user = None
    async with session_scope() as session:
        current_user = await resolve_session(session, token)
        if current_user is not None:
            request.state.current_user = current_user
            billing = PostgresBillingRepository(session)
            now = datetime.now(UTC)
            request.state.entitlements = await billing.effective_entitlements(
                current_user.id, now
            )
            subscription = await billing.subscription(current_user.id)
            request.state.is_paid_user = bool(
                subscription
                and subscription["plan"]["code"] in {"pro", "pro_monthly", "pro_yearly"}
                and subscription["status"] == "active"
                and (
                    subscription["current_period_end"] is None
                    or datetime.fromisoformat(subscription["current_period_end"]) > now
                )
            )
            subscription_access = (
                path
                in {
                    "/api/account/me",
                    "/api/account/logout",
                    "/api/billing/me",
                    "/api/billing/plans",
                    "/api/billing/orders",
                    "/api/billing/credits",
                    "/api/billing/credits/purchase",
                }
                or path.startswith("/api/billing/orders/")
            )
            if (
                not current_user.is_admin
                and not request.state.entitlements
                and not subscription_access
            ):
                return JSONResponse(
                    status_code=402,
                    content={
                        "detail": "订阅已到期, 请开通专业版后继续使用",
                        "code": "SUBSCRIPTION_EXPIRED",
                    },
                )
            platform_settings = (
                path.startswith("/api/settings") and path not in _PERSONAL_SETTINGS_PATHS
            )
            global_mutation = (
                request.method in {"POST", "PUT", "PATCH", "DELETE"}
                and path.startswith(("/api/ext-data", "/api/custom-signals"))
            )
            uses_platform_context = platform_settings or global_mutation
            if uses_platform_context and not current_user.is_admin:
                return JSONResponse(
                    status_code=403,
                    content={"detail": "administrator access required"},
                )
            strategy_repository = PostgresStrategyRepository(session)
            request.state.owned_strategy_ids = await strategy_repository.owned_ids(
                current_user.id
            )
            marketplace = PostgresStrategyMarketplaceRepository(session)
            request.state.purchased_strategy_ids = await marketplace.purchased_ids(
                current_user.id
            )
            request.state.installed_strategy_ids = await marketplace.installed_ids(
                current_user.id
            )
            request.state.strategy_overrides = await strategy_repository.list_configs(
                current_user.id
            )
            if not uses_platform_context:
                preferences, secrets = await PostgresUserSettingsRepository(session).load(
                    current_user.id
                )
                context_token = settings_context.activate(preferences, secrets)

    if current_user is None:
        return JSONResponse(status_code=401, content={"detail": "not authenticated"})
    try:
        response = await call_next(request)
        if context_token is not None and response.status_code < 400:
            context = settings_context.current()
            if context is not None:
                async with session_scope() as session:
                    await PostgresUserSettingsRepository(session).apply(
                        current_user.id,
                        context.preference_updates,
                        context.secret_updates,
                        context.secret_deletes,
                    )
        return response
    finally:
        if context_token is not None:
            settings_context.reset(context_token)
