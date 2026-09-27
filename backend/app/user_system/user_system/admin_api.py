"""Minimal user administration for the multi-user operating MVP."""
from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import Date, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.persistence.database import get_session
from app.persistence.models import (
    BillingPlan,
    CreditRedemptionCode,
    RegistrationCode,
    User,
    UserBacktestRun,
    UserPageUsage,
    UserStrategy,
    UserSubscription,
)
from app.user_system.context import CurrentUser
from app.user_system.dependencies import require_admin

router = APIRouter(prefix="/api/admin", tags=["admin"])

DatabaseSession = Annotated[AsyncSession, Depends(get_session)]
AdminUser = Annotated[CurrentUser, Depends(require_admin)]


class UpdateUserRequest(BaseModel):
    status: Literal["active", "disabled"] | None = None
    role: Literal["user", "admin"] | None = None


class CreateRegistrationCodesRequest(BaseModel):
    count: int = 1
    plan_code: str = "pro_monthly"
    valid_days: int = 30
    expires_in_days: int | None = 30


class CreateCreditCodesRequest(BaseModel):
    count: int = 1
    points: int = 100
    expires_in_days: int | None = 30


@router.get("/credit-codes")
async def list_credit_codes(session: DatabaseSession, _: AdminUser) -> dict:
    rows = await session.execute(
        select(CreditRedemptionCode, User)
        .outerjoin(User, User.id == CreditRedemptionCode.redeemed_by_user_id)
        .order_by(CreditRedemptionCode.created_at.desc()).limit(500)
    )
    return {"codes": [{
        "id": str(item.id), "code_prefix": item.code_prefix, "status": item.status,
        "points": item.amount_cents // 100,
        "expires_at": item.expires_at.isoformat() if item.expires_at else None,
        "redeemed_at": item.redeemed_at.isoformat() if item.redeemed_at else None,
        "redeemed_by": user.email if user else None, "created_at": item.created_at.isoformat(),
    } for item, user in rows.all()]}


@router.post("/credit-codes", status_code=201)
async def create_credit_codes(
    payload: CreateCreditCodesRequest, session: DatabaseSession, admin: AdminUser,
) -> dict:
    if not 1 <= payload.count <= 100:
        raise HTTPException(status_code=422, detail="count must be between 1 and 100")
    if not 1 <= payload.points <= 1_000_000:
        raise HTTPException(status_code=422, detail="points must be between 1 and 1000000")
    if payload.expires_in_days is not None and not 1 <= payload.expires_in_days <= 3650:
        raise HTTPException(status_code=422, detail="expires_in_days must be between 1 and 3650")
    now = datetime.now(UTC)
    expires_at = now + timedelta(days=payload.expires_in_days) if payload.expires_in_days else None
    plain_codes = []
    for _ in range(payload.count):
        code = f"JF-{secrets.token_hex(4).upper()}-{secrets.token_hex(4).upper()}"
        plain_codes.append(code)
        session.add(CreditRedemptionCode(
            code_hash=hashlib.sha256(code.encode()).hexdigest(), code_prefix=code[:14],
            amount_cents=payload.points * 100, status="active", expires_at=expires_at,
            created_by_user_id=admin.id,
        ))
    await session.flush()
    return {"codes": plain_codes, "points": payload.points, "expires_at": expires_at.isoformat() if expires_at else None}


@router.delete("/credit-codes/{code_id}")
async def revoke_credit_code(code_id: UUID, session: DatabaseSession, _: AdminUser) -> dict:
    item = await session.get(CreditRedemptionCode, code_id)
    if item is None:
        raise HTTPException(status_code=404, detail="credit code not found")
    if item.status == "redeemed":
        raise HTTPException(status_code=409, detail="redeemed credit code cannot be revoked")
    item.status = "revoked"
    await session.flush()
    return {"ok": True}


@router.get("/registration-codes")
async def list_registration_codes(session: DatabaseSession, _: AdminUser) -> dict:
    rows = await session.execute(
        select(RegistrationCode, BillingPlan, User)
        .join(BillingPlan, BillingPlan.id == RegistrationCode.plan_id)
        .outerjoin(User, User.id == RegistrationCode.redeemed_by_user_id)
        .order_by(RegistrationCode.created_at.desc()).limit(500)
    )
    return {"codes": [{
        "id": str(item.id), "code_prefix": item.code_prefix, "status": item.status,
        "plan_code": plan.code, "plan_name": plan.name, "valid_days": item.valid_days,
        "expires_at": item.expires_at.isoformat() if item.expires_at else None,
        "redeemed_at": item.redeemed_at.isoformat() if item.redeemed_at else None,
        "redeemed_by": user.email if user else None, "created_at": item.created_at.isoformat(),
    } for item, plan, user in rows.all()]}


