"""Referral ownership and integer-cent service credits."""
from __future__ import annotations

import secrets
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.persistence.models import CreditAccount, CreditLedgerEntry, User


class InsufficientCreditsError(ValueError):
    pass


class PostgresCreditRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def ensure_referral_code(self, user: User) -> str:
        if user.referral_code:
            return user.referral_code
        for _ in range(10):
            code = secrets.token_hex(4).upper()
            exists = await self._session.scalar(select(User.id).where(User.referral_code == code))
            if exists is None:
                user.referral_code = code
                await self._session.flush()
                return code
        raise RuntimeError("could not allocate referral code")

    async def referrer(self, code: str | None) -> User | None:
        normalized = (code or "").strip().upper()
        if not normalized:
            return None
        return await self._session.scalar(select(User).where(User.referral_code == normalized))

    async def account(self, user_id: UUID, *, lock: bool = False) -> CreditAccount:
        query = select(CreditAccount).where(CreditAccount.user_id == user_id)
        if lock:
            query = query.with_for_update()
        account = await self._session.scalar(query)
        if account is None:
            account = CreditAccount(user_id=user_id)
            self._session.add(account)
            await self._session.flush()
        return account

    async def add(self, user_id: UUID, amount_cents: int, entry_type: str, business_key: str, description: str) -> bool:
        if amount_cents <= 0:
            raise ValueError("credit amount must be positive")
        if await self._session.scalar(select(CreditLedgerEntry.id).where(CreditLedgerEntry.business_key == business_key)):
            return False
        account = await self.account(user_id, lock=True)
        account.balance_cents += amount_cents
        account.earned_cents += amount_cents
        self._session.add(CreditLedgerEntry(
            user_id=user_id, amount_cents=amount_cents,
            balance_after_cents=account.balance_cents, entry_type=entry_type,
            business_key=business_key, description=description,
        ))
        await self._session.flush()
        return True

    async def spend(self, user_id: UUID, amount_cents: int, business_key: str, description: str) -> None:
        account = await self.account(user_id, lock=True)
        if account.balance_cents < amount_cents:
            raise InsufficientCreditsError("insufficient credits")
        account.balance_cents -= amount_cents
        account.spent_cents += amount_cents
        self._session.add(CreditLedgerEntry(
            user_id=user_id, amount_cents=-amount_cents,
            balance_after_cents=account.balance_cents, entry_type="service_purchase",
            business_key=business_key, description=description,
        ))
        await self._session.flush()

    async def summary(self, user_id: UUID) -> dict:
        account = await self.account(user_id)
        user = await self._session.get(User, user_id)
        code = await self.ensure_referral_code(user)
        entries = await self._session.scalars(
            select(CreditLedgerEntry).where(CreditLedgerEntry.user_id == user_id)
            .order_by(CreditLedgerEntry.created_at.desc()).limit(50)
        )
        referred_count = len((await self._session.scalars(select(User.id).where(User.referred_by_user_id == user_id))).all())
        return {
            "balance_cents": account.balance_cents, "earned_cents": account.earned_cents,
            "spent_cents": account.spent_cents, "referral_code": code,
            "referred_users": referred_count,
            "entries": [{
                "id": str(item.id), "amount_cents": item.amount_cents,
                "balance_after_cents": item.balance_after_cents, "entry_type": item.entry_type,
                "description": item.description, "created_at": item.created_at.isoformat(),
            } for item in entries],
        }
