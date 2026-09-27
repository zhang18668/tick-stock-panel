from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.config import Settings


def test_standalone_mode_does_not_require_database() -> None:
    config = Settings(app_mode="standalone", database_url="")
    assert config.app_mode == "standalone"
    assert config.database_url == ""


def test_multi_user_mode_requires_database_url() -> None:
    with pytest.raises(ValidationError, match="database_url is required"):
        Settings(app_mode="multi_user", database_url="")


def test_multi_user_mode_accepts_postgresql_url() -> None:
    config = Settings(
        app_mode="multi_user",
        database_url="postgresql+asyncpg://user:pass@localhost/db",
    )
    assert config.database_url.startswith("postgresql+asyncpg://")
