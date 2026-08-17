"""TileProxyService 重定向 SSRF 防护测试（Wave 1 / G1-02）。

验证：
1. httpx 客户端禁用自动重定向（follow_redirects=False）
2. 重定向到环回地址被 resolve_outbound_target 实际策略阻断
3. 重定向到私网地址被阻断（底图上游为公网 CDN，allow_private=False）
4. 校验通过的重定向正常跟随，且最多 _MAX_REDIRECT_HOPS 跳
5. 302 缺 Location / 超跳数 → TileProxyUpstreamError（不暴露上游 URL）
6. 正常 200 直接返回不受影响
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import httpx
import pytest


class _FakeResponse:
    """最小 httpx.Response 替身（fetch_tile 只用到这些成员）。"""

    def __init__(
        self,
        status_code: int,
        headers: dict[str, str] | None = None,
        content: bytes = b"",
    ):
        self.status_code = status_code
        self.headers = httpx.Headers(headers or {})
        self.content = content

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"HTTP {self.status_code}",
                request=httpx.Request("GET", "https://tile.example.internal/0/0/0.png"),
                response=httpx.Response(self.status_code),
            )

    async def aclose(self) -> None:
        pass


def _client_returning(*responses: _FakeResponse) -> AsyncMock:
    client = AsyncMock()
    client.get = AsyncMock(side_effect=list(responses))
    return client


def _client_always(response_factory) -> AsyncMock:
    client = AsyncMock()
    client.get = AsyncMock(side_effect=lambda *_a, **_k: response_factory())
    return client


def _patch_common(fake_client: AsyncMock):
    from app.services.tile_proxy_service import TileProxyService

    return (
        patch(
            "app.services.config_service.get_effective_api_key",
            return_value="test-key",
        ),
        patch.object(
            TileProxyService,
            "get_http_client",
            AsyncMock(return_value=fake_client),
        ),
    )


def test_http_client_disables_auto_redirect() -> None:
    """客户端必须关闭自动重定向，改由服务层逐跳校验。"""
    from app.services.tile_proxy_service import TileProxyService

    svc = TileProxyService()

    async def run() -> None:
        client = await svc.get_http_client()
        try:
            assert client.follow_redirects is False
        finally:
            await svc.close()

    asyncio.run(run())


def test_fetch_tile_returns_200_without_redirect() -> None:
    from app.services.tile_proxy_service import TileProxyService

    svc = TileProxyService()
    fake = _client_returning(_FakeResponse(200, content=b"PNGDATA"))
    p1, p2 = _patch_common(fake)
    with p1, p2:
        data = asyncio.run(svc.fetch_tile("osm-standard", 5, 25, 12, use_cache=False))
    assert data == b"PNGDATA"
    fake.get.assert_awaited_once()


def test_fetch_tile_blocks_redirect_to_loopback() -> None:
    """302 → 127.0.0.1 必须被真实 SSRF 策略阻断，且不发起第二次请求。"""
    from app.services.errors import TileProxyUpstreamError
    from app.services.tile_proxy_service import TileProxyService

    svc = TileProxyService()
    fake = _client_returning(
        _FakeResponse(302, {"location": "http://127.0.0.1:6379/a.png"})
    )
    p1, p2 = _patch_common(fake)
    with p1, p2, pytest.raises(TileProxyUpstreamError, match="redirect"):
        asyncio.run(svc.fetch_tile("osm-standard", 5, 25, 12, use_cache=False))
    fake.get.assert_awaited_once()


def test_fetch_tile_blocks_redirect_to_private_ip() -> None:
    """底图上游均为公网 CDN：重定向进私网必为异常，必须阻断。"""
    from app.services.errors import TileProxyUpstreamError
    from app.services.tile_proxy_service import TileProxyService

    svc = TileProxyService()
    fake = _client_returning(
        _FakeResponse(302, {"location": "http://192.168.1.10/a.png"})
    )
    p1, p2 = _patch_common(fake)
    with p1, p2, pytest.raises(TileProxyUpstreamError, match="redirect"):
        asyncio.run(svc.fetch_tile("osm-standard", 5, 25, 12, use_cache=False))
    fake.get.assert_awaited_once()


def test_fetch_tile_follows_validated_redirect() -> None:
    """校验通过的重定向应跟随，并请求 Location 目标。"""
    from app.core.ssrf import OutboundTarget
    from app.services.tile_proxy_service import TileProxyService

    redirect_target = "https://cdn.example.org/tiles/5/25/12.png"
    svc = TileProxyService()
    fake = _client_returning(
        _FakeResponse(302, {"location": redirect_target}),
        _FakeResponse(200, content=b"REDIRECTED"),
    )
    p1, p2 = _patch_common(fake)
    with (
        p1,
        p2,
        patch(
            "app.services.tile_proxy_service.resolve_outbound_target",
            return_value=OutboundTarget(url=redirect_target, ips=("203.0.113.10",)),
        ),
    ):
        data = asyncio.run(svc.fetch_tile("osm-standard", 5, 25, 12, use_cache=False))
    assert data == b"REDIRECTED"
    assert fake.get.await_count == 2
    assert fake.get.await_args_list[1].args[0] == redirect_target


def test_fetch_tile_redirect_loop_exceeds_hop_limit() -> None:
    """无限重定向循环必须在上限跳数后终止。"""
    from app.core.ssrf import OutboundTarget
    from app.services.errors import TileProxyUpstreamError
    from app.services.tile_proxy_service import (
        TileProxyService,
        _MAX_REDIRECT_HOPS,
    )

    svc = TileProxyService()
    fake = _client_always(
        lambda: _FakeResponse(302, {"location": "https://cdn.example.org/loop.png"})
    )
    p1, p2 = _patch_common(fake)
    with (
        p1,
        p2,
        patch(
            "app.services.tile_proxy_service.resolve_outbound_target",
            return_value=OutboundTarget(
                url="https://cdn.example.org/loop.png", ips=("203.0.113.10",)
            ),
        ),
        pytest.raises(TileProxyUpstreamError, match="redirect"),
    ):
        asyncio.run(svc.fetch_tile("osm-standard", 5, 25, 12, use_cache=False))
    assert fake.get.await_count == _MAX_REDIRECT_HOPS + 1


def test_fetch_tile_redirect_without_location_rejected() -> None:
    """302 缺 Location 头必须显式报错而非静默返回空 tile。"""
    from app.services.errors import TileProxyUpstreamError
    from app.services.tile_proxy_service import TileProxyService

    svc = TileProxyService()
    fake = _client_returning(_FakeResponse(302))
    p1, p2 = _patch_common(fake)
    with p1, p2, pytest.raises(TileProxyUpstreamError, match="Location"):
        asyncio.run(svc.fetch_tile("osm-standard", 5, 25, 12, use_cache=False))
    fake.get.assert_awaited_once()
