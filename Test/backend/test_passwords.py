"""Tests for app.services.passwords (PBKDF2-SHA256 hashing/verification)."""

from __future__ import annotations

import pytest

from app.services.passwords import (
    _ALGO,
    _DEFAULT_ITERATIONS,
    WEAK_POLICY_BYPASS_ENV_VAR,
    PasswordPolicyError,
    hash_password,
    validate_password,
    verify_password,
)

PLAIN = "Correct Horse Battery Staple!"


# ---------------------------------------------------------------------------
# Normal: hash + verify round trip
# ---------------------------------------------------------------------------


def test_hash_password_produces_expected_format():
    """A hashed password follows the ``algo$iter$salt$digest`` layout."""
    stored = hash_password(PLAIN)
    parts = stored.split("$", 3)
    assert len(parts) == 4, f"expected 4 $-separated parts, got {parts}"
    algo, iter_s, salt_hex, digest_hex = parts
    assert algo == _ALGO, "algorithm prefix must be pbkdf2-sha256"
    assert int(iter_s) == _DEFAULT_ITERATIONS, "default iterations must be 200000"
    assert len(salt_hex) == 32, "salt must be 16 bytes -> 32 hex chars"
    assert len(digest_hex) == 64, "sha256 digest must be 32 bytes -> 64 hex chars"


def test_verify_password_accepts_correct_password():
    """verify_password returns True for the original plaintext."""
    stored = hash_password(PLAIN)
    assert verify_password(PLAIN, stored) is True, "correct password must verify"


def test_verify_password_rejects_incorrect_password():
    """verify_password returns False for a wrong plaintext."""
    stored = hash_password(PLAIN)
    assert verify_password("definitely-wrong", stored) is False, (
        "incorrect password must not verify"
    )


# ---------------------------------------------------------------------------
# Boundary / constant-time
# ---------------------------------------------------------------------------


def test_hash_password_uses_random_salt_per_call():
    """Each hash call produces a different salt (and thus a different digest)."""
    a = hash_password(PLAIN)
    b = hash_password(PLAIN)
    assert a != b, "two hashes of the same password must differ (random salt)"
    # Both must still verify against the original password.
    assert verify_password(PLAIN, a), "first hash must verify"
    assert verify_password(PLAIN, b), "second hash must verify"


def test_hash_password_honours_custom_iterations():
    """Custom iteration count is embedded in the stored string and respected."""
    stored = hash_password(PLAIN, iterations=10_000)
    parts = stored.split("$", 3)
    assert int(parts[1]) == 10_000, "custom iterations must be stored in the string"
    assert verify_password(PLAIN, stored) is True, (
        "password hashed with custom iterations must verify"
    )


def test_verify_password_constant_time_on_mismatch():
    """verify_password uses secrets.compare_digest (returns bool, never raises)."""
    stored = hash_password(PLAIN)
    # A completely wrong digest-length garbage string should still return False,
    # not raise, because compare_digest handles unequal-but-same-length inputs.
    garbage = f"{_ALGO}${_DEFAULT_ITERATIONS}{'0' * 32}{'0' * 64}"
    assert verify_password(PLAIN, garbage) is False, (
        "garbage digest with valid format must return False, not raise"
    )


# ---------------------------------------------------------------------------
# Exception / malformed input
# ---------------------------------------------------------------------------


def test_verify_password_malformed_stored_returns_false():
    """Malformed stored strings (too few fields) return False, not raise."""
    assert verify_password(PLAIN, "not-a-valid-hash") is False, (
        "malformed stored hash must return False"
    )


def test_verify_password_wrong_algo_returns_false():
    """A stored hash with a foreign algorithm prefix returns False."""
    stored = hash_password(PLAIN)
    foreign = "bcrypt$" + stored.split("$", 1)[1]
    assert verify_password(PLAIN, foreign) is False, (
        "foreign algorithm prefix must be rejected"
    )


def test_verify_password_empty_string_returns_false():
    """An empty stored string returns False instead of raising."""
    assert verify_password(PLAIN, "") is False, "empty stored must return False"


# ---------------------------------------------------------------------------
# Password strength policy + the development-only weak-policy bypass
# ---------------------------------------------------------------------------

WEAK = "cgda-dev-admin"
STRONG = "R0qh5KPJDhGFt3P3xFQf4dXdKgFn"


def test_validate_password_rejects_known_weak_password():
    """A denylisted (historically leaked) password is refused even standalone."""
    with pytest.raises(PasswordPolicyError):
        validate_password(WEAK)


def test_validate_password_rejects_password_containing_username():
    """Rule 4: the password must not contain the username (case-insensitive)."""
    with pytest.raises(PasswordPolicyError):
        validate_password("Xk7-admin-Qz2", username="admin")


def test_validate_password_accepts_strong_password():
    validate_password(STRONG, username="admin")


def test_weak_bypass_off_by_default(monkeypatch):
    """Without the flag, development must still enforce the policy."""
    monkeypatch.delenv(WEAK_POLICY_BYPASS_ENV_VAR, raising=False)
    monkeypatch.setenv("BACKEND_ENV", "development")
    with pytest.raises(PasswordPolicyError):
        validate_password(WEAK, username="admin")


def test_weak_bypass_flag_value_must_be_truthy(monkeypatch):
    monkeypatch.setenv(WEAK_POLICY_BYPASS_ENV_VAR, "0")
    monkeypatch.setenv("BACKEND_ENV", "development")
    with pytest.raises(PasswordPolicyError):
        validate_password(WEAK, username="admin")


def test_weak_bypass_requires_both_flag_and_development_env(monkeypatch):
    """The switch is deliberately double-gated so it can never leak into prod."""
    monkeypatch.setenv(WEAK_POLICY_BYPASS_ENV_VAR, "1")

    # flag set but no environment declared -> still enforced
    monkeypatch.delenv("BACKEND_ENV", raising=False)
    with pytest.raises(PasswordPolicyError):
        validate_password(WEAK, username="admin")

    # flag set but non-development environment -> still enforced
    monkeypatch.setenv("BACKEND_ENV", "production")
    with pytest.raises(PasswordPolicyError):
        validate_password(WEAK, username="admin")

    # flag + development -> bypassed
    monkeypatch.setenv("BACKEND_ENV", "development")
    validate_password(WEAK, username="admin")


def test_weak_bypass_still_accepts_strong_passwords(monkeypatch):
    """Enabling the bypass must not change behaviour for valid passwords."""
    monkeypatch.setenv(WEAK_POLICY_BYPASS_ENV_VAR, "1")
    monkeypatch.setenv("BACKEND_ENV", "development")
    validate_password(STRONG, username="admin")
