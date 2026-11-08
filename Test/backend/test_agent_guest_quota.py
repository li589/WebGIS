"""未登录访客的「按天」助手额度（rate_limit.check_agent_guest_daily_quota）。

覆盖点：
1. 同一访客正好放行 ``limit`` 次，第 ``limit+1`` 次拒绝，且 Retry-After 指向次日零点；
2. 不同访客互不挤占（同一 IP 下也各自独立）——这是「按人记」的核心；
3. 前端没上报访客号时退回按 IP 计（旧缓存页面照样限得住）；
4. 额度 <= 0 时完全关闭（本机探针/自动化用）；
5. 计数键包含北京日期，跨日自动换桶（不依赖 Redis TTL 也成立）。
"""

from __future__ import annotations

import pytest

from app.api import rate_limit as rl


@pytest.fixture()
def isolated(monkeypatch):
    """强制走进程内计数，避免测试触碰真实 Redis；前后清空降级桶。"""
    monkeypatch.setattr("app.core.redis_client.get_redis_client", lambda: None)
    rl._guest_quota_memory.clear()
    yield
    rl._guest_quota_memory.clear()


def test_limit_blocks_exactly_after_limit(isolated):
    limit = rl.guest_quota_limit()
    assert limit > 0, "默认应开启游客额度"

    allowed = [
        rl.check_agent_guest_daily_quota("visitor-a", "10.0.0.1").allowed
        for _ in range(limit)
    ]
    assert all(allowed)

    blocked = rl.check_agent_guest_daily_quota("visitor-a", "10.0.0.1")
    assert blocked.allowed is False
    # Retry-After 应是「距北京次日 0 点」的秒数，落在 (0, 一天] 区间
    assert 1 <= blocked.retry_after_seconds <= 24 * 3600 + 60


def test_visitors_are_independent_even_on_same_ip(isolated):
    visitor_id1, visitor_id2, ip = "visitor-b1", "visitor-b2", "10.0.0.2"
    for _ in range(rl.guest_quota_limit()):
        assert rl.check_agent_guest_daily_quota(visitor_id1, ip).allowed

    assert rl.check_agent_guest_daily_quota(visitor_id1, ip).allowed is False
    # 同一出口 IP 下的另一个访客不受影响
    assert rl.check_agent_guest_daily_quota(visitor_id2, ip).allowed is True


def test_falls_back_to_ip_when_visitor_id_missing(isolated):
    ip = "10.0.0.3"
    for _ in range(rl.guest_quota_limit()):
        assert rl.check_agent_guest_daily_quota(None, ip).allowed
    assert rl.check_agent_guest_daily_quota(None, ip).allowed is False
    # 空串等同于没上报
    assert rl.check_agent_guest_daily_quota("", ip).allowed is False
    # 另一个 IP 仍有自己的额度
    assert rl.check_agent_guest_daily_quota(None, "10.0.0.4").allowed is True


def test_zero_limit_disables_quota(isolated, monkeypatch):
    monkeypatch.setattr(rl, "_GUEST_QUOTA_LIMIT", 0)
    assert all(
        rl.check_agent_guest_daily_quota("visitor-d", "10.0.0.5").allowed
        for _ in range(50)
    )


def test_key_contains_beijing_day(isolated):
    day, ttl = rl._beijing_day_and_ttl()
    key = rl._guest_quota_key("visitor-e", "10.0.0.6")
    assert day in key
    assert 60 <= ttl <= 24 * 3600 + 60


def test_visitor_id_is_hashed_not_stored_raw(isolated):
    raw = "visitor-should-not-leak"
    key = rl._guest_quota_key(raw, "10.0.0.7")
    assert raw not in key


class _FakeRequest:
    """只带 cookies 的最小请求替身（has_valid_session 只用到这一项）。"""

    def __init__(self, cookies: dict[str, str]) -> None:
        self.cookies = cookies


@pytest.fixture()
def session_cookie_name():
    from app.core.config import settings

    return settings.session_cookie_name


def test_no_cookie_is_not_a_session(session_cookie_name):
    assert rl.has_valid_session(_FakeRequest({})) is False


