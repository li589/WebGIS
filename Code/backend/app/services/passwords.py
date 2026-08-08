"""Password hashing (PBKDF2-SHA256, stdlib only)."""

from __future__ import annotations

import hashlib
import secrets

_ALGO = "pbkdf2-sha256"
_DEFAULT_ITERATIONS = 200_000


def hash_password(password: str, *, iterations: int = _DEFAULT_ITERATIONS) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"{_ALGO}${iterations}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iter_s, salt_hex, hash_hex = stored.split("$", 3)
        if algo != _ALGO:
            return False
        iterations = int(iter_s)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(hash_hex)
        actual = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt, iterations
        )
        return secrets.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False
