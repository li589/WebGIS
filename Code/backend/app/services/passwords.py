"""Password hashing (PBKDF2-SHA256, stdlib only) + 口令强度策略。

策略在**仓储层**校验（``UserRepository.create_user`` / ``update_user``），
而不是只放在 API 的 Pydantic 模型上 —— 否则脚本、迁移、运维命令等直接调用
仓储的路径会绕过校验，弱口令（如历史上入库的 ``cgda-dev-admin``）可被重新设置。
"""

from __future__ import annotations

import hashlib
import os
import secrets
import string

_ALGO = "pbkdf2-sha256"
_DEFAULT_ITERATIONS = 200_000

# 最小长度可用 BACKEND_PASSWORD_MIN_LENGTH 覆盖（默认 8，与 API 层一致）。
MIN_LENGTH = max(1, int(os.getenv("BACKEND_PASSWORD_MIN_LENGTH", "8") or 8))

# 已知弱口令黑名单：本项目历史上泄漏过的、以及通用常见弱口令。
# 命中即拒绝，防止"轮换后再设回同一个弱口令"。
WEAK_DENYLIST = frozenset(
    {
        # —— 本项目真实泄漏过的凭据（2026-09-16 轮换，见 Docs/04-执行部署/外网访问与Cloudflare隧道.md）——
        "cgda-dev-admin",
        "cgda-dev-write-key",
        "cgda-dev",
        "cgdaadmin",
        "cgda1234",
        # —— 通用常见弱口令 ——
        "password",
        "password1",
        "password123",
        "passw0rd",
        "12345678",
        "123456789",
        "1234567890",
        "1234567a",
        "qwertyui",
        "qwerty123",
        "iloveyou",
        "letmein",
        "welcome1",
        "admin123",
        "administrator",
        "changeme",
        "abc12345",
        "test1234",
        "default1",
        "11111111",
        "00000000",
        "aaaaaaaa",
    }
)

_CLASSES = (
    frozenset(string.ascii_lowercase),
    frozenset(string.ascii_uppercase),
    frozenset(string.digits),
    # 符号：非字母数字的其余可打印字符（含空格之外的标点）
    frozenset(set(string.punctuation)),
)


class PasswordPolicyError(ValueError):
    """口令不满足强度策略。"""


def _class_count(password: str) -> int:
    chars = set(password)
    return sum(1 for cls in _CLASSES if chars & cls)


def validate_password(password: str, *, username: str | None = None) -> None:
    """校验口令强度；不满足则抛 ``PasswordPolicyError``（为 ``ValueError`` 子类）。

    规则：
      1. 长度 ≥ ``MIN_LENGTH``；
      2. 至少包含 2 类字符（小写/大写/数字/符号）—— 内部系统取中等强度；
      3. 不在弱口令黑名单内（忽略大小写与首尾空白）；
      4. 不等于用户名，也不包含用户名（忽略大小写）。
    """
    if not isinstance(password, str) or not password:
        raise PasswordPolicyError("password is required")

    if len(password) < MIN_LENGTH:
        raise PasswordPolicyError(
            f"password must be at least {MIN_LENGTH} characters long"
        )

    if _class_count(password) < 2:
        raise PasswordPolicyError(
            "password must mix at least 2 character classes "
            "(lowercase / uppercase / digit / symbol)"
        )

    lowered = password.strip().lower()
    if lowered in WEAK_DENYLIST:
        raise PasswordPolicyError(
            "password is on the known-weak denylist; choose a different one"
        )

    if username:
        uname = username.strip().lower()
        if uname and (lowered == uname or uname in lowered):
            raise PasswordPolicyError("password must not contain the username")


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