@router.post("/registration-codes", status_code=201)
async def create_registration_codes(
    payload: CreateRegistrationCodesRequest, session: DatabaseSession, admin: AdminUser,
) -> dict:
    if not 1 <= payload.count <= 100:
        raise HTTPException(status_code=422, detail="count must be between 1 and 100")
    if not 1 <= payload.valid_days <= 3650:
        raise HTTPException(status_code=422, detail="valid_days must be between 1 and 3650")
    if payload.expires_in_days is not None and not 1 <= payload.expires_in_days <= 3650:
        raise HTTPException(status_code=422, detail="expires_in_days must be between 1 and 3650")
    plan = await session.scalar(select(BillingPlan).where(BillingPlan.code == payload.plan_code, BillingPlan.active.is_(True)))
    if plan is None:
        raise HTTPException(status_code=404, detail="billing plan not found")
    now = datetime.now(UTC)
    expires_at = now + timedelta(days=payload.expires_in_days) if payload.expires_in_days else None
    plain_codes = []
    for _ in range(payload.count):
        code = f"CF-{secrets.token_hex(4).upper()}-{secrets.token_hex(4).upper()}"
        plain_codes.append(code)
        session.add(RegistrationCode(
            code_hash=hashlib.sha256(code.encode()).hexdigest(), code_prefix=code[:12],
            plan_id=plan.id, valid_days=payload.valid_days, status="active",
            expires_at=expires_at, created_by_user_id=admin.id,
        ))
    await session.flush()
    return {"codes": plain_codes, "plan_code": plan.code, "valid_days": payload.valid_days, "expires_at": expires_at.isoformat() if expires_at else None}


@router.delete("/registration-codes/{code_id}")
async def revoke_registration_code(code_id: UUID, session: DatabaseSession, _: AdminUser) -> dict:
    item = await session.get(RegistrationCode, code_id)
    if item is None:
        raise HTTPException(status_code=404, detail="registration code not found")
    if item.status == "redeemed":
        raise HTTPException(status_code=409, detail="redeemed registration code cannot be revoked")
    item.status = "revoked"
    await session.flush()
    return {"ok": True}


def _return_ratio(result: dict) -> float | None:
    stats = result.get("stats") if isinstance(result.get("stats"), dict) else {}
    for source in (stats, result):
        for key in ("total_return", "return", "return_pct"):
            value = source.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                return float(value)
    return None


def _daily_counts(rows: list[tuple[date, int]], start: date, days: int) -> dict[str, int]:
    values = {str(day): int(count) for day, count in rows}
    return {
        str(start + timedelta(days=offset)): values.get(str(start + timedelta(days=offset)), 0)
        for offset in range(days)
    }


@router.get("/users")
async def list_users(
    session: DatabaseSession,
    _: AdminUser,
    limit: int = 100,
    offset: int = 0,
) -> dict:
    total = await session.scalar(select(func.count()).select_from(User))
    result = await session.execute(
        select(User, UserSubscription, BillingPlan)
        .outerjoin(UserSubscription, UserSubscription.user_id == User.id)
        .outerjoin(BillingPlan, BillingPlan.id == UserSubscription.plan_id)
        .order_by(User.created_at.desc()).offset(max(0, offset)).limit(max(1, min(limit, 500)))
    )
    return {
        "users": [
            {
                "id": str(user.id),
                "email": user.email,
                "display_name": user.display_name,
                "role": user.role,
                "status": user.status,
                "created_at": user.created_at.isoformat(),
                "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
                "subscription": ({
                    "plan_code": plan.code,
                    "plan_name": plan.name,
                    "status": subscription.status,
                    "current_period_end": subscription.current_period_end.isoformat() if subscription.current_period_end else None,
                } if subscription is not None and plan is not None else None),
            }
            for user, subscription, plan in result.all()
        ],
        "total": int(total or 0),
    }


@router.patch("/users/{user_id}")
async def update_user(
    user_id: UUID,
    payload: UpdateUserRequest,
    session: DatabaseSession,
    admin: AdminUser,
) -> dict:
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")
    if user.id == admin.id and payload.status == "disabled":
        raise HTTPException(status_code=400, detail="cannot disable current administrator")
    if payload.status is not None:
        user.status = payload.status
    if payload.role is not None:
        user.role = payload.role
    await session.flush()
    return {"ok": True, "id": str(user.id), "role": user.role, "status": user.status}


