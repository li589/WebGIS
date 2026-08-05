"""出站请求 SSRF 防护（发布就绪 P0-2）。

为后端发起的出站 HTTP(S) 请求提供统一的 URL 安全校验，阻断服务器端请求伪造
（SSRF）最常见的高危目标：环回地址（本机 Redis/MinIO/服务）、链路本地地址
（云元数据 169.254.169.254 等）、保留/组播/未指定地址。

设计取舍：默认**不**阻断 RFC1918 私网地址（10/8、172.16/12、192.168/16），
因为本平台存在合法的"内网数据源 / NAS / 局域网文件服务"出站场景。需要更严格
时可通过 ``validate_outbound_url(..., allow_private=False)`` 收紧。

审查修复（BUG-1）：``safe_urlopen`` 对每次重定向目标再跑校验，避免
``urlopen`` 默认跟随 3xx 绕过到环回/链路本地。

审查修复（R1，DNS 重绑定 / TOCTOU）：校验与连接之间存在二次 DNS 解析窗口，
攻击者控制权威 DNS 时可让校验解析到公网 IP、实际连接解析到 ``127.0.0.1``。
现改为**解析一次、钉死 IP 连接**：``resolve_outbound_target`` 返回校验通过的
IP 列表，连接阶段只允许连这些 IP（``_pinned_create_connection``），而 ``Host``
头与 TLS SNI 仍使用原主机名，证书校验不受影响。
"""

from __future__ import annotations

import http.client
import ipaddress
import logging
import socket
from dataclasses import dataclass
from typing import Any, Callable, Mapping
from urllib.error import HTTPError
from urllib.parse import urljoin, urlparse
from urllib.request import (
    HTTPHandler,
    HTTPRedirectHandler,
    HTTPSHandler,
    OpenerDirector,
    Request,
    build_opener,
    getproxies,
)

logger = logging.getLogger(__name__)

_ALLOWED_SCHEMES = {"http", "https"}
_REDIRECT_STATUS = frozenset({301, 302, 303, 307, 308})


class SSRFBlockedError(ValueError):
    """出站 URL 被 SSRF 防护策略阻断。"""


@dataclass(frozen=True)
class OutboundTarget:
    """已通过 SSRF 校验的出站目标。

    Attributes:
        url: 校验通过的 URL（原样返回）。
        ips: 校验时解析到的 IP 字符串列表；连接阶段只允许连这些 IP，
            以消除「校验后再解析」的 DNS 重绑定窗口。
    """

    url: str
    ips: tuple[str, ...]


def _iter_resolved_ips(host: str, port: int) -> list[ipaddress._BaseAddress]:
    """解析主机名到 IP 列表；解析失败抛 SSRFBlockedError。"""
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise SSRFBlockedError(f"无法解析出站主机: {host!r}") from exc
    ips: list[ipaddress._BaseAddress] = []
    for info in infos:
        try:
            ips.append(ipaddress.ip_address(info[4][0]))
        except ValueError:
            continue
    return ips


def _assert_ip_allowed(
    ip: ipaddress._BaseAddress, host: str, *, allow_private: bool
) -> None:
    """单个 IP 的策略判定；命中黑名单即抛 SSRFBlockedError。"""
    if (
        ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    ):
        logger.warning("SSRF 阻断出站请求 host=%r ip=%s", host, ip)
        raise SSRFBlockedError(f"阻断出站地址 {ip}（主机 {host!r}）")
    if ip.is_private and not allow_private:
        logger.warning("SSRF 阻断私网出站请求 host=%r ip=%s", host, ip)
        raise SSRFBlockedError(f"阻断私网出站地址 {ip}（主机 {host!r}）")


def resolve_outbound_target(url: str, *, allow_private: bool = True) -> OutboundTarget:
    """校验出站 URL 并返回「URL + 已校验 IP 列表」。

    与 :func:`validate_outbound_url` 的区别：本函数把解析结果带出来，供连接阶段
    钉死使用，从而关闭 DNS 重绑定窗口。

    Args:
        url: 目标 URL。
        allow_private: 是否允许 RFC1918 私网地址（默认 True，兼容内网数据源）。
            环回 / 链路本地 / 保留 / 组播 / 未指定地址始终被阻断。

    Returns:
        OutboundTarget：校验通过的 URL 与其解析到的全部 IP。

    Raises:
        SSRFBlockedError: 协议非 http/https、无主机、解析失败/为空，
            或任一解析结果命中被阻断地址。
    """
    parsed = urlparse(url)
    scheme = (parsed.scheme or "").lower()
    if scheme not in _ALLOWED_SCHEMES:
        raise SSRFBlockedError(f"不允许的出站协议: {scheme!r}（仅 http/https）")
    host = parsed.hostname
    if not host:
        raise SSRFBlockedError("出站 URL 缺少主机名")

    port = parsed.port or (443 if scheme == "https" else 80)
    ips = _iter_resolved_ips(host, port)
    if not ips:
        # 防御性：getaddrinfo 返回空/全部不可解析时，此前会「静默放行」。
        raise SSRFBlockedError(f"出站主机未解析到可用 IP: {host!r}")
    for ip in ips:
        _assert_ip_allowed(ip, host, allow_private=allow_private)
    return OutboundTarget(url=url, ips=tuple(str(ip) for ip in ips))


