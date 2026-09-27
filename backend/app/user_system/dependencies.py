"""FastAPI dependencies for authenticated multi-user routes."""
from __future__ import annotations

from fastapi import HTTPException, Request

from app.user_system.context import CurrentUser


def require_user(request: Request) -> CurrentUser:
    user = getattr(request.state, "current_user", None)
    if not isinstance(user, CurrentUser):
        raise HTTPException(status_code=401, detail="not authenticated")
    return user


def require_admin(request: Request) -> CurrentUser:
    user = require_user(request)
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="administrator access required")
    return user
