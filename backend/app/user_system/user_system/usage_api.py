"""Privacy-minimal page usage aggregation for the administrator dashboard."""
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.persistence.database import get_session
from app.persistence.models import UserPageUsage
from app.user_system.context import CurrentUser
from app.user_system.dependencies import require_user

router = APIRouter(prefix="/api/usage", tags=["usage"])
DatabaseSession = Annotated[AsyncSession, Depends(get_session)]
AuthenticatedUser = Annotated[CurrentUser, Depends(require_user)]


class PageViewRequest(BaseModel):
    path: str = Field(min_length=1, max_length=160, pattern=r"^/[a-zA-Z0-9/_-]*$")


@router.post("/page")
async def record_page(payload: PageViewRequest, session: DatabaseSession, user: AuthenticatedUser) -> dict:
    item = await session.scalar(select(UserPageUsage).where(
        UserPageUsage.user_id == user.id, UserPageUsage.path == payload.path
    ))
    if item is None:
        session.add(UserPageUsage(user_id=user.id, path=payload.path))
    else:
        item.view_count += 1
    await session.flush()
    return {"ok": True}
