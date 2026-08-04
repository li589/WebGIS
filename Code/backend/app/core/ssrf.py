"""出站请求 SSRF 防护（发布就绪 P0-2）。

为后端发起的出站 HTTP(S) 请求提供统一的 URL 安全校验，阻断服务器端请求伪造
（SSRF）最常见的高危目标：环回地址（本机 Redis/MinIO/服务）、链路本地地址
（云元数据 169.254.169.254 等）、保留/组播/未指定地址。

设计取舍：默认**不**阻断 RFC1918 私网地址（10/8、172.16/12、192.168/16），
因为本平台存在合法的"内网数据源 / NAS / 局域网文件服务"出站场景。需要更严格
时可通过 ``validate_outbound_url(..., allow_private=False)`` 收紧。
"""

from __future__ import annotations

import ipaddress
import logging
import socket
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

_ALLOWED_SCHEMES = {"http", "https"}


class SSRFBlockedError(ValueError):
    """出站 URL 被 SSRF 防护策略阻断。"""


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


def validate_outbound_url(url: str, *, allow_private: bool = True) -> str:
    """校验出站 URL 是否允许发起请求。

    Args:
        url: 目标 URL。
        allow_private: 是否允许 RFC1918 私网地址（默认 True，兼容内网数据源）。
            环回 / 链路本地 / 保留 / 组播 / 未指定地址始终被阻断。

    Returns:
        原始 url（校验通过）。

    Raises:
        SSRFBlockedError: 协议非 http/https、无主机、解析失败或命中被阻断地址。
    """
    parsed = urlparse(url)
    scheme = (parsed.scheme or "").lower()
    if scheme not in _ALLOWED_SCHEMES:
        raise SSRFBlockedError(f"不允许的出站协议: {scheme!r}（仅 http/https）")
    host = parsed.hostname
    if not host:
        raise SSRFBlockedError("出站 URL 缺少主机名")

    port = parsed.port or (443 if scheme == "https" else 80)
    for ip in _iter_resolved_ips(host, port):
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
    return url
