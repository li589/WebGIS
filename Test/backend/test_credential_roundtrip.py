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

from unittest.mock import patch

import pytest
from app.services import portal_catalog as portal_catalog_mod
from app.services import portal_credentials as portal_mod
from app.services.api_keys_repository import ApiKeysRepository
from app.services.gee_credentials_repository import GeeCredentialsRepository

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


def test_copernicus_env_overlay_prefers_userpass(monkeypatch):
    """.env 账密 overlay 优先于 token：CDSE 主路径是 OIDC 账密交换。"""
    repo = _DictRepo()
    monkeypatch.setenv("BACKEND_COPERNICUS_USERNAME", "cdse-user")
    monkeypatch.setenv("BACKEND_COPERNICUS_PASSWORD", "cdse-pass")
    monkeypatch.setenv("BACKEND_COPERNICUS_TOKEN", "stale-static-token")
    try:
        store = portal_mod.load_portal_credentials_secret(
            repo=repo, encryption_key=_VALID_KEY
        )
        entry = store["copernicus"]
        assert entry["auth_type"] == "basic"
        assert entry["username"] == "cdse-user"
        assert entry["password"] == "cdse-pass"
        assert "token" not in entry
    finally:
        monkeypatch.delenv("BACKEND_COPERNICUS_USERNAME", raising=False)
        monkeypatch.delenv("BACKEND_COPERNICUS_PASSWORD", raising=False)
        monkeypatch.delenv("BACKEND_COPERNICUS_TOKEN", raising=False)


def test_copernicus_env_overlay_token_only(monkeypatch):
    """仅 token 时维持静态 Bearer overlay（向后兼容）。"""
    repo = _DictRepo()
    monkeypatch.setenv("BACKEND_COPERNICUS_TOKEN", "env-token")
    try:
        entry = portal_mod.load_portal_credentials_secret(
            repo=repo, encryption_key=_VALID_KEY
        )["copernicus"]
        assert entry["auth_type"] == "bearer"
        assert entry["token"] == "env-token"
    finally:
        monkeypatch.delenv("BACKEND_COPERNICUS_TOKEN", raising=False)


def test_portal_id_key_projects_to_profile_key():
    """键归一：portal_id 键（如 esa_copernicus）存储投影到 credential_profile
    规范键（copernicus）——目录徽标/回填/worker 解析统一读规范键。"""
    repo = _DictRepo()
    portal_mod.upsert_portal_credential(
        repo=repo,
        encryption_key=_VALID_KEY,
        portal_id="esa_copernicus",
        payload={
            "enabled": True,
            "auth_type": "basic",
            "username": "cdse-user",
            "password": "cdse-pass",
        },
    )
    store = portal_mod.load_portal_credentials_secret(
        repo=repo, encryption_key=_VALID_KEY
    )
    # 原键保留（向后兼容）+ 规范键投影
    assert store["esa_copernicus"]["password"] == "cdse-pass"
    projected = store["copernicus"]
    assert projected["username"] == "cdse-user"
    assert projected["password"] == "cdse-pass"
    assert projected["auth_type"] == "basic"
    assert projected["source"] == "db"


def test_profile_dedicated_key_wins_over_alias_projection():
    """规范 profile 专键条目优先，不被 portal_id 别名投影覆盖。"""
    repo = _DictRepo()
    portal_mod.upsert_portal_credential(
        repo=repo,
        encryption_key=_VALID_KEY,
        portal_id="esa_download",
        payload={"auth_type": "basic", "username": "alias-user", "password": "alias-pass"},
    )
    portal_mod.upsert_portal_credential(
        repo=repo,
        encryption_key=_VALID_KEY,
        portal_id="copernicus",
        payload={"auth_type": "basic", "username": "direct-user", "password": "direct-pass"},
    )
    store = portal_mod.load_portal_credentials_secret(
        repo=repo, encryption_key=_VALID_KEY
    )
    assert store["copernicus"]["username"] == "direct-user"


def test_delete_profile_key_purges_alias_residue():
    """清除规范键时同步清除别名键残留——否则归一投影让「清除凭据」失效且
    密文残留（secret 清除必须彻底）。"""
    repo = _DictRepo()
    portal_mod.upsert_portal_credential(
        repo=repo,
        encryption_key=_VALID_KEY,
        portal_id="esa_copernicus",
        payload={"auth_type": "basic", "username": "u", "password": "p"},
    )
    portal_mod.delete_portal_credential(
        repo=repo, encryption_key=_VALID_KEY, portal_id="copernicus"
    )
    raw = repo.get_json("portal_credentials", {})
    assert "esa_copernicus" not in raw
    assert "copernicus" not in raw
    store = portal_mod.load_portal_credentials_secret(
        repo=repo, encryption_key=_VALID_KEY
    )
    assert "copernicus" not in store or not store["copernicus"].get("password")


def test_portal_catalog_reports_credentials_for_alias_stored_entry():
    """端到端：portal_id 键存储后目录徽标（has_credentials）转绿。"""
    from app.core.config import settings

    repo = _DictRepo()
    portal_mod.upsert_portal_credential(
        repo=repo,
        encryption_key=_VALID_KEY,
        portal_id="esa_copernicus",
        payload={"auth_type": "basic", "username": "u", "password": "p"},
    )
    prev_key = settings.gee_credentials_encryption_key
    object.__setattr__(settings, "gee_credentials_encryption_key", _VALID_KEY)
    try:
        with patch.object(portal_catalog_mod, "_repo", return_value=repo):
            entries = {e["portal_id"]: e for e in portal_catalog_mod.get_portal_catalog()}
    finally:
        object.__setattr__(settings, "gee_credentials_encryption_key", prev_key)
    assert entries["esa_copernicus"]["has_credentials"] is True
    assert entries["esa_download"]["has_credentials"] is True


