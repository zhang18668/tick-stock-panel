from __future__ import annotations

import uuid

import pytest

from app.user_system.context import CurrentUser
from app.user_system.security import (
    hash_password,
    hash_session_token,
    new_session_token,
    verify_password,
)


def test_current_user_is_immutable_and_admin_is_explicit() -> None:
    user = CurrentUser(
        id=uuid.uuid4(),
        email="user@example.com",
        role="user",
        session_id=uuid.uuid4(),
    )
    assert user.is_admin is False
    with pytest.raises(AttributeError):
        user.role = "admin"  # type: ignore[misc]


def test_password_hash_never_contains_plaintext_and_verifies() -> None:
    password = "correct-horse-battery-staple"
    password_hash = hash_password(password)
    assert password not in password_hash
    assert verify_password(password_hash, password)
    assert not verify_password(password_hash, "wrong-password")


def test_password_rejects_short_values() -> None:
    with pytest.raises(ValueError, match="at least 8"):
        hash_password("short")


def test_session_tokens_are_opaque_and_only_hash_is_persistable() -> None:
    token = new_session_token()
    digest = hash_session_token(token)
    assert token != digest
    assert len(digest) == 64
    assert hash_session_token(token) == digest
    assert hash_session_token(new_session_token()) != digest
