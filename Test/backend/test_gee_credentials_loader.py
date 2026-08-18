"""GeeCredentialsLoader 兼容性单测（earthengine-api 1.x）。

回归背景：旧实现回退分支引用 ``ee.Credentials``——该类在 earthengine-api
1.x 已移除，且 ``ee.ServiceAccountCredentials`` 的 1.x 签名为
``(email, key_file, key_data)``，旧代码把私钥按位置参数传入会被当作
key_file 文件路径。主路径改为 google.oauth2 直接构造后，这些用例锁定
新行为。
"""

from __future__ import annotations

import pytest


def _rsa_pem() -> str:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode("ascii")


@pytest.fixture()
def sa_info() -> dict:
    return {
        "client_email": "gee-test@cgda-test.iam.gserviceaccount.com",
        "private_key": _rsa_pem(),
        "private_key_id": "test-key-id",
        "token_uri": "https://oauth2.googleapis.com/token",
        "project_id": "cgda-test",
    }


def _loader():
    from app.gee.core.src.webgis_gee.accounts.credentials import GeeCredentialsLoader

    return GeeCredentialsLoader()


def test_load_returns_google_oauth_credentials(sa_info):
    """主路径：earthengine-api 1.x 下返回 google.oauth2 凭据对象（不再触碰
    已移除的 ee.Credentials），且不触发网络请求（无 eager refresh）。"""
    creds = _loader().load_service_account_credentials(sa_info)
    from google.oauth2 import service_account

    assert isinstance(creds, service_account.Credentials)
    assert creds.service_account_email == sa_info["client_email"]
    assert creds.project_id == "cgda-test"
    assert creds.token is None  # 未 refresh，Initialize 时才取 token


def test_load_accepts_json_string(sa_info):
    import json

    creds = _loader().load_service_account_credentials(json.dumps(sa_info))
    assert creds.service_account_email == sa_info["client_email"]


def test_missing_required_fields_raises(sa_info):
    del sa_info["private_key"]
    with pytest.raises(ValueError, match="private_key"):
        _loader().load_service_account_credentials(sa_info)


def test_fallback_returns_raw_dict_when_both_paths_fail(sa_info, monkeypatch):
    """google.oauth2 与 ee.ServiceAccountCredentials 均不可用时回退原始
    dict（不再抛 AttributeError: ee.Credentials）。"""
    from google.oauth2 import service_account as sa_module

    def _boom(*_args, **_kwargs):
        raise ImportError("google-auth mocked unavailable")

    monkeypatch.setattr(sa_module.Credentials, "from_service_account_info", _boom)
    import ee

    def _ee_boom(*_args, **_kwargs):
        raise ImportError("ee credentials mocked unavailable")

    monkeypatch.setattr(ee, "ServiceAccountCredentials", _ee_boom)

    creds = _loader().load_service_account_credentials(sa_info)
    assert isinstance(creds, dict)
    assert creds["client_email"] == sa_info["client_email"]