def validate_outbound_url(url: str, *, allow_private: bool = True) -> str:
    """校验出站 URL 是否允许发起请求（兼容旧调用点）。

    Returns:
        原始 url（校验通过）。

    Raises:
        SSRFBlockedError: 见 :func:`resolve_outbound_target`。
    """
    return resolve_outbound_target(url, allow_private=allow_private).url


class _NoRedirectHandler(HTTPRedirectHandler):
    """禁止 urllib 自动跟随重定向，交由 safe_urlopen 手工校验后再跟。"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        return None


def _pinned_create_connection(ips: tuple[str, ...]) -> Callable[..., socket.socket]:
    """生成只连指定 IP 的 ``create_connection`` 替身。

    忽略调用方传入地址元组中的主机名，改用校验阶段得到的 IP，按顺序重试以保留
    多 A 记录的可用性；端口沿用原值。
    """

    def _create(address: tuple[str, int], *args: Any, **kwargs: Any) -> socket.socket:
        _, port = address
        last_exc: OSError | None = None
        for ip in ips:
            try:
                return socket.create_connection((ip, port), *args, **kwargs)
            except OSError as exc:
                last_exc = exc
        if last_exc is not None:
            raise last_exc
        raise OSError(f"无可用的已校验出站 IP: {ips!r}")

    return _create


def _pinned_connection_factory(
    base_cls: type[http.client.HTTPConnection], ips: tuple[str, ...]
) -> Callable[..., http.client.HTTPConnection]:
    """返回连接工厂：构造 ``base_cls`` 并把底层连接钉死到已校验 IP。

    ``self.host`` 保持原主机名，因此 ``Host`` 请求头与 TLS SNI / 证书校验均正确。
    """

    def _factory(host: str, **kwargs: Any) -> http.client.HTTPConnection:
        conn = base_cls(host, **kwargs)
        conn._create_connection = _pinned_create_connection(ips)  # type: ignore[method-assign]
        return conn

    return _factory


class _PinnedHTTPHandler(HTTPHandler):
    """http:// 走已校验 IP。"""

    def __init__(self, ips: tuple[str, ...]) -> None:
        super().__init__()
        self._ips = ips

    def http_open(self, req):  # type: ignore[no-untyped-def]
        return self.do_open(
            _pinned_connection_factory(http.client.HTTPConnection, self._ips), req
        )


class _PinnedHTTPSHandler(HTTPSHandler):
    """https:// 走已校验 IP（SNI / 证书仍按主机名校验）。"""

    def __init__(self, ips: tuple[str, ...]) -> None:
        super().__init__()
        self._ips = ips

    def https_open(self, req):  # type: ignore[no-untyped-def]
        return self.do_open(
            _pinned_connection_factory(http.client.HTTPSConnection, self._ips),
            req,
            context=self._context,
        )


def _build_pinned_opener(target: OutboundTarget) -> OpenerDirector:
    """构造禁跟随重定向 + IP 钉死的 opener。

    若环境配置了 HTTP(S) 代理，实际连接目标是代理而非原主机，钉 IP 会失效甚至
    连不通；此时降级为「仅 URL 校验」并告警（代理链路的出站管控应由代理负责）。
    """
    scheme = (urlparse(target.url).scheme or "").lower()
    if getproxies().get(scheme):
        logger.warning(
            "检测到 %s 代理配置，跳过出站 IP 钉死（DNS 重绑定防护降级为仅 URL 校验）",
            scheme,
        )
        return build_opener(_NoRedirectHandler(), HTTPSHandler())
    return build_opener(
        _NoRedirectHandler(),
        _PinnedHTTPHandler(target.ips),
        _PinnedHTTPSHandler(target.ips),
    )


def safe_urlopen(
    url: str,
    *,
    timeout: float,
    headers: Mapping[str, str] | None = None,
    allow_private: bool = True,
    max_redirects: int = 5,
):
    """带 SSRF 校验的 urlopen；每跳重定向再校验，且连接钉死已校验 IP。

    Returns:
        最终响应对象（调用方负责 ``.read()`` / ``.close()``，或 ``with`` 使用）。

    Raises:
        SSRFBlockedError: 初始或重定向 URL 被阻断，或重定向次数超限。
        HTTPError / URLError: 网络或非重定向 HTTP 错误（透传）。
    """
    target = resolve_outbound_target(url, allow_private=allow_private)
    redirects = 0
    req_headers = dict(headers or {})

    while True:
        # 每跳目标主机不同，opener 需按当次已校验 IP 重建。
        opener = _build_pinned_opener(target)
        req = Request(target.url, headers=req_headers)
        try:
            # noqa: S310 — URL 经 resolve_outbound_target 校验；重定向亦同
            return opener.open(req, timeout=timeout)
        except HTTPError as exc:
            if exc.code not in _REDIRECT_STATUS:
                raise
            location = exc.headers.get("Location") if exc.headers else None
            try:
                exc.close()
            except Exception:  # pragma: no cover - best-effort
                pass
            if not location:
                raise SSRFBlockedError(
                    f"重定向响应缺少 Location（status={exc.code}）"
                ) from exc
            redirects += 1
            if redirects > max_redirects:
                raise SSRFBlockedError(
                    f"出站重定向超过上限（max_redirects={max_redirects}）"
                ) from exc
            next_url = urljoin(target.url, location)
            logger.info(
                "SSRF-safe redirect %s -> %s (hop=%d)",
                target.url,
                next_url,
                redirects,
            )
            target = resolve_outbound_target(next_url, allow_private=allow_private)
