"""Public plans, current subscription, and manual admin assignment."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.persistence.database import get_session
from app.persistence.models import CreditRedemptionCode
from app.persistence.repositories.billing import PostgresBillingRepository
from app.persistence.repositories.credits import InsufficientCreditsError, PostgresCreditRepository
from app.user_system import payment_providers, service
from app.user_system.context import CurrentUser
from app.user_system.dependencies import require_admin, require_user

router = APIRouter(prefix="/api/billing", tags=["billing"])

DatabaseSession = Annotated[AsyncSession, Depends(get_session)]
AuthenticatedUser = Annotated[CurrentUser, Depends(require_user)]
AdminUser = Annotated[CurrentUser, Depends(require_admin)]


class AssignSubscriptionRequest(BaseModel):
    user_id: UUID
    plan_code: str = Field(min_length=1, max_length=40)
    days: int | None = Field(default=30, ge=1, le=3650)


class CreatePaymentOrderRequest(BaseModel):
    plan_code: str = Field(pattern="^pro_(monthly|yearly)$")
    provider: str = Field(pattern="^(wechat|alipay)$")


class CreditPurchaseRequest(BaseModel):
    plan_code: str = Field(pattern="^pro_(monthly|yearly)$")


class RedeemRegistrationCodeRequest(BaseModel):
    registration_code: str = Field(min_length=8, max_length=64)


class RedeemCreditCodeRequest(BaseModel):
    code: str = Field(min_length=8, max_length=64)


@router.get("/plans")
async def plans(session: DatabaseSession, _: AuthenticatedUser) -> dict:
    return {
        "plans": await PostgresBillingRepository(session).list_plans(),
        "channels": payment_providers.configured_channels(),
    }


@router.get("/me")
async def my_subscription(session: DatabaseSession, user: AuthenticatedUser) -> dict:
    subscription = await PostgresBillingRepository(session).subscription(user.id)
    now = datetime.now(UTC)
    is_effective = bool(
        subscription
        and subscription["status"] == "active"
        and (
            subscription["current_period_end"] is None
            or datetime.fromisoformat(subscription["current_period_end"]) > now
        )
    )
    return {
        "subscription": subscription,
        "effective_plan": subscription["plan"]["code"] if is_effective else "expired",
        "credits": await PostgresCreditRepository(session).summary(user.id),
    }


@router.get("/credits")
async def my_credits(session: DatabaseSession, user: AuthenticatedUser) -> dict:
    return await PostgresCreditRepository(session).summary(user.id)


@router.post("/credits/redeem")
async def redeem_credit_code(
    payload: RedeemCreditCodeRequest, session: DatabaseSession, user: AuthenticatedUser,
) -> dict:
    import hashlib

    normalized = payload.code.strip().upper()
    item = await session.scalar(
        select(CreditRedemptionCode)
        .where(CreditRedemptionCode.code_hash == hashlib.sha256(normalized.encode()).hexdigest())
        .with_for_update()
    )
    now = datetime.now(UTC)
    if item is None or item.status != "active" or (item.expires_at is not None and item.expires_at <= now):
        raise HTTPException(status_code=422, detail="积分兑换码无效、已使用或已过期")
    added = await PostgresCreditRepository(session).add(
        user.id, item.amount_cents, "redemption_code", f"credit-code:{item.id}", "积分兑换码充值",
    )
    if not added:
        raise HTTPException(status_code=409, detail="该积分兑换码已兑换")
    item.status = "redeemed"
    item.redeemed_by_user_id = user.id
    item.redeemed_at = now
    await session.flush()
    return {"ok": True, "points": item.amount_cents // 100, "credits": await PostgresCreditRepository(session).summary(user.id)}


@router.post("/redeem")
async def redeem_registration_code(
    payload: RedeemRegistrationCodeRequest,
    session: DatabaseSession,
    user: AuthenticatedUser,
) -> dict:
    try:
        subscription = await service.redeem_registration_code(
            session, user_id=user.id, registration_code=payload.registration_code
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"ok": True, "subscription": subscription}


@router.post("/credits/purchase")
async def purchase_with_credits(
    payload: CreditPurchaseRequest, session: DatabaseSession, user: AuthenticatedUser
) -> dict:
    try:
        subscription = await PostgresBillingRepository(session).purchase_with_credits(
            user.id, payload.plan_code, datetime.now(UTC)
        )
    except InsufficientCreditsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"ok": True, "subscription": subscription, "credits": await PostgresCreditRepository(session).summary(user.id)}


@router.post("/admin/assign")
async def assign_subscription(
    payload: AssignSubscriptionRequest,
    session: DatabaseSession,
    _: AdminUser,
) -> dict:
    now = datetime.now(UTC)
    ends_at = now + timedelta(days=payload.days) if payload.days is not None else None
    try:
        subscription = await PostgresBillingRepository(session).assign(
            payload.user_id,
            payload.plan_code,
            now,
            ends_at,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"ok": True, "subscription": subscription}


@router.post("/orders", status_code=201)
async def create_payment_order(
    payload: CreatePaymentOrderRequest,
    session: DatabaseSession,
    user: AuthenticatedUser,
) -> dict:
    repo = PostgresBillingRepository(session)
    try:
        order = await repo.create_order(
            user.id, payload.plan_code, payload.provider, datetime.now(UTC) + timedelta(minutes=15)
        )
        plan = (await repo.order(user.id, order.id))["plan"]
        code_url = await payment_providers.create_qr(
            payload.provider, order.out_trade_no, order.amount_cents, plan["name"]
        )
        await repo.set_order_code_url(order, code_url)
    except payment_providers.PaymentConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return (await repo.order(user.id, order.id)) or {}


@router.get("/orders/{order_id}")
async def payment_order(
    order_id: UUID, session: DatabaseSession, user: AuthenticatedUser
) -> dict:
    order = await PostgresBillingRepository(session).order(user.id, order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="payment order not found")
    return order


@router.post("/webhooks/wechat")
async def wechat_webhook(request: Request, session: DatabaseSession) -> dict:
    body = await request.body()
    try:
        result = payment_providers.parse_wechat_callback(
            body,
            request.headers["Wechatpay-Timestamp"],
            request.headers["Wechatpay-Nonce"],
            request.headers["Wechatpay-Signature"],
        )
        if result.get("trade_state") == "SUCCESS":
            await PostgresBillingRepository(session).fulfill_order(
                result["out_trade_no"], "wechat", int(result["amount"]["total"]),
                result["transaction_id"], datetime.fromisoformat(result["success_time"]),
            )
    except Exception as exc:
        raise HTTPException(status_code=400, detail="invalid WeChat Pay callback") from exc
    return {"code": "SUCCESS", "message": "成功"}


@router.post("/webhooks/alipay")
async def alipay_webhook(request: Request, session: DatabaseSession) -> Response:
    params = {key: str(value) for key, value in (await request.form()).items()}
    try:
        payment_providers.verify_alipay_callback(params)
        if params.get("app_id") != payment_providers.settings.alipay_app_id:
            raise ValueError("app id mismatch")
        if params.get("trade_status") in {"TRADE_SUCCESS", "TRADE_FINISHED"}:
            await PostgresBillingRepository(session).fulfill_order(
                params["out_trade_no"], "alipay", int(Decimal(params["total_amount"]) * 100),
                params["trade_no"], datetime.strptime(params["gmt_payment"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC),
            )
    except Exception:
        return Response(content="failure", media_type="text/plain", status_code=400)
    return Response(content="success", media_type="text/plain")
