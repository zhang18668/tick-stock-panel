"""Async PostgreSQL engine and transaction helpers.

Market data deliberately remains outside this module. It continues to use the
shared Parquet/DuckDB repository owned by the application lifespan.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import settings

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def multi_user_enabled() -> bool:
    return settings.app_mode == "multi_user"


def initialize_database() -> AsyncEngine | None:
    """Create the shared engine once; standalone mode intentionally does nothing."""
    global _engine, _session_factory
    if not multi_user_enabled():
        return None
    if _engine is None:
        _engine = create_async_engine(
            settings.database_url,
            pool_pre_ping=True,
            pool_size=settings.database_pool_size,
            max_overflow=settings.database_max_overflow,
        )
        _session_factory = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


async def close_database() -> None:
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None


async def verify_database() -> None:
    """Fail startup early when multi-user mode cannot reach PostgreSQL."""
    engine = initialize_database()
    if engine is None:
        return
    async with engine.connect() as connection:
        await connection.execute(text("SELECT 1"))


async def get_session() -> AsyncIterator[AsyncSession]:
    """Yield one transaction-scoped session for a FastAPI dependency."""
    if _session_factory is None:
        initialize_database()
    if _session_factory is None:
        raise RuntimeError("PostgreSQL is unavailable in standalone mode")
    async with _session_factory() as session, session.begin():
        yield session


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Open a transaction outside FastAPI dependency injection (for middleware)."""
    if _session_factory is None:
        initialize_database()
    if _session_factory is None:
        raise RuntimeError("PostgreSQL is unavailable in standalone mode")
    async with _session_factory() as session, session.begin():
        yield session
