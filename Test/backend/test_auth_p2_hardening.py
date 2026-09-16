"""P2 鉴权加固回归：口令策略 / 账号锁定 / 过期会话清理 / 环回判定 / SVG 上传。

对应 2026-09-16 鉴权子系统评审的 P2 清单：

* P2-1 口令强度策略下沉到存储层（不只是 API 层的 Pydantic 校验）。
* P2-2 账号维度登录失败锁定（补 IP 限流在换 IP / development 旁路下的缺口）。
* P2-3 SQLite 过期会话主动清理（此前仅惰性删除 → 死行堆积）。
* P2-4 环回判定修正（``"localhost"`` 永不命中；补 IPv4-mapped IPv6）。
* 主题 SVG logo 脚本载体拦截（登录页存储型 XSS 第一层）。

本文件全部为纯函数/仓储级用例，不启动 ASGI 应用，保持秒级。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

_CODE_ROOT = Path(__file__).resolve().parents[2]
_PYTHON_PROVIDER = _CODE_ROOT / "algorithms" / "providers" / "Python"
for _p in (_PYTHON_PROVIDER, _CODE_ROOT):
    _s = str(_p)
    if _s in sys.path:
        sys.path.remove(_s)
    sys.path.insert(0, _s)


# --------------------------------------------------------------------------
# P2-1 口令强度策略
# --------------------------------------------------------------------------


def test_password_policy_rejects_weak_candidates():
    from app.services.passwords import PasswordPolicyError, validate_password

    weak = {
        "short1!": "长度不足",
        "alllowercase": "单一字符类",
        "12345678": "纯数字",
        "password123": "通用弱口令黑名单",
        "cgda-dev-admin": "本项目历史泄漏口令",
    }
    for pwd, _reason in weak.items():
        with pytest.raises(PasswordPolicyError):
            validate_password(pwd)


def test_password_policy_rejects_username_substring():
    from app.services.passwords import PasswordPolicyError, validate_password

    with pytest.raises(PasswordPolicyError):
        validate_password("Admin-Str0ng-42!", username="admin")


def test_password_policy_accepts_strong():
    from app.services.passwords import validate_password

    # 现有测试口令必须全部仍然可用，否则整套鉴权用例会被策略误伤
    for pwd in ("test-pass-123", "std-pass-123", "user-pass-123", "viewer-pass"):
        validate_password(pwd)
    validate_password("R0qh5KPJDhGFt3P3xFQf4dXdKgFn", username="admin")


def test_repository_enforces_policy_on_create_and_update(tmp_path):
    from app.services.passwords import PasswordPolicyError
    from app.services.user_repository import UserRepository

    repo = UserRepository(tmp_path / "users.sqlite3")
    with pytest.raises(PasswordPolicyError):
        repo.create_user(username="weak1", password="password123", role="standard")
    created = repo.create_user(
        username="ok1", password="Str0ng-Pw-9a7!", role="standard"
    )
    with pytest.raises(PasswordPolicyError):
        repo.update_user(int(created["id"]), password="12345678")


# --------------------------------------------------------------------------
# P2-2 账号维度登录失败锁定
# --------------------------------------------------------------------------


@pytest.fixture()
def lockout_memory(monkeypatch):
    """强制走进程内降级路径（断 Redis），阈值 3 次 / 窗口 60s，便于断言。"""
    import app.core.redis_client as redis_mod
    from app.services import login_lockout

    monkeypatch.setattr(redis_mod, "get_redis_client", lambda: None)
    monkeypatch.setenv("BACKEND_LOGIN_LOCKOUT_ENABLED", "1")
    monkeypatch.setenv("BACKEND_LOGIN_LOCKOUT_THRESHOLD", "3")
    monkeypatch.setenv("BACKEND_LOGIN_LOCKOUT_MINUTES", "1")
    login_lockout.clear_failures("alice")
    yield login_lockout
    login_lockout.clear_failures("alice")


def test_lockout_engages_after_threshold(lockout_memory):
    assert lockout_memory.lockout_status("alice") == (False, 0)
    assert lockout_memory.record_failure("alice") == 0
    assert lockout_memory.record_failure("alice") == 0
    # 第 3 次失败达到阈值 → 返回剩余锁定秒数
    remaining = lockout_memory.record_failure("alice")
    assert remaining > 0
    locked, retry_after = lockout_memory.lockout_status("alice")
    assert locked is True
    assert retry_after > 0


def test_lockout_is_case_insensitive(lockout_memory):
    for name in ("Alice", "ALICE", " alice "):
        lockout_memory.record_failure(name)
    assert lockout_memory.lockout_status("alice")[0] is True


def test_successful_login_clears_failures(lockout_memory):
    lockout_memory.record_failure("alice")
    lockout_memory.record_failure("alice")
    lockout_memory.clear_failures("alice")
    lockout_memory.record_failure("alice")
    lockout_memory.record_failure("alice")
    assert lockout_memory.lockout_status("alice")[0] is False


def test_lockout_can_be_disabled(lockout_memory, monkeypatch):
    monkeypatch.setenv("BACKEND_LOGIN_LOCKOUT_ENABLED", "0")
    for _ in range(10):
        assert lockout_memory.record_failure("alice") == 0
    assert lockout_memory.lockout_status("alice") == (False, 0)


def test_lockout_window_refreshes_on_continued_failures(lockout_memory):
    """锁定期间继续失败须续满窗口，否则「边锁边试」可把锁定耗穿。"""
    for _ in range(3):
        lockout_memory.record_failure("alice")
    lockout_memory._memory[lockout_memory._bucket("alice")][1] -= 55  # 模拟窗口将尽
    lockout_memory.record_failure("alice")
    _, retry_after = lockout_memory.lockout_status("alice")
    assert retry_after > 55, "锁定窗口未续满，攻击者可等待窗口尾端绕过"


# --------------------------------------------------------------------------
# P2-3 SQLite 过期会话清理
# --------------------------------------------------------------------------


def test_purge_expired_sessions_removes_only_stale_rows(tmp_path):
    from datetime import timedelta

    from app.services.user_repository import UserRepository

    repo = UserRepository(tmp_path / "users.sqlite3")
    user = repo.create_user(username="p2c", password="Str0ng-Pw-4b2!", role="standard")
    uid = int(user["id"])

    now = __import__("datetime").datetime.now(__import__("datetime").UTC)
    repo.upsert_session(
        token="expired-token",
        user_id=uid,
        username="p2c",
        role="standard",
        expires_at=(now - timedelta(hours=1)).isoformat(),
    )
    repo.upsert_session(
        token="live-token",
        user_id=uid,
        username="p2c",
        role="standard",
        expires_at=(now + timedelta(hours=1)).isoformat(),
    )

    assert repo.purge_expired_sessions() == 1
    assert repo.get_session("expired-token") is None
    assert repo.get_session("live-token") is not None


# --------------------------------------------------------------------------
# P2-4 环回判定
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "host",
    ["127.0.0.1", "::1", "localhost", "::ffff:127.0.0.1", "127.5.5.5", "LOCALHOST"],
)
def test_is_loopback_host_true(host):
    from app.services.credential_resolver import is_loopback_host

    assert is_loopback_host(host) is True


@pytest.mark.parametrize(
    "host",
    ["192.168.1.5", "8.8.8.8", "10.0.0.9", "", None, "::ffff:192.168.1.5"],
)
def test_is_loopback_host_false(host):
    from app.services.credential_resolver import is_loopback_host

    assert is_loopback_host(host) is False


def test_loopback_ips_no_longer_contains_unmatchable_localhost():
    """``request.client.host`` 恒为 IP 字面量，``"localhost"`` 条目永不命中。"""
    from app.services.credential_resolver import LOOPBACK_IPS

    assert "localhost" not in LOOPBACK_IPS


# --------------------------------------------------------------------------
# 主题 logo：SVG 脚本载体拦截（登录页存储型 XSS 第一层防御）
# --------------------------------------------------------------------------


def test_svg_logo_rejects_script_payloads():
    from app.services.theme_repository import assert_svg_safe

    for payload in (
        b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
        b'<svg onload="alert(1)"></svg>',
        b'<svg><foreignObject><body xmlns="http://www.w3.org/1999/xhtml">x</body></foreignObject></svg>',
        b'<svg><a href="javascript:alert(1)">x</a></svg>',
    ):
        with pytest.raises(ValueError):
            assert_svg_safe(payload)


def test_svg_logo_accepts_static_svg():
    from app.services.theme_repository import assert_svg_safe

    assert_svg_safe(b'<svg xmlns="http://www.w3.org/2000/svg"><rect width="10"/></svg>')


# --------------------------------------------------------------------------
# P2-2 端到端：HTTP 层锁定语义（429 + Retry-After + 错误码）
# --------------------------------------------------------------------------


@pytest.fixture()
def lockout_client(tmp_path, monkeypatch):
    """起一个真实 ASGI 应用，锁阈值降到 2 便于断言。"""
    from unittest.mock import patch

    monkeypatch.setenv("BACKEND_ENV", "test")
    monkeypatch.setenv("BACKEND_USER_AUTH_ENABLED", "true")
    monkeypatch.setenv("BACKEND_ADMIN_USERNAME", "lockadmin")
    monkeypatch.setenv("BACKEND_ADMIN_PASSWORD", "Lock-Adm1n-Pw!")
    monkeypatch.setenv("BACKEND_API_KEY", "lock-api-key")
    monkeypatch.setenv("BACKEND_API_KEYS_ENABLED", "true")
    monkeypatch.setenv("BACKEND_API_KEY_ROLE", "standard")
    monkeypatch.setenv("BACKEND_DATA_ROOT", str(tmp_path / "data"))
    monkeypatch.setenv("BACKEND_OUTPUT_ROOT", str(tmp_path / "out"))
    monkeypatch.setenv("BACKEND_WORKFLOW_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("BACKEND_DEV_AUTH_PREFILL", "false")
    monkeypatch.setenv("BACKEND_LOGIN_LOCKOUT_THRESHOLD", "2")
    monkeypatch.setenv("BACKEND_LOGIN_LOCKOUT_MINUTES", "1")

    from dataclasses import replace

    import app.core.config as cfg_mod
    from app.core.config import Settings

    cfg_mod.settings = replace(
        Settings(),
        admin_username="lockadmin",
        admin_password="Lock-Adm1n-Pw!",
        environment="test",
        api_key="lock-api-key",
        api_keys_enabled=True,
        api_key_role="standard",
    )
    monkeypatch.setattr("app.core.config.settings", cfg_mod.settings)

    from app.services import user_repository as ur_mod
    from app.services.user_repository import UserRepository

    repo = UserRepository(tmp_path / "state" / "users.sqlite3")

    from app.main import create_app
    from app.services.auth_bootstrap import bootstrap_auth
    from app.services.config_service import (
        _get_api_keys_repository,
        _get_effective_api_key_cached,
    )
    from app.services.effective_config import hydrate_effective_config

    with patch.object(ur_mod, "_repo", repo):
        hydrate_effective_config()
        bootstrap_auth()
        _get_api_keys_repository().upsert_key(
            key_name="backend_auth",
            key_value="lock-api-key",
            display_name="Test backend auth",
            description="pytest fixture",
            history_source="test",
            archive_previous=False,
        )
        _get_effective_api_key_cached.cache_clear()
        hydrate_effective_config()
        with TestClient(create_app()) as client:
            yield client


def test_login_lockout_returns_429_with_retry_after(lockout_client):
    ok = lockout_client.post(
        "/auth/login", json={"username": "lockadmin", "password": "Lock-Adm1n-Pw!"}
    )
    assert ok.status_code == 200, ok.text

    for _ in range(2):
        bad = lockout_client.post(
            "/auth/login", json={"username": "lockadmin", "password": "nope-wrong-1"}
        )
        assert bad.status_code == 401, bad.text

    # 阈值已满：此时即便口令正确也必须被拦在慢哈希之前
    blocked = lockout_client.post(
        "/auth/login", json={"username": "lockadmin", "password": "Lock-Adm1n-Pw!"}
    )
    assert blocked.status_code == 429, blocked.text
    assert blocked.json()["error_code"] == "C429001"
    assert int(blocked.headers["Retry-After"]) > 0


def test_admin_unlock_endpoint_clears_lockout(lockout_client):
    for _ in range(2):
        lockout_client.post(
            "/auth/login", json={"username": "lockadmin", "password": "nope-wrong-1"}
        )
    assert (
        lockout_client.post(
            "/auth/login",
            json={"username": "lockadmin", "password": "Lock-Adm1n-Pw!"},
        ).status_code
        == 429
    )

    # 起第二个管理员账号来解锁（被锁的账号自己登不进去）
    from app.services.user_repository import get_user_repository

    repo = get_user_repository()
    repo.create_user(username="rescuer", password="Second-Adm-Pw-8k!", role="admin")
    # 直接构造管理员会话：走 session_service 而非被锁的登录口
    from app.core.config import settings
    from app.services.session_service import create_session

    token = create_session(
        user_id=int(repo.get_by_username("rescuer")["id"]),
        username="rescuer",
        role="admin",
    )
    lockout_client.cookies.set(settings.session_cookie_name, token)
    locked_uid = int(repo.get_by_username("lockadmin")["id"])
    resp = lockout_client.post(f"/auth/users/{locked_uid}/unlock")
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "unlocked"

    lockout_client.cookies.clear()
    ok = lockout_client.post(
        "/auth/login", json={"username": "lockadmin", "password": "Lock-Adm1n-Pw!"}
    )
    assert ok.status_code == 200, ok.text
