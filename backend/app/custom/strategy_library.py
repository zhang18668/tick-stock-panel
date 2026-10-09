from app.extensions import BACKEND_EXTENSION_API_VERSION, BackendExtensionRegistrar
from app.strategy_library.api import build_router

EXTENSION_ID = "strategy.library"
EXTENSION_API_VERSION = BACKEND_EXTENSION_API_VERSION


def setup(registrar: BackendExtensionRegistrar) -> None:
    registrar.include_router(build_router())
