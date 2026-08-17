"""secret_cipher 共享加密模块单测（安全收敛 W-A1）。

覆盖：
- 裸原语 round-trip、随机 IV、错误密钥、篡改密文。
- encrypt_secret 三分支：无 key / cryptography 缺失 / 通用异常 × require_encryption。
- decrypt_secret fail-closed：生产空 IV、生产无 key + 非空 IV（F10 补强）、
  dev 明文回退、密钥轮换。
"""

from __future__ import annotations

import base64

import pytest

from app.core.config import settings
from app.services import secret_cipher as sc

_VALID_KEY = "a" * 64
_OTHER_KEY = "b" * 64


def _as_production():
    # 必须在调用时解析 config.settings 当前对象：其它测试可能已整体替换
    # app.core.config.settings（见 F6 split-brain），导入期绑定会改到旧对象上。
    import app.core.config as config

    prev = config.settings.environment
    object.__setattr__(config.settings, "environment", "production")
    return prev


def _restore(prev):
    import app.core.config as config

    object.__setattr__(config.settings, "environment", prev)


# ── 裸原语 ───────────────────────────────────────────────────────────────


def test_aesgcm_roundtrip():
    ct, iv = sc.aesgcm_encrypt(_VALID_KEY, "sk-secret-123")
    assert ct and iv
    assert sc.aesgcm_decrypt(_VALID_KEY, ct, iv) == "sk-secret-123"


def test_aesgcm_random_iv_each_call():
    ct1, iv1 = sc.aesgcm_encrypt(_VALID_KEY, "same")
    ct2, iv2 = sc.aesgcm_encrypt(_VALID_KEY, "same")
    assert iv1 != iv2
    assert ct1 != ct2


def test_aesgcm_wrong_key_raises():
    ct, iv = sc.aesgcm_encrypt(_VALID_KEY, "secret")
    with pytest.raises(Exception):
        sc.aesgcm_decrypt(_OTHER_KEY, ct, iv)


def test_aesgcm_tampered_ciphertext_raises():
    ct, iv = sc.aesgcm_encrypt(_VALID_KEY, "secret")
    raw = bytearray(base64.b64decode(ct))
    raw[0] ^= 0xFF
    tampered = base64.b64encode(bytes(raw)).decode("ascii")
    with pytest.raises(Exception):
        sc.aesgcm_decrypt(_VALID_KEY, tampered, iv)


def test_aesgcm_bad_key_hex_raises():
    with pytest.raises(Exception):
        sc.aesgcm_encrypt("zz" * 32, "secret")


def test_aesgcm_utf8_payload_roundtrip():
    payload = "令牌-🔐-tokén"
    ct, iv = sc.aesgcm_encrypt(_VALID_KEY, payload)
    assert sc.aesgcm_decrypt(_VALID_KEY, ct, iv) == payload


# ── encrypt_secret 三分支 ────────────────────────────────────────────────


def test_encrypt_secret_no_key_required_raises():
    with pytest.raises(RuntimeError, match="ENCRYPTION_KEY"):
        sc.encrypt_secret("v", key="", require_encryption=True)


def test_encrypt_secret_no_key_dev_plaintext_fallback():
    ct, iv = sc.encrypt_secret("v", key="", require_encryption=False)
    assert (ct, iv) == ("v", "")


def test_encrypt_secret_missing_cryptography_required_raises(monkeypatch):
    def _boom(key, plaintext):
        raise ImportError("no cryptography")

    monkeypatch.setattr(sc, "aesgcm_encrypt", _boom)
    with pytest.raises(RuntimeError, match="cryptography package required"):
        sc.encrypt_secret("v", key=_VALID_KEY, require_encryption=True)


def test_encrypt_secret_missing_cryptography_dev_fallback(monkeypatch):
    def _boom(key, plaintext):
        raise ImportError("no cryptography")

    monkeypatch.setattr(sc, "aesgcm_encrypt", _boom)
    ct, iv = sc.encrypt_secret("v", key=_VALID_KEY, require_encryption=False)
    assert (ct, iv) == ("v", "")


def test_encrypt_secret_generic_error_required_wraps(monkeypatch):
    def _boom(key, plaintext):
        raise ValueError("bad hex")

    monkeypatch.setattr(sc, "aesgcm_encrypt", _boom)
    with pytest.raises(RuntimeError, match="Encryption failed"):
        sc.encrypt_secret("v", key=_VALID_KEY, require_encryption=True)


def test_encrypt_secret_generic_error_dev_fallback(monkeypatch):
    def _boom(key, plaintext):
        raise ValueError("bad hex")

    monkeypatch.setattr(sc, "aesgcm_encrypt", _boom)
    ct, iv = sc.encrypt_secret("v", key=_VALID_KEY, require_encryption=False)
    assert (ct, iv) == ("v", "")


def test_encrypt_secret_roundtrip_via_policy_wrapper():
    ct, iv = sc.encrypt_secret("secret-xyz", key=_VALID_KEY, require_encryption=True)
    assert sc.decrypt_secret(ct, iv, key=_VALID_KEY, require_encryption=True) == (
        "secret-xyz"
    )


# ── decrypt_secret fail-closed 策略 ──────────────────────────────────────


def test_decrypt_secret_production_empty_iv_rejected():
    prev = _as_production()
    try:
        with pytest.raises(RuntimeError, match="empty-IV"):
            sc.decrypt_secret("c2l4ZGF0YQ==", "", key=_VALID_KEY, require_encryption=True)
    finally:
        _restore(prev)


def test_decrypt_secret_production_no_key_nonempty_iv_rejected():
    """F10 补强：生产环境无 key + 非空 IV 不允许把密文当明文返回。"""
    prev = _as_production()
    try:
        with pytest.raises(RuntimeError, match="without encryption key"):
            sc.decrypt_secret("c2l4ZGF0YQ==", "dGVzdGl2", key="", require_encryption=True)
    finally:
        _restore(prev)


def test_decrypt_secret_no_key_not_required_returns_ciphertext():
    """require_encryption 是调用方策略（各 repo 传 secrets_encryption_required()）。"""
    out = sc.decrypt_secret("c2l4ZGF0YQ==", "dGVzdGl2", key="", require_encryption=False)
    assert out == "c2l4ZGF0YQ=="


def test_decrypt_secret_dev_empty_iv_returns_ciphertext():
    assert settings.environment in {"development", "dev", "test", "testing"}
    out = sc.decrypt_secret("plain-value", "", key="", require_encryption=False)
    assert out == "plain-value"


def test_decrypt_secret_key_rotation_raises():
    ct, iv = sc.aesgcm_encrypt(_VALID_KEY, "rotated-secret")
    with pytest.raises(Exception):
        sc.decrypt_secret(ct, iv, key=_OTHER_KEY, require_encryption=True)


def test_decrypt_secret_garbage_ciphertext_raises():
    with pytest.raises(Exception):
        sc.decrypt_secret("!!!not-base64!!!", "dGVzdGl2", key=_VALID_KEY, require_encryption=True)