def test_api_key_upsert_resets_test_status_on_secret_change(tmp_path):
    repo = _make_repo(tmp_path, _VALID_KEY)
    try:
        repo.upsert_key(key_name="test_svc", key_value="val1", display_name="Test Svc")
        repo.update_test_status("test_svc", "ok")
        info = repo.get_key_info("test_svc")
        assert info["last_test_status"] == "ok"
        assert info["last_tested_at"] is not None

        # 1) Metadata only update: test status is preserved
        repo.upsert_key(
            key_name="test_svc",
            key_value="val1",
            display_name="Updated Test Svc",
            description="some desc",
        )
        info = repo.get_key_info("test_svc")
        assert info["display_name"] == "Updated Test Svc"
        assert info["last_test_status"] == "ok"

        # 2) Secret value update: test status is reset to None
        repo.upsert_key(
            key_name="test_svc",
            key_value="val2_new_secret",
            display_name="Updated Test Svc",
        )
        info = repo.get_key_info("test_svc")
        assert info["last_test_status"] is None
        assert info["last_tested_at"] is None

        # Check history contains original version
        history = repo.list_history("test_svc")
        assert len(history) == 1
        assert history[0]["created_at"] is not None
    finally:
        repo.close()


def test_api_key_delete_purges_history(tmp_path):
    repo = _make_repo(tmp_path, _VALID_KEY)
    try:
        repo.upsert_key(key_name="k_del", key_value="val1", display_name="Del")
        repo.upsert_key(key_name="k_del", key_value="val2", display_name="Del")
        assert len(repo.list_history("k_del")) == 1

        repo.delete_key("k_del", purge_history=True)
        assert repo.get_key_info("k_del") is None
        assert len(repo.list_history("k_del")) == 0
    finally:
        repo.close()


def _make_gee_repo(tmp_path, key: str) -> GeeCredentialsRepository:
    db_parent = tmp_path / "state"
    db_parent.mkdir(parents=True, exist_ok=True)
    return GeeCredentialsRepository(
        str(db_parent / "gee_credentials.sqlite3"), encryption_key=key
    )


def test_gee_credentials_encrypt_decrypt_roundtrip(tmp_path):
    repo = _make_gee_repo(tmp_path, _VALID_KEY)
    sa_data = {
        "client_email": "sa@example.com",
        "private_key": "mock_sa_private_key_secret_for_tests",
        "private_key_id": "key123",
        "project_id": "demo-gee-project",
    }
    try:
        info = repo.upsert_account(
            account_id="acc_main",
            service_account_json=sa_data,
            display_name="Main GEE Account",
        )
        assert info is not None
        assert info["account_id"] == "acc_main"
        assert info["display_name"] == "Main GEE Account"
        assert info["project_id"] == "demo-gee-project"
        assert info["enabled"] is True
        # 敏感信息绝不在 info 字典中泄露
        assert "private_key" not in info
        assert "credentials_encrypted" not in info

        # 解密回环：get_account_credentials 恢复完整数据
        plain_creds = repo.get_account_credentials("acc_main")
        assert plain_creds is not None
        assert plain_creds["client_email"] == "sa@example.com"
        assert plain_creds["private_key"] == sa_data["private_key"]
        assert plain_creds["project_id"] == "demo-gee-project"

        # list_accounts 列表包含该账号且脱敏
        accounts = repo.list_accounts()
        assert len(accounts) == 1
        assert accounts[0]["account_id"] == "acc_main"
        assert "private_key" not in accounts[0]
        assert "credentials_encrypted" not in accounts[0]
    finally:
        repo.close()


def test_gee_credentials_rotation_breaks_old_ciphertext(tmp_path):
    repo1 = _make_gee_repo(tmp_path, _VALID_KEY)
    sa_data = {
        "client_email": "rot@example.com",
        "private_key": "some-secret-key",
        "private_key_id": "k1",
    }
    try:
        repo1.upsert_account(account_id="acc_rot", service_account_json=sa_data)
    finally:
        repo1.close()

    # 使用不同密钥重新打开同一个数据库，解密必须失败
    repo2 = _make_gee_repo(tmp_path, _OTHER_KEY)
    try:
        with pytest.raises((RuntimeError, ValueError, Exception)):
            repo2.get_account_credentials("acc_rot")
    finally:
        repo2.close()


def test_gee_credentials_toggle_and_filtering(tmp_path):
    repo = _make_gee_repo(tmp_path, _VALID_KEY)
    sa_data = {
        "client_email": "toggle@example.com",
        "private_key": "key",
        "private_key_id": "k1",
        "project_id": "proj1",
    }
    try:
        repo.upsert_account(account_id="acc_tog", service_account_json=sa_data)
        assert len(repo.list_enabled_accounts_with_credentials()) == 1

        # 禁用
        repo.set_enabled("acc_tog", False)
        assert len(repo.list_enabled_accounts_with_credentials()) == 0
        assert repo.get_account_credentials("acc_tog") is None

        # include_disabled=True 仍能查到脱敏信息
        disabled_list = repo.list_accounts(include_disabled=True)
        assert len(disabled_list) == 1
        assert disabled_list[0]["enabled"] is False

        # 重新启用
        repo.set_enabled("acc_tog", True)
        assert len(repo.list_enabled_accounts_with_credentials()) == 1

        # 删除
        assert repo.delete_account("acc_tog") is True
        assert repo.get_account("acc_tog") is None
        assert len(repo.list_accounts()) == 0
    finally:
        repo.close()
