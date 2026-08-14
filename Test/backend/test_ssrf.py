"""SSRF 出站校验、重定向再校验（BUG-1）与 DNS 重绑定钉 IP（R1）。"""

from __future__ import annotations

import http.client
import ipaddress
import socket
from email.message import EmailMessage
from io import BytesIO
from unittest.mock import patch

import pytest
from urllib.error import HTTPError
from urllib.request import OpenerDirector

from app.core import ssrf as ssrf_mod
from app.core.ssrf import (
    OutboundTarget,
    SSRFBlockedError,
    resolve_outbound_target,
    safe_urlopen,
    validate_outbound_url,
)

_PUBLIC_IP = "93.184.216.34"


# --------------------------------------------------------------------------
# URL 策略校验
# --------------------------------------------------------------------------


def test_validate_blocks_loopback() -> None:
    with pytest.raises(SSRFBlockedError, match="阻断"):
        validate_outbound_url("http://127.0.0.1:6379/")


def test_validate_blocks_link_local() -> None:
    with pytest.raises(SSRFBlockedError, match="阻断"):
        validate_outbound_url("http://169.254.169.254/latest/meta-data/")


def test_validate_blocks_non_http_scheme() -> None:
    with pytest.raises(SSRFBlockedError, match="协议"):
        validate_outbound_url("file:///etc/passwd")


def test_validate_blocks_empty_resolution(monkeypatch: pytest.MonkeyPatch) -> None:
    """解析结果为空时必须阻断（此前会静默放行）。"""
    monkeypatch.setattr(ssrf_mod, "_iter_resolved_ips", lambda host, port: [])
    with pytest.raises(SSRFBlockedError, match="未解析到可用 IP"):
        validate_outbound_url("http://example.invalid/data")


def test_validate_blocks_private_when_disallowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        ssrf_mod,
        "_iter_resolved_ips",
        lambda host, port: [ipaddress.ip_address("10.1.2.3")],
    )
    with pytest.raises(SSRFBlockedError, match="私网"):
        validate_outbound_url("http://nas.invalid/x", allow_private=False)
    # 默认允许私网（内网数据源场景）
    assert validate_outbound_url("http://nas.invalid/x") == "http://nas.invalid/x"


def test_resolve_returns_validated_ips(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        ssrf_mod,
        "_iter_resolved_ips",
        lambda host, port: [
            ipaddress.ip_address(_PUBLIC_IP),
            ipaddress.ip_address("93.184.216.35"),
        ],
    )
    target = resolve_outbound_target("https://example.invalid/data")
    assert isinstance(target, OutboundTarget)
    assert target.ips == (_PUBLIC_IP, "93.184.216.35")


# --------------------------------------------------------------------------
# R1：DNS 重绑定 —— 连接阶段钉死校验期解析到的 IP
# --------------------------------------------------------------------------


def test_pinned_connection_uses_validated_ip_not_rebound_dns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """校验解析到公网 IP 后，即使 DNS 被改指 127.0.0.1，连接仍走公网 IP。"""
    monkeypatch.setattr(
        ssrf_mod,
        "_iter_resolved_ips",
        lambda host, port: [ipaddress.ip_address(_PUBLIC_IP)],
    )
    target = resolve_outbound_target("http://rebind.invalid/payload")

    captured: dict[str, object] = {}

    def _fake_create_connection(address, *args, **kwargs):  # type: ignore[no-untyped-def]
        captured["address"] = address
        raise OSError("connection refused (test stub)")

    monkeypatch.setattr(socket, "create_connection", _fake_create_connection)

    create = ssrf_mod._pinned_create_connection(target.ips)
    # 调用方传入的是主机名（此时 DNS 已被攻击者改指环回），必须被忽略
    with pytest.raises(OSError):
        create(("rebind.invalid", 80), 5)

    assert captured["address"] == (_PUBLIC_IP, 80)


def test_pinned_connection_falls_back_to_next_ip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """多 A 记录时首个 IP 不可达应回退下一个，保留可用性。"""
    attempts: list[tuple[str, int]] = []
    sentinel = object()

    def _fake_create_connection(address, *args, **kwargs):  # type: ignore[no-untyped-def]
        attempts.append(address)
        if address[0] == "203.0.113.1":
            raise OSError("unreachable")
        return sentinel

    monkeypatch.setattr(socket, "create_connection", _fake_create_connection)

    create = ssrf_mod._pinned_create_connection(("203.0.113.1", "203.0.113.2"))
    assert create(("multi.invalid", 443), 5) is sentinel
    assert attempts == [("203.0.113.1", 443), ("203.0.113.2", 443)]


def test_pinned_factory_preserves_hostname_for_sni() -> None:
    """钉 IP 不能破坏 Host 头与 TLS SNI：conn.host 仍为原主机名。"""
    factory = ssrf_mod._pinned_connection_factory(
        http.client.HTTPSConnection, (_PUBLIC_IP,)
    )
    conn = factory("example.invalid:8443", timeout=5)
    try:
        assert conn.host == "example.invalid"
        assert conn.port == 8443
        assert conn._create_connection is not socket.create_connection
    finally:
        conn.close()


# --------------------------------------------------------------------------
# BUG-1：重定向逐跳再校验
# --------------------------------------------------------------------------


