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


# ---------------------------------------------------------------------------
# 三道闸：访客号 20 / 同 IP 100 / 全站 300（2026-11-08 新增）
# ---------------------------------------------------------------------------
# 防的是「清 localStorage 换个新访客号」这种绕过：第一道按浏览器记，清一下即
# 清零；所以补第二道绑网络、第三道绑全站。这里把上限压小以便快速触顶。


@pytest.fixture()
def small_limits(isolated, monkeypatch):
    """把三道闸压到 2 / 5 / 7，方便几次调用就触顶。"""
    monkeypatch.setattr(rl, "_GUEST_QUOTA_LIMIT", 2)
    monkeypatch.setattr(rl, "_GUEST_IP_QUOTA_LIMIT", 5)
    monkeypatch.setattr(rl, "_GUEST_GLOBAL_QUOTA_LIMIT", 7)
    return {"visitor": 2, "ip": 5, "global": 7}


def test_layer_blocks_on_visitor_quota(small_limits):
    for _ in range(small_limits["visitor"]):
        result, scope = rl.check_agent_guest_quota_layers("v1", "1.1.1.1")
        assert result.allowed is True
        assert scope is None

    result, scope = rl.check_agent_guest_quota_layers("v1", "1.1.1.1")
    assert result.allowed is False
    assert scope == rl.QUOTA_SCOPE_VISITOR
    assert 1 <= result.retry_after_seconds <= 24 * 3600 + 60


def test_same_ip_caps_across_browsers(small_limits):
    """换新访客号（＝清 localStorage）也突破不了同 IP 上限。"""
    ip = "1.1.1.2"
    for i in range(small_limits["visitor"]):
        assert rl.check_agent_guest_quota_layers(f"browser-{i}a", ip)[0].allowed
        assert rl.check_agent_guest_quota_layers(f"browser-{i}b", ip)[0].allowed

    # 已用 4 次（IP 上限 5），新浏览器还能用 1 次
    assert rl.check_agent_guest_quota_layers("browser-fresh", ip)[0].allowed

    # 第 6 次开始被 IP 那道挡住，且报的是 ip 而不是 visitor
    result, scope = rl.check_agent_guest_quota_layers("browser-newer", ip)
    assert result.allowed is False
    assert scope == rl.QUOTA_SCOPE_IP


def test_global_cap_across_ips(small_limits):
    """换 IP 也突破不了全站总量。"""
    used = 0
    ip_idx = 0
    while used < small_limits["global"]:
        ip = f"9.9.9.{ip_idx}"
        ip_idx += 1
        for i in range(small_limits["visitor"]):
            if used >= small_limits["global"]:
                break
            assert rl.check_agent_guest_quota_layers(f"g-{used}", ip)[0].allowed
            used += 1
            if used % small_limits["visitor"] == 0:
                break

    result, scope = rl.check_agent_guest_quota_layers("g-overflow", "9.9.9.99")
    assert result.allowed is False
    assert scope == rl.QUOTA_SCOPE_GLOBAL


def test_blocked_request_does_not_consume_other_layers(small_limits):
    """被后一道拦下时，前面几道不该白掉一次额度（先预检、后统一计数）。"""
    ip = "1.1.1.30"
    used = 0
    idx = 0
    while used < small_limits["ip"]:
        # 每个访客最多 2 次（visitor 上限），轮流换号把 IP 额度用满
        allowed, _scope = rl.check_agent_guest_quota_layers(f"ipfill-{idx}", ip)
        assert allowed.allowed is True
        used += 1
        if used % small_limits["visitor"] == 0:
            idx += 1

    # IP 已满：新访客号这一次被拒，但它的访客桶应该还是 0
    result, scope = rl.check_agent_guest_quota_layers("unlucky", ip)
    assert (result.allowed, scope) == (False, rl.QUOTA_SCOPE_IP)

    peeked = rl.peek_agent_guest_quota_layers("unlucky", ip)
    assert peeked[rl.QUOTA_SCOPE_VISITOR] == (0, small_limits["visitor"])


def test_disabled_layer_is_skipped(small_limits, monkeypatch):
    monkeypatch.setattr(rl, "_GUEST_IP_QUOTA_LIMIT", 0)
    monkeypatch.setattr(rl, "_GUEST_GLOBAL_QUOTA_LIMIT", 0)
    peeked = rl.peek_agent_guest_quota_layers("v-solo", "9.9.9.50")
    assert set(peeked) == {rl.QUOTA_SCOPE_VISITOR}
    # 只剩访客号一道时，同一 IP 上的另一个访客不受影响
    for _ in range(small_limits["visitor"]):
        assert rl.check_agent_guest_quota_layers("v-solo", "9.9.9.50")[0].allowed
    assert rl.check_agent_guest_quota_layers("v-solo", "9.9.9.50")[0].allowed is False
    assert rl.check_agent_guest_quota_layers("v-other", "9.9.9.50")[0].allowed is True


def test_internal_ip_skips_ip_layer(small_limits):
    """拿不到真实 IP（内网/回环/解析不出）时不能拿它当桶。

    否则一旦代理链丢头，全站访客会挤进同一个 IP 桶，100 次瞬间耗光、整站变砖。
    """
    for weird in ("172.20.0.1", "127.0.0.1", "192.168.1.5", "testclient", ""):
        peeked = rl.peek_agent_guest_quota_layers("v-int", weird)
        assert rl.QUOTA_SCOPE_IP not in peeked, weird

    # 访客号那道照样生效
    for _ in range(small_limits["visitor"]):
        assert rl.check_agent_guest_quota_layers("v-int", "172.20.0.1")[0].allowed
    assert rl.check_agent_guest_quota_layers("v-int", "172.20.0.1")[0].allowed is False


def test_public_ip_keeps_ip_layer(small_limits):
    peeked = rl.peek_agent_guest_quota_layers("v-pub", "1.1.1.77")
    assert peeked[rl.QUOTA_SCOPE_IP] == (0, small_limits["ip"])


def test_ip_key_is_hashed_and_dated(isolated):
    ip = "1.1.1.77"
    key = rl._guest_ip_quota_key(ip)
    day, _ttl = rl._beijing_day_and_ttl()
    assert ip not in key, "IP 不应明文进 Redis 键"
    assert day in key
    assert key != rl._guest_global_quota_key()


class _FakeIpRequest:
    """带 headers / client 的请求替身（client_ip 只用到这两项）。"""

    def __init__(self, headers: dict[str, str], peer: str = "172.20.0.1") -> None:
        self.headers = headers
        self.client = type("C", (), {"host": peer})()


def test_client_ip_prefers_gateway_real_ip(monkeypatch):
    """信任代理时优先读网关写的 X-Real-IP；XFF 首段可被客户端伪造，不采信。"""
    import types

    monkeypatch.setattr(
        "app.core.config.settings", types.SimpleNamespace(trust_proxy=True)
    )
    req = _FakeIpRequest(
        {
            "x-real-ip": "203.0.113.5",
            "x-forwarded-for": "1.2.3.4, 203.0.113.5",
        }
    )
    assert rl.client_ip(req) == "203.0.113.5"


def test_client_ip_ignores_headers_when_proxy_untrusted(monkeypatch):
    import types

    monkeypatch.setattr(
        "app.core.config.settings", types.SimpleNamespace(trust_proxy=False)
    )
    req = _FakeIpRequest({"x-real-ip": "203.0.113.5"})
    assert rl.client_ip(req) == "172.20.0.1"
