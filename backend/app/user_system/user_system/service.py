"""Identity service for PostgreSQL multi-user mode."""
from __future__ import annotations

import hashlib
import re
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.persistence.models import (
    BillingPlan,
    RegistrationCode,
    User,
    UserSession,
    UserSubscription,
)
from app.persistence.repositories.credits import PostgresCreditRepository
from app.user_system.context import CurrentUser
from app.user_system.security import (
    hash_password,
    hash_session_token,
    new_session_token,
    verify_password,
)

SESSION_TTL = timedelta(days=30)
_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


class EmailAlreadyRegisteredError(ValueError):
    pass


def normalize_email(email: str) -> str:
    normalized = email.strip().casefold()
    if len(normalized) > 320 or not _EMAIL_RE.fullmatch(normalized):
        raise ValueError("invalid email address")
    return normalized


async def register_user(
    session: AsyncSession,
    *,
    email: str,
    password: str,
    display_name: str = "",
    referral_code: str | None = None,
    registration_code: str | None = None,
) -> User:
    await session.execute(text("SELECT pg_advisory_xact_lock(1122334455)"))
    normalized_display_name = display_name.strip()
    if not normalized_display_name:
        raise ValueError("display name is required")
    user_count = await session.scalar(select(func.count()).select_from(User))
    credits = PostgresCreditRepository(session)
    referrer = await credits.referrer(referral_code)
    if referral_code and referrer is None:
        raise ValueError("invalid referral code")
    is_first_user = not user_count
    code_record = None
    plan = None
    now = datetime.now(UTC)
    if not is_first_user:
        normalized_code = (registration_code or "").strip().upper()
        if not normalized_code:
            raise ValueError("registration code is required")
        code_record = await session.scalar(
            select(RegistrationCode)
            .where(RegistrationCode.code_hash == hashlib.sha256(normalized_code.encode()).hexdigest())
            .with_for_update()
        )
        if code_record is None or code_record.status != "active":
            raise ValueError("invalid or already redeemed registration code")
        if code_record.expires_at is not None and code_record.expires_at <= now:
            raise ValueError("registration code has expired")
        plan = await session.get(BillingPlan, code_record.plan_id)
        if plan is None or not plan.active:
            raise ValueError("registration code plan is unavailable")
    user = User(
        email=normalize_email(email),
        password_hash=hash_password(password),
        display_name=normalized_display_name[:120],
        role="admin" if is_first_user else "user",
        status="active",
        referred_by_user_id=referrer.id if referrer else None,
    )
    try:
        async with session.begin_nested():
            session.add(user)
            await session.flush()
    except IntegrityError as exc:
        raise EmailAlreadyRegisteredError("email is already registered") from exc
    if code_record is not None and plan is not None:
        session.add(UserSubscription(
            user_id=user.id, plan_id=plan.id, status="active",
            current_period_start=now, current_period_end=now + timedelta(days=code_record.valid_days),
            provider="registration_code",
        ))
        code_record.status = "redeemed"
        code_record.redeemed_by_user_id = user.id
        code_record.redeemed_at = now
    await credits.ensure_referral_code(user)
    await credits.account(user.id)
    await session.flush()
    return user


async def redeem_registration_code(
    session: AsyncSession, *, user_id: uuid.UUID, registration_code: str
) -> dict:
    """Redeem a one-time code for an existing user's subscription."""
    normalized_code = registration_code.strip().upper()
    now = datetime.now(UTC)
    code_record = await session.scalar(
        select(RegistrationCode)
        .where(RegistrationCode.code_hash == hashlib.sha256(normalized_code.encode()).hexdigest())
        .with_for_update()
    )
    if code_record is None or code_record.status != "active":
        raise ValueError("invalid or already redeemed registration code")
    if code_record.expires_at is not None and code_record.expires_at <= now:
        raise ValueError("registration code has expired")
    plan = await session.get(BillingPlan, code_record.plan_id)
    if plan is None or not plan.active:
        raise ValueError("registration code plan is unavailable")

    subscription = await session.scalar(
        select(UserSubscription).where(UserSubscription.user_id == user_id).with_for_update()
    )
    starts_at = now
    if subscription is not None and subscription.current_period_end is not None:
        starts_at = max(now, subscription.current_period_end)
    ends_at = starts_at + timedelta(days=code_record.valid_days)
    if subscription is None:
        subscription = UserSubscription(
            user_id=user_id, plan_id=plan.id, status="active",
            current_period_start=now, current_period_end=ends_at,
            provider="registration_code",
        )
        session.add(subscription)
    else:
        subscription.plan_id = plan.id
        subscription.status = "active"
        subscription.current_period_start = now
        subscription.current_period_end = ends_at
        subscription.provider = "registration_code"
    code_record.status = "redeemed"
    code_record.redeemed_by_user_id = user_id
    code_record.redeemed_at = now
    await session.flush()
    return {"plan_code": plan.code, "current_period_end": ends_at.isoformat()}


async def authenticate_user(session: AsyncSession, *, email: str, password: str) -> User | None:
    user = await session.scalar(select(User).where(User.email == normalize_email(email)))
    if user is None or user.status != "active":
        return None
    if not verify_password(user.password_hash, password):
        return None
    user.last_login_at = datetime.now(UTC)
    return user


async def create_session(
    session: AsyncSession,
    *,
    user: User,
    ip: str | None,
    user_agent: str | None,
) -> tuple[str, UserSession]:
    token = new_session_token()
    record = UserSession(
        user_id=user.id,
        token_hash=hash_session_token(token),
        expires_at=datetime.now(UTC) + SESSION_TTL,
        ip=(ip or "")[:64] or None,
        user_agent=(user_agent or "")[:512] or None,
    )
    session.add(record)
    await session.flush()
    return token, record


async def resolve_session(session: AsyncSession, token: str) -> CurrentUser | None:
    if not token:
        return None
    row = await session.execute(
        select(UserSession, User)
        .join(User, User.id == UserSession.user_id)
        .where(UserSession.token_hash == hash_session_token(token))
    )
    found = row.one_or_none()
    if found is None:
        return None
    user_session, user = found
    now = datetime.now(UTC)
    if user_session.revoked_at is not None or user_session.expires_at <= now:
        return None
    if user.status != "active":
        return None
    return CurrentUser(
        id=user.id,
        email=user.email,
        role=user.role,
        session_id=user_session.id,
    )


async def revoke_session(session: AsyncSession, session_id: uuid.UUID) -> None:
    await session.execute(
        update(UserSession)
        .where(UserSession.id == session_id, UserSession.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )
