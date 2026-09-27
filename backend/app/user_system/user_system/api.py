"""Registration, email login, logout, and current-user endpoints."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.persistence.database import get_session
from app.persistence.models import User
from app.user_system import service
from app.user_system.context import CurrentUser
from app.user_system.dependencies import require_user

router = APIRouter(prefix="/api/account", tags=["account"])

DatabaseSession = Annotated[AsyncSession, Depends(get_session)]
AuthenticatedUser = Annotated[CurrentUser, Depends(require_user)]

COOKIE_NAME = "cf_session"
COOKIE_MAX_AGE = int(service.SESSION_TTL.total_seconds())


class RegisterRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=8, max_length=128)
    display_name: str = Field(min_length=1, max_length=120)
    referral_code: str | None = Field(default=None, min_length=4, max_length=16)
    registration_code: str | None = Field(default=None, min_length=8, max_length=64)


class EmailLoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=128)


@router.get("/status")
async def status(request: Request, session: DatabaseSession) -> dict:
    token = request.cookies.get(COOKIE_NAME, "")
    user = await service.resolve_session(session, token)
    return {
        "mode": "multi_user",
        "authenticated": user is not None,
        "user": (
            {"id": str(user.id), "email": user.email, "role": user.role}
            if user is not None
            else None
        ),
    }


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite="lax",
        path="/",
    )


@router.post("/register", status_code=201)
async def register(
    payload: RegisterRequest,
    request: Request,
    response: Response,
    session: DatabaseSession,
) -> dict:
    try:
        user = await service.register_user(
            session,
            email=payload.email,
            password=payload.password,
            display_name=payload.display_name,
            referral_code=payload.referral_code,
            registration_code=payload.registration_code,
        )
    except service.EmailAlreadyRegisteredError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    token, _ = await service.create_session(
        session,
        user=user,
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    _set_session_cookie(response, token)
    return {"id": str(user.id), "email": user.email, "display_name": user.display_name}


@router.post("/login")
async def login(
    payload: EmailLoginRequest,
    request: Request,
    response: Response,
    session: DatabaseSession,
) -> dict:
    try:
        user = await service.authenticate_user(
            session, email=payload.email, password=payload.password
        )
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="invalid email or password") from exc
    if user is None:
        raise HTTPException(status_code=401, detail="invalid email or password")
    token, _ = await service.create_session(
        session,
        user=user,
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    _set_session_cookie(response, token)
    return {"id": str(user.id), "email": user.email, "display_name": user.display_name}


@router.post("/logout")
async def logout(
    response: Response,
    user: AuthenticatedUser,
    session: DatabaseSession,
) -> dict:
    await service.revoke_session(session, user.session_id)
    response.delete_cookie(
        COOKIE_NAME,
        path="/",
        secure=settings.auth_cookie_secure,
        httponly=True,
        samesite="lax",
    )
    return {"ok": True}


@router.get("/me")
async def me(user: AuthenticatedUser, session: DatabaseSession) -> dict:
    record = await session.get(User, user.id)
    return {
        "id": str(user.id),
        "email": user.email,
        "display_name": record.display_name if record is not None else None,
        "role": user.role,
    }