@router.get("/overview")
async def overview(session: DatabaseSession, _: AdminUser) -> dict:
    users = int(await session.scalar(select(func.count()).select_from(User)) or 0)
    strategies = int(await session.scalar(select(func.count()).select_from(UserStrategy)) or 0)
    backtests = int(await session.scalar(select(func.count()).select_from(UserBacktestRun)) or 0)
    page_rows = await session.execute(
        select(UserPageUsage.path, func.sum(UserPageUsage.view_count), func.count(UserPageUsage.user_id))
        .group_by(UserPageUsage.path).order_by(func.sum(UserPageUsage.view_count).desc())
    )
    days = 30
    start = date.today() - timedelta(days=days - 1)

    async def daily(model: type[User] | type[UserStrategy] | type[UserBacktestRun]) -> dict[str, int]:
        day = cast(model.created_at, Date)
        rows = await session.execute(
            select(day, func.count()).where(day >= start).group_by(day).order_by(day)
        )
        return _daily_counts(rows.all(), start, days)

    user_daily = await daily(User)
    strategy_daily = await daily(UserStrategy)
    backtest_daily = await daily(UserBacktestRun)

    strategy_counts = (
        select(UserStrategy.user_id, func.count().label("strategies"))
        .group_by(UserStrategy.user_id).subquery()
    )
    backtest_counts = (
        select(UserBacktestRun.user_id, func.count().label("backtests"))
        .group_by(UserBacktestRun.user_id).subquery()
    )
    activity_rows = await session.execute(
        select(
            User,
            func.coalesce(func.sum(UserPageUsage.view_count), 0).label("page_views"),
            func.max(UserPageUsage.last_viewed_at).label("last_active_at"),
            func.coalesce(strategy_counts.c.strategies, 0),
            func.coalesce(backtest_counts.c.backtests, 0),
        )
        .outerjoin(UserPageUsage, UserPageUsage.user_id == User.id)
        .outerjoin(strategy_counts, strategy_counts.c.user_id == User.id)
        .outerjoin(backtest_counts, backtest_counts.c.user_id == User.id)
        .group_by(User.id, strategy_counts.c.strategies, backtest_counts.c.backtests)
        .order_by(func.coalesce(func.sum(UserPageUsage.view_count), 0).desc(), User.created_at.desc())
        .limit(10)
    )
    top_users = []
    for user, page_views, last_active_at, strategy_count, backtest_count in activity_rows.all():
        top_users.append({
            "id": str(user.id), "email": user.email, "display_name": user.display_name,
            "page_views": int(page_views or 0), "strategies": strategy_count,
            "backtests": backtest_count,
            "last_active_at": last_active_at.isoformat() if last_active_at else None,
        })
    return {
        "counts": {"users": users, "strategies": strategies, "backtests": backtests},
        "timeline": [
            {"date": day, "users": user_daily[day], "strategies": strategy_daily[day], "backtests": backtest_daily[day]}
            for day in user_daily
        ],
        "top_users": top_users,
        "pages": [
            {"path": path, "views": int(views or 0), "users": int(page_users or 0)}
            for path, views, page_users in page_rows.all()
        ],
    }


@router.get("/strategies")
async def all_strategies(session: DatabaseSession, _: AdminUser, limit: int = 500) -> dict:
    rows = await session.execute(
        select(UserStrategy, User).join(User, User.id == UserStrategy.user_id)
        .order_by(UserStrategy.updated_at.desc()).limit(max(1, min(limit, 1000)))
    )
    return {"strategies": [{
        "id": str(item.id), "strategy_id": item.strategy_id, "source": item.source,
        "meta": dict(item.strategy_meta), "owner": {"id": str(user.id), "email": user.email},
        "created_at": item.created_at.isoformat(), "updated_at": item.updated_at.isoformat(),
    } for item, user in rows.all()]}


@router.get("/strategy-ranking")
async def strategy_ranking(session: DatabaseSession, _: AdminUser, limit: int = 100) -> dict:
    rows = await session.execute(
        select(UserBacktestRun, User).join(User, User.id == UserBacktestRun.user_id)
        .where(UserBacktestRun.status == "completed")
        .order_by(UserBacktestRun.created_at.desc()).limit(2000)
    )
    ranking = []
    for run, user in rows.all():
        ratio = _return_ratio(dict(run.result_data))
        if ratio is None or ratio <= 0:
            continue
        ranking.append({
            "run_id": run.run_id, "run_type": run.run_type, "strategy_id": run.strategy_id,
            "return_ratio": ratio, "params": dict(run.request_data),
            "result": dict(run.result_data), "owner": {"id": str(user.id), "email": user.email},
            "created_at": run.created_at.isoformat(),
        })
    ranking.sort(key=lambda item: item["return_ratio"], reverse=True)
    return {"ranking": ranking[:max(1, min(limit, 500))]}
