from __future__ import annotations

import pytest

from app.user_system.service import normalize_email


def test_email_is_normalized_for_unique_identity() -> None:
    assert normalize_email("  User@Example.COM ") == "user@example.com"


@pytest.mark.parametrize("value", ["", "missing-at.example.com", "a@b", "a b@example.com"])
def test_invalid_email_is_rejected(value: str) -> None:
    with pytest.raises(ValueError, match="invalid email"):
        normalize_email(value)
