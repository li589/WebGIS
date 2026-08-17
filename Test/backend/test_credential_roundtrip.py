"""Credential encryption round-trip + fail-closed policy tests (CGDA review F1/F10).

Covers:
- Real-key encrypt -> decrypt roundtrip for API keys and portal credentials.
- Key rotation breaks old ciphertext (cannot be decrypted with a different key).
- Production / non-development empty-IV decryption is rejected at the repository layer.
- Missing encryption key in non-development fail-closed (F10 fix): a non-empty-IV
  ciphertext cannot be returned as plaintext when no key is configured.

These are repository / blob-level tests (no HTTP, no Redis), so they run anywhere.
"""

from __future__ import annotations

import pytest

from app.services import portal_credentials as portal_mod
from app.services.api_keys_repository import ApiKeysRepository

_VALID_KEY = "a" * 64  # 32 bytes, valid hex
_OTHER_KEY = "b" * 64


def _make_repo(tmp_path, key: str) -> ApiKeysRepository:
    db_parent = tmp_path / "state"
    db_parent.mkdir(parents=True, exist_ok=True)
    return ApiKeysRepository(str(db_parent / "apikeys.sqlite3"), encryption_key=key)


def test_api_key_encrypt_decrypt_roundtrip(tmp_path):
    repo = _make_repo(tmp_path, _VALID_KEY)
    try:
        info = repo.upsert_key(
            key_name="openai",
            key_value="sk-secret-1234567890",
            display_name="OpenAI",
        )
        assert info is not None
        plain = repo.get_key_value("openai")
        assert plain == "sk-secret-1234567890"
        # masked value must never equal the plaintext
        assert info["masked_value"] != "sk-secret-1234567890"
    finally:
        repo.close()


def test_api_key_key_rotation_breaks_old_ciphertext(tmp_path):
    repo1 = _make_repo(tmp_path, _VALID_KEY)
    try:
        repo1.upsert_key(
            key_name="k", key_value="rotated-secret", display_name="Rotated"
        )
    finally:
        repo1.close()

    # Reopen the same DB with a DIFFERENT key: the stored ciphertext must not decrypt.
    repo2 = _make_repo(tmp_path, _OTHER_KEY)
    try:
        with pytest.raises(Exception):
            repo2.get_key_value("k")
    finally:
        repo2.close()


def test_api_key_decrypt_missing_key_in_nondev_raises(tmp_path):
    # F10: decrypting a non-empty-IV ciphertext with NO key must fail-closed.
    # secrets_encryption_required() is True only outside {dev,test}, so force production.
    from app.core.config import settings

    prev = settings.environment
    object.__setattr__(settings, "environment", "production")
    repo = _make_repo(tmp_path, "")
    try:
        with pytest.raises(RuntimeError):
            repo._decrypt("c2l4ZGF0YQ==", "dGVzdGl2")  # ciphertext, non-empty iv, no key
    finally:
        object.__setattr__(settings, "environment", prev)
        repo.close()


def test_api_key_production_empty_iv_rejected(tmp_path):
    from app.core.config import settings

    prev = settings.environment
    object.__setattr__(settings, "environment", "production")
    repo = _make_repo(tmp_path, _VALID_KEY)
    try:
        with pytest.raises(RuntimeError, match="empty-IV"):
            repo._decrypt("c2l4ZGF0YQ==", "")
    finally:
        object.__setattr__(settings, "environment", prev)
        repo.close()


def test_portal_blob_roundtrip_with_key():
    enc = portal_mod._encrypt_blob("portal-token-secret", _VALID_KEY)
    assert enc["iv"] and enc["iv"] != "plain"
    dec = portal_mod._decrypt_blob(enc["ciphertext"], enc["iv"], _VALID_KEY)
    assert dec == "portal-token-secret"


