"""Optional PostgreSQL multi-user plugin entry point."""
from __future__ import annotations

from app.config import settings
from app.extensions import BACKEND_EXTENSION_API_VERSION, BackendExtensionRegistrar

EXTENSION_ID = "tickstock.user-management"
EXTENSION_API_VERSION = BACKEND_EXTENSION_API_VERSION


def setup(registrar: BackendExtensionRegistrar) -> None:
    if settings.app_mode != "multi_user":
        return
    from app.user_system import admin_api, api, billing_api, usage_api
    from app.user_system.middleware import handle_request

    registrar.include_router(api.router)
    registrar.include_router(billing_api.router)
    registrar.include_router(admin_api.router)
    registrar.include_router(usage_api.router)
    registrar.register_request_handler(handle_request)


async def startup(_context) -> None:
    if settings.app_mode == "multi_user":
        from app.persistence.database import verify_database

        await verify_database()


async def shutdown() -> None:
    if settings.app_mode == "multi_user":
        from app.persistence.database import close_database

        await close_database()