def test_safe_urlopen_blocks_redirect_to_loopback() -> None:
    """外网 URL 302 到 127.0.0.1 必须被阻断。"""
    headers = EmailMessage()
    headers["Location"] = "http://127.0.0.1:9/secret"

    def _open(req, timeout=None):  # type: ignore[no-untyped-def]
        raise HTTPError(req.full_url, 302, "Found", headers, BytesIO(b""))

    call_count = {"n": 0}
    real = resolve_outbound_target

    def _resolve(url: str, *, allow_private: bool = True) -> OutboundTarget:
        call_count["n"] += 1
        if call_count["n"] == 1:
            # 假装初始「外网」主机已通过校验
            return OutboundTarget(url=url, ips=(_PUBLIC_IP,))
        return real(url, allow_private=allow_private)

    opener = OpenerDirector()
    opener.open = _open  # type: ignore[method-assign]

    with (
        patch("app.core.ssrf.resolve_outbound_target", side_effect=_resolve),
        patch("app.core.ssrf.build_opener", return_value=opener),
    ):
        with pytest.raises(SSRFBlockedError, match="阻断|127"):
            safe_urlopen("http://example.invalid/start", timeout=1)


def test_safe_urlopen_rejects_redirect_loop() -> None:
    """重定向次数超限必须阻断。"""
    headers = EmailMessage()
    headers["Location"] = "http://example.invalid/next"

    def _open(req, timeout=None):  # type: ignore[no-untyped-def]
        raise HTTPError(req.full_url, 302, "Found", headers, BytesIO(b""))

    opener = OpenerDirector()
    opener.open = _open  # type: ignore[method-assign]

    with (
        patch(
            "app.core.ssrf.resolve_outbound_target",
            side_effect=lambda u, **kw: OutboundTarget(url=u, ips=(_PUBLIC_IP,)),
        ),
        patch("app.core.ssrf.build_opener", return_value=opener),
    ):
        with pytest.raises(SSRFBlockedError, match="重定向超过上限"):
            safe_urlopen("http://example.invalid/start", timeout=1, max_redirects=2)


def test_safe_urlopen_success_no_redirect() -> None:
    body = b"ok-payload"

    class _Resp:
        headers = EmailMessage()

        def read(self) -> bytes:
            return body

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def close(self) -> None:
            return None

    opener = OpenerDirector()
    opener.open = lambda req, timeout=None: _Resp()  # type: ignore[method-assign]

    with (
        patch(
            "app.core.ssrf.resolve_outbound_target",
            side_effect=lambda u, **kw: OutboundTarget(url=u, ips=(_PUBLIC_IP,)),
        ),
        patch("app.core.ssrf.build_opener", return_value=opener),
    ):
        with safe_urlopen("http://example.invalid/data", timeout=1) as resp:
            assert resp.read() == body


def test_build_pinned_opener_blocks_proxy_by_default() -> None:
    target = OutboundTarget(url="http://example.invalid/data", ips=(_PUBLIC_IP,))
    with patch("app.core.ssrf.getproxies", return_value={"http": "http://127.0.0.1:8888"}):
        with pytest.raises(SSRFBlockedError, match="fail-closed"):
            ssrf_mod._build_pinned_opener(target)


def test_build_pinned_opener_allows_proxy_when_explicit() -> None:
    target = OutboundTarget(url="http://example.invalid/data", ips=(_PUBLIC_IP,))
    with patch("app.core.ssrf.getproxies", return_value={"http": "http://127.0.0.1:8888"}):
        opener = ssrf_mod._build_pinned_opener(target, allow_proxy=True)
        assert isinstance(opener, OpenerDirector)


def test_is_trusted_open_meteo_local_url() -> None:
    from app.core.ssrf import is_trusted_open_meteo_local_url
    from app.weatherengine.provider_ids import OPEN_METEO_LOCAL_URL

    assert is_trusted_open_meteo_local_url(
        f"{OPEN_METEO_LOCAL_URL}?latitude=0&longitude=0"
    )
    assert not is_trusted_open_meteo_local_url("https://api.open-meteo.com/v1/forecast")


def test_validate_url_for_storage_http_only() -> None:
    from app.core.ssrf import validate_url_for_storage

    assert (
        validate_url_for_storage("https://nomads.ncep.noaa.gov/")
        == "https://nomads.ncep.noaa.gov/"
    )
    with pytest.raises(ValueError, match="http or https"):
        validate_url_for_storage("smb://nas/share/a.h5")
    with pytest.raises(ValueError, match="javascript|http or https"):
        validate_url_for_storage("javascript:alert(1)")


def test_validate_data_source_uri_for_storage_allows_platform_schemes() -> None:
    from app.core.ssrf import validate_data_source_uri_for_storage

    assert (
        validate_data_source_uri_for_storage("smb://nas/share/a.h5?cred=nas-lab")
        == "smb://nas/share/a.h5?cred=nas-lab"
    )
    assert (
        validate_data_source_uri_for_storage("file:///C:/data/x.tif")
        == "file:///C:/data/x.tif"
    )
    with pytest.raises(ValueError, match="scheme"):
        validate_data_source_uri_for_storage("javascript:alert(1)")