def test_portal_plaintext_iv_rejected_in_nondev():
    from app.core.config import settings

    prev = settings.environment
    object.__setattr__(settings, "environment", "production")
    try:
        with pytest.raises(RuntimeError, match="plaintext"):
            portal_mod._decrypt_blob("c2l4ZGF0YQ==", "plain", "")
    finally:
        object.__setattr__(settings, "environment", prev)


class _DictRepo:
    """In-memory stand-in for the credential repo (get_json/set_json only)."""

    def __init__(self) -> None:
        self._store: dict[str, object] = {}

    def get_json(self, key: str, default: object = None) -> object:
        return self._store.get(key, default)

    def set_json(self, key: str, value: object) -> None:
        self._store[key] = value


def test_portal_enabled_fail_closed_preserves_disabled_on_partial_update():
    """F4: a partial update (no `enabled`) must NOT resurrect a disabled portal,
    while an explicit `enabled` still overrides as before."""
    repo = _DictRepo()
    # 1) create a deliberately disabled portal
    portal_mod.upsert_portal_credential(
        repo=repo,
        encryption_key=_VALID_KEY,
        portal_id="earthdata",
        payload={"token": "secret-token", "enabled": False},
    )
    raw = repo.get_json("portal_credentials", {})
    assert raw["earthdata"]["enabled"] is False

    # 2) partial update WITHOUT `enabled` -> stays disabled (fail-closed)
    portal_mod.upsert_portal_credential(
        repo=repo,
        encryption_key=_VALID_KEY,
        portal_id="earthdata",
        payload={"token": "rotated-token"},
    )
    raw = repo.get_json("portal_credentials", {})
    assert raw["earthdata"]["enabled"] is False

    # 3) explicit enabled=True overrides
    portal_mod.upsert_portal_credential(
        repo=repo,
        encryption_key=_VALID_KEY,
        portal_id="earthdata",
        payload={"enabled": True},
    )
    raw = repo.get_json("portal_credentials", {})
    assert raw["earthdata"]["enabled"] is True

    # 4) explicit enabled=False overrides back
    portal_mod.upsert_portal_credential(
        repo=repo,
        encryption_key=_VALID_KEY,
        portal_id="earthdata",
        payload={"enabled": False},
    )
    raw = repo.get_json("portal_credentials", {})
    assert raw["earthdata"]["enabled"] is False


def test_portal_accounts_upsert_roundtrip():
    """多账号（NSMC 限额轮换）：写入清洗、public 投影报 account_count、清空回落单凭据。"""
    repo = _DictRepo()

    portal_mod.upsert_portal_credential(
        repo=repo,
        encryption_key=_VALID_KEY,
        portal_id="nsmc",
        payload={
            "enabled": True,
            "auth_type": "basic",
            "token_header": "token",
            "accounts": [
                {"username": "u1", "password": "p1", "token": ""},
                {"username": "", "password": "", "token": "tok2"},
                # 无效条目（既无 token 也无用户名+密码）被清洗
                {"username": "u3", "password": "", "token": ""},
                "garbage",
            ],
        },
    )
    entry = portal_mod.load_portal_credentials_secret(
        repo=repo, encryption_key=_VALID_KEY
    )["nsmc"]
    accounts = entry["accounts"]
    assert [a["username"] for a in accounts] == ["u1", ""]
    assert accounts[1]["token"] == "tok2"

    public = portal_mod.public_portal_credentials(
        repo=repo, encryption_key=_VALID_KEY
    )["nsmc"]
    assert public["account_count"] == 2

    # 显式空列表 = 清空多账号（回落单凭据模式）
    portal_mod.upsert_portal_credential(
        repo=repo,
        encryption_key=_VALID_KEY,
        portal_id="nsmc",
        payload={"accounts": []},
    )
    entry = portal_mod.load_portal_credentials_secret(
        repo=repo, encryption_key=_VALID_KEY
    )["nsmc"]
    assert "accounts" not in entry
    public = portal_mod.public_portal_credentials(
        repo=repo, encryption_key=_VALID_KEY
    )["nsmc"]
    assert public["account_count"] == 0
