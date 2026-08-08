"""Encryption policy: hex key format + refuse empty-IV outside development."""

from __future__ import annotations

from dataclasses import replace
from unittest.mock import patch

import pytest

from app.core.config import settings
from app.services.effective_config import (
    assert_encryption_policy,
    refuse_empty_iv_outside_development,
    validate_encryption_key_format,
)

_VALID_KEY = "a" * 64


def test_validate_encryption_key_format_accepts_64_hex() -> None:
    validate_encryption_key_format(_VALID_KEY)


@pytest.mark.parametrize(
    "bad",
    ["", "abc", "g" * 64, "a" * 63, "a" * 65],
)
def test_validate_encryption_key_format_rejects_bad(bad: str) -> None:
    with pytest.raises(RuntimeError):
        validate_encryption_key_format(bad)


def test_assert_encryption_policy_rejects_malformed_key() -> None:
    with patch(
        "app.services.effective_config.settings",
        replace(
            settings,
            environment="development",
            gee_credentials_encryption_key="g" * 64,
        ),
    ):
        with pytest.raises(RuntimeError, match="hexadecimal"):
            assert_encryption_policy()


def test_assert_encryption_policy_accepts_valid_key() -> None:
    with patch(
        "app.services.effective_config.settings",
        replace(
            settings,
            environment="production",
            gee_credentials_encryption_key=_VALID_KEY,
        ),
    ):
        assert_encryption_policy()


def test_refuse_empty_iv_outside_development() -> None:
    with patch(
        "app.services.effective_config.settings",
        replace(settings, environment="production"),
    ):
        with pytest.raises(RuntimeError, match="empty-IV"):
            refuse_empty_iv_outside_development("")
    with patch(
        "app.services.effective_config.settings",
        replace(settings, environment="development"),
    ):
        refuse_empty_iv_outside_development("")  # allowed in development
        refuse_empty_iv_outside_development("dGVzdA==")
