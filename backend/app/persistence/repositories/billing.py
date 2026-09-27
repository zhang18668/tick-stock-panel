"""Plans and manually managed subscriptions for the billing MVP."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.persistence.models import BillingPlan, PaymentOrder, User, UserSubscription
from app.persistence.repositories.credits import PostgresCreditRepository


class PostgresBillingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_plans(self) -> list[dict]:
        result = await self._session.scalars(
            select(BillingPlan).where(BillingPlan.active.is_(True)).order_by(BillingPlan.price_cents)
        )
        return [self._plan(item) for item in result]

    async def subscription(self, user_id: UUID) -> dict | None:
        row = await self._session.execute(
            select(UserSubscription, BillingPlan)
            .join(BillingPlan, BillingPlan.id == UserSubscription.plan_id)
            .where(UserSubscription.user_id == user_id)
        )
        item = row.first()
        if item is None:
            return None
        subscription, plan = item
        return {
            "plan": self._plan(plan),
            "status": subscription.status,
            "current_period_start": subscription.current_period_start.isoformat(),
            "current_period_end": (
                subscription.current_period_end.isoformat()
                if subscription.current_period_end is not None
                else None
            ),
            "provider": subscription.provider,
        }

    async def effective_entitlements(self, user_id: UUID, now: datetime) -> dict:
        subscription = await self.subscription(user_id)
        if subscription is not None:
            end = subscription["current_period_end"]
            if (
                subscription["status"] == "active"
                and (end is None or datetime.fromisoformat(end) > now)
            ):
                return dict(subscription["plan"]["entitlements"])
        return {}

    async def assign(
        self,
        user_id: UUID,
        plan_code: str,
        starts_at: datetime,
        ends_at: datetime | None,
        provider: str = "manual",
    ) -> dict:
        plan = await self._session.scalar(select(BillingPlan).where(BillingPlan.code == plan_code))
        if plan is None or not plan.active:
            raise ValueError("unknown billing plan")
        item = await self._session.scalar(
            select(UserSubscription).where(UserSubscription.user_id == user_id)
        )
        if item is None:
            item = UserSubscription(
                user_id=user_id,
                plan_id=plan.id,
                current_period_start=starts_at,
                current_period_end=ends_at,
                status="active",
                provider=provider,
            )
            self._session.add(item)
        else:
            item.plan_id = plan.id
            item.current_period_start = starts_at
            item.current_period_end = ends_at
            item.status = "active"
            item.provider = provider
        await self._session.flush()
        return (await self.subscription(user_id)) or {}

    async def create_order(
        self, user_id: UUID, plan_code: str, provider: str, expires_at: datetime
    ) -> PaymentOrder:
        plan = await self._session.scalar(select(BillingPlan).where(BillingPlan.code == plan_code))
        if plan is None or not plan.active or plan.code not in {"pro_monthly", "pro_yearly"}:
            raise ValueError("unknown purchasable plan")
        order = PaymentOrder(
            user_id=user_id,
            plan_id=plan.id,
            provider=provider,
            out_trade_no=f"CF{datetime.now().strftime('%Y%m%d%H%M%S')}{uuid.uuid4().hex[:16]}",
            amount_cents=plan.price_cents,
            status="pending",
            expires_at=expires_at,
        )
        self._session.add(order)
        await self._session.flush()
        return order

    async def set_order_code_url(self, order: PaymentOrder, code_url: str) -> None:
        order.code_url = code_url
        await self._session.flush()

    async def order(self, user_id: UUID, order_id: UUID) -> dict | None:
        row = await self._session.execute(
            select(PaymentOrder, BillingPlan)
            .join(BillingPlan, BillingPlan.id == PaymentOrder.plan_id)
            .where(PaymentOrder.id == order_id, PaymentOrder.user_id == user_id)
        )
        item = row.first()
        if item is None:
            return None
        order, plan = item
        return {
            "id": str(order.id), "out_trade_no": order.out_trade_no,
            "provider": order.provider, "status": order.status,
            "amount_cents": order.amount_cents, "code_url": order.code_url,
            "expires_at": order.expires_at.isoformat(), "plan": self._plan(plan),
        }

    async def fulfill_order(
        self, out_trade_no: str, provider: str, amount_cents: int,
        provider_trade_no: str, paid_at: datetime,
    ) -> bool:
        row = await self._session.execute(
            select(PaymentOrder, BillingPlan)
            .join(BillingPlan, BillingPlan.id == PaymentOrder.plan_id)
            .where(PaymentOrder.out_trade_no == out_trade_no)
            .with_for_update()
        )
        item = row.first()
        if item is None:
            raise ValueError("unknown payment order")
        order, plan = item
        if order.provider != provider or order.amount_cents != amount_cents:
            raise ValueError("payment order does not match callback")
        if order.status == "paid":
            return False
        if order.status != "pending":
            raise ValueError("payment order is not payable")
        order.status = "paid"
        order.provider_trade_no = provider_trade_no
        order.paid_at = paid_at
        buyer = await self._session.get(User, order.user_id)
        if buyer is not None and buyer.referred_by_user_id is not None:
            await PostgresCreditRepository(self._session).add(
                buyer.referred_by_user_id,
                amount_cents // 2,
                "referral_reward",
                f"referral-payment:{order.id}",
                f"推荐用户订购 {plan.name} 奖励",
            )
        subscription = await self._session.scalar(
            select(UserSubscription).where(UserSubscription.user_id == order.user_id).with_for_update()
        )
        start = paid_at
        if subscription is not None and subscription.current_period_end and subscription.current_period_end > start:
            start = subscription.current_period_end
        period = timedelta(days=365 if plan.billing_period == "year" else 30)
        if subscription is None:
            subscription = UserSubscription(
                user_id=order.user_id, plan_id=plan.id, status="active",
                current_period_start=paid_at, current_period_end=start + period,
                provider=provider, provider_subscription_id=provider_trade_no,
            )
            self._session.add(subscription)
        else:
            subscription.plan_id = plan.id
            subscription.status = "active"
            subscription.current_period_start = paid_at
            subscription.current_period_end = start + period
            subscription.provider = provider
            subscription.provider_subscription_id = provider_trade_no
        await self._session.flush()
        return True

    async def purchase_with_credits(self, user_id: UUID, plan_code: str, now: datetime) -> dict:
        plan = await self._session.scalar(select(BillingPlan).where(BillingPlan.code == plan_code))
        if plan is None or not plan.active or plan.code not in {"pro_monthly", "pro_yearly"}:
            raise ValueError("unknown purchasable plan")
        purchase_key = f"credit-purchase:{uuid.uuid4()}"
        await PostgresCreditRepository(self._session).spend(
            user_id, plan.price_cents, purchase_key, f"积分购买 {plan.name}"
        )
        subscription = await self._session.scalar(
            select(UserSubscription).where(UserSubscription.user_id == user_id).with_for_update()
        )
        start = now
        if subscription is not None and subscription.current_period_end and subscription.current_period_end > start:
            start = subscription.current_period_end
        period = timedelta(days=365 if plan.billing_period == "year" else 30)
        if subscription is None:
            subscription = UserSubscription(
                user_id=user_id, plan_id=plan.id, status="active", current_period_start=now,
                current_period_end=start + period, provider="credits",
                provider_subscription_id=purchase_key,
            )
            self._session.add(subscription)
        else:
            subscription.plan_id = plan.id
            subscription.status = "active"
            subscription.current_period_start = now
            subscription.current_period_end = start + period
            subscription.provider = "credits"
            subscription.provider_subscription_id = purchase_key
        await self._session.flush()
        return (await self.subscription(user_id)) or {}

    @staticmethod
    def _plan(plan: BillingPlan) -> dict:
        return {
            "code": plan.code,
            "name": plan.name,
            "price_cents": plan.price_cents,
            "billing_period": plan.billing_period,
            "entitlements": dict(plan.entitlements),
        }