def test_bogus_cookie_is_not_a_session(session_cookie_name, monkeypatch):
    """随便塞一个 cgda_session=fake 不能算已登录，否则额度直接被绕过。"""
    monkeypatch.setattr(
        "app.services.session_service.get_session", lambda token: None
    )
    req = _FakeRequest({session_cookie_name: "totally-fake-token"})
    assert rl.has_valid_session(req) is False


def test_real_session_is_recognised(session_cookie_name, monkeypatch):
    monkeypatch.setattr(
        "app.services.session_service.get_session",
        lambda token: {"user_id": 1} if token == "good" else None,
    )
    req = _FakeRequest({session_cookie_name: "good"})
    assert rl.has_valid_session(req) is True


def test_session_lookup_error_falls_back_to_guest(session_cookie_name, monkeypatch):
    """会话存储故障时按游客处理（fail-closed），宁可多限不漏限。"""

    def boom(token):  # noqa: ANN001, ARG001
        raise RuntimeError("redis down")

    monkeypatch.setattr("app.services.session_service.get_session", boom)
    req = _FakeRequest({session_cookie_name: "whatever"})
    assert rl.has_valid_session(req) is False


# ---------------------------------------------------------------------------
# 按角色判定：游客登录用的是共享 demo 账号，它同样有合法会话 Cookie。
# 只看「有没有会话」会把这类请求判成已登录、从而完全不限额——2026-11-08
# 实测确认过（游客登录后 /agent/quota 直接返回 scope=account）。
# ---------------------------------------------------------------------------


def _patch_session(monkeypatch, role_by_token: dict[str, dict]):
    monkeypatch.setattr(
        "app.services.session_service.get_session",
        lambda token: role_by_token.get(token),
    )


def test_guest_login_with_demo_account_still_counts(session_cookie_name, monkeypatch):
    """「以游客身份进入」= demo 会话，必须照样占游客额度。"""
    _patch_session(monkeypatch, {"demo-token": {"user_id": 2, "role": "demo"}})
    req = _FakeRequest({session_cookie_name: "demo-token"})
    assert rl.session_role(req) == "demo"
    assert rl.is_guest_request(req) is True


def test_admin_session_is_exempt(session_cookie_name, monkeypatch):
    _patch_session(monkeypatch, {"admin-token": {"user_id": 1, "role": "admin"}})
    req = _FakeRequest({session_cookie_name: "admin-token"})
    assert rl.session_role(req) == "admin"
    assert rl.is_guest_request(req) is False


def test_standard_session_is_exempt(session_cookie_name, monkeypatch):
    _patch_session(monkeypatch, {"std-token": {"user_id": 3, "role": "standard"}})
    req = _FakeRequest({session_cookie_name: "std-token"})
    assert rl.is_guest_request(req) is False


def test_role_is_case_insensitive(session_cookie_name, monkeypatch):
    _patch_session(monkeypatch, {"t": {"user_id": 2, "role": "DEMO"}})
    req = _FakeRequest({session_cookie_name: "t"})
    assert rl.session_role(req) == "demo"
    assert rl.is_guest_request(req) is True


def test_no_cookie_counts_as_guest(session_cookie_name):
    assert rl.session_role(_FakeRequest({})) is None
    assert rl.is_guest_request(_FakeRequest({})) is True


def test_bogus_cookie_counts_as_guest(session_cookie_name, monkeypatch):
    _patch_session(monkeypatch, {})
    req = _FakeRequest({session_cookie_name: "fake"})
    assert rl.session_role(req) is None
    assert rl.is_guest_request(req) is True


def test_session_without_role_counts_as_guest(session_cookie_name, monkeypatch):
    """会话里没有 role 字段（旧数据）时不能当成免额度账号。"""
    _patch_session(monkeypatch, {"old-token": {"user_id": 9}})
    req = _FakeRequest({session_cookie_name: "old-token"})
    assert rl.session_role(req) is None
    assert rl.is_guest_request(req) is True


def test_session_error_counts_as_guest(session_cookie_name, monkeypatch):
    def boom(token):  # noqa: ANN001, ARG001
        raise RuntimeError("redis down")

    monkeypatch.setattr("app.services.session_service.get_session", boom)
    req = _FakeRequest({session_cookie_name: "whatever"})
    assert rl.session_role(req) is None
    assert rl.is_guest_request(req) is True
