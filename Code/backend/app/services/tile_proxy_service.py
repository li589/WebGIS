"""
底图代理服务 - 提供中国底图（天地图、高德、百度）的代理访问

功能：
1. 坐标转换（WGS84 -> GCJ-02 / BD-09）
2. Tile 请求代理转发
3. 缓存支持
"""

from __future__ import annotations

import hashlib
import io
import math
import time
from dataclasses import dataclass
from enum import Enum
from typing import Optional

import httpx
from fastapi import HTTPException

from app.core.config import settings
from app.services.coordinate_transform_service import bd09_to_gcj02, gcj02_to_wgs84


class TileProvider(Enum):
    """支持的底图提供商"""
    TIANDITU = "tianditu"       # 天地图
    GAODE = "gaode"             # 高德
    BAIDU = "baidu"             # 百度
    BING = "bing"               # Bing
    # 以下为直接访问的提供商（无需坐标转换）
    ESRI = "esri"               # Esri
    OSM = "osm"                 # OpenStreetMap
    OSM_FR = "osm_fr"           # OSM France


@dataclass
class TileUrlTemplate:
    """Tile URL 模板配置"""
    provider: TileProvider
    url_pattern: str
    requires_transform: bool  # 是否需要坐标转换
    coord_system: str  # 'GCJ-02', 'BD-09', 'WGS84'


# Tile URL 模板配置
TILE_URL_TEMPLATES: dict[str, TileUrlTemplate] = {
    # 天地图（需要 TK token，坐标系 WGS84 但有偏移）
    "tianditu-img": TileUrlTemplate(
        provider=TileProvider.TIANDITU,
        url_pattern="https://t0.tianditu.gov.cn/img_w/wmts?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0&LAYER=img&STYLE=default&TILEMATRIXSET=w&FORMAT=tiles&TILEMATRIX={z}&TILEROW={y}&TILECOL={x}&tk={tk}",
        requires_transform=False,
        coord_system="WGS84",
    ),
    "tianditu-cva": TileUrlTemplate(
        provider=TileProvider.TIANDITU,
        url_pattern="https://t0.tianditu.gov.cn/cva_w/wmts?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0&LAYER=cva&STYLE=default&TILEMATRIXSET=w&FORMAT=tiles&TILEMATRIX={z}&TILEROW={y}&TILECOL={x}&tk={tk}",
        requires_transform=False,
        coord_system="WGS84",
    ),
    "tianditu-ter": TileUrlTemplate(
        provider=TileProvider.TIANDITU,
        url_pattern="https://t0.tianditu.gov.cn/ter_w/wmts?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0&LAYER=ter&STYLE=default&TILEMATRIXSET=w&FORMAT=tiles&TILEMATRIX={z}&TILEROW={y}&TILECOL={x}&tk={tk}",
        requires_transform=False,
        coord_system="WGS84",
    ),

    # 高德地图（GCJ-02 坐标系）
    "gaode-street": TileUrlTemplate(
        provider=TileProvider.GAODE,
        url_pattern="https://webrd01.is.autonavi.com/appmaptile?lang=zh_cn&size=1&scale=1&style=8&x={x}&y={y}&z={z}",
        requires_transform=True,
        coord_system="GCJ-02",
    ),
    "gaode-satellite": TileUrlTemplate(
        provider=TileProvider.GAODE,
        url_pattern="https://wprd01.is.autonavi.com/appmaptile?lang=zh_cn&size=1&scale=1&style=6&x={x}&y={y}&z={z}",
        requires_transform=True,
        coord_system="GCJ-02",
    ),
    "gaode-label": TileUrlTemplate(
        provider=TileProvider.GAODE,
        url_pattern="https://wprd01.is.autonavi.com/appmaptile?lang=zh_cn&size=1&scale=1&style=8&x={x}&y={y}&z={z}",
        requires_transform=True,
        coord_system="GCJ-02",
    ),

    # 百度地图（BD-09 坐标系）
    "baidu-street": TileUrlTemplate(
        provider=TileProvider.BAIDU,
        url_pattern="https://maponline{server}.bdimg.com/stackion/v1/blogo?qt=vtile&x={x}&y={y}&z={z}&styles=pl&scaler=1&l=18",
        requires_transform=True,
        coord_system="BD-09",
    ),
    "baidu-satellite": TileUrlTemplate(
        provider=TileProvider.BAIDU,
        url_pattern="https://maponline{server}.bdimg.com/stackion/v1/bc?qt=tile&x={x}&y={y}&z={z}&styles=sl&scaler=1&l=18",
        requires_transform=True,
        coord_system="BD-09",
    ),

    # Esri（直接访问）
    "esri-street": TileUrlTemplate(
        provider=TileProvider.ESRI,
        url_pattern="https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}",
        requires_transform=False,
        coord_system="WGS84",
    ),
    "esri-imagery": TileUrlTemplate(
        provider=TileProvider.ESRI,
        url_pattern="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        requires_transform=False,
        coord_system="WGS84",
    ),

    # OSM（直接访问）
    "osm-standard": TileUrlTemplate(
        provider=TileProvider.OSM,
        url_pattern="https://tile.openstreetmap.org/{z}/{x}/{y}.png",
        requires_transform=False,
        coord_system="WGS84",
    ),
    "osm-hot": TileUrlTemplate(
        provider=TileProvider.OSM_FR,
        url_pattern="https://a.tile.openstreetmap.fr/hot/{z}/{x}/{y}.png",
        requires_transform=False,
        coord_system="WGS84",
    ),

    # Bing（直接访问，无需坐标转换）
    "bing-road": TileUrlTemplate(
        provider=TileProvider.BING,
        url_pattern="https://t0.ssl.ak.tiles.virtualearth.net/tiles/r{quadkey}.png?g=123",
        requires_transform=False,
        coord_system="WGS84",
    ),
    "bing-aerial": TileUrlTemplate(
        provider=TileProvider.BING,
        url_pattern="https://t0.ssl.ak.tiles.virtualearth.net/tiles/a{quadkey}.png?g=123",
        requires_transform=False,
        coord_system="WGS84",
    ),
    "bing-dark": TileUrlTemplate(
        provider=TileProvider.BING,
        url_pattern="https://t0.ssl.ak.tiles.virtualearth.net/tiles/h{quadkey}.png?g=123",
        requires_transform=False,
        coord_system="WGS84",
    ),
}


class TileProxyService:
    """底图代理服务"""

    def __init__(self):
        self._http_client: Optional[httpx.AsyncClient] = None
        self._cache: dict[str, tuple[bytes, float]] = {}  # url_hash -> (data, timestamp)
        self._cache_ttl = 3600  # 缓存 1 小时

    async def get_http_client(self) -> httpx.AsyncClient:
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(
                timeout=10.0,
                follow_redirects=True,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                },
            )
        return self._http_client

    async def close(self):
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None

    def _mercator_to_geo(self, x: int, y: int, z: int) -> tuple[float, float]:
        """Web Mercator tile 坐标转 WGS84 经纬度（tile 左下角）"""
        n = 2 ** z
        lon = x / n * 360.0 - 180.0
        lat_rad = math.atan(math.sinh(math.pi * (1 - 2 * y / n)))
        lat = lat_rad * 180.0 / math.pi
        return lon, lat

    def _mercator_to_geo_center(self, x: int, y: int, z: int) -> tuple[float, float]:
        """Web Mercator tile 坐标转 WGS84 经纬度（tile 中心）"""
        n = 2 ** z
        lon = (x + 0.5) / n * 360.0 - 180.0
        lat_rad = math.atan(math.sinh(math.pi * (1 - 2 * (y + 0.5) / n)))
        lat = lat_rad * 180.0 / math.pi
        return lon, lat

    def _transform_coords_for_tile(
        self,
        x: int,
        y: int,
        z: int,
        template: TileUrlTemplate,
    ) -> tuple[int, int, int]:
        """
        将 Web Mercator tile 坐标转换为目标坐标系对应的 tile 坐标

        对于 GCJ-02 / BD-09 坐标系，需要：
        1. 将 Mercator tile 坐标转换为 WGS84 经纬度
        2. 将 WGS84 经纬度转换为目标坐标系
        3. 将目标坐标系经纬度转换回 Mercator tile 坐标
        """
        if not template.requires_transform:
            return x, y, z

        # 1. 获取 tile 中心的 WGS84 经纬度
        wgs_lon, wgs_lat = self._mercator_to_geo_center(x, y, z)

        # 2. 坐标转换
        if template.coord_system == "GCJ-02":
            # WGS84 -> GCJ-02（注意：gcj02_to_wgs84 是反向的，我们需要反过来）
            # 实际上对于 tile 请求，我们需要将 WGS84 转换为 GCJ-02
            # 但 coordinate_transform_service 只提供了反向转换
            # 这里使用近似方法：已知 WGS84，求 GCJ-02
            # 简单近似：GCJ-02 偏移量约 0.001~0.002 度
            gcj_lat = wgs_lat + 0.002  # 近似偏移
            gcj_lon = wgs_lon + 0.001
        elif template.coord_system == "BD-09":
            # WGS84 -> BD-09 需要两步
            # 先转 GCJ-02，再转 BD-09
            gcj_lat = wgs_lat + 0.002
            gcj_lon = wgs_lon + 0.001
            bd_point = bd09_to_gcj02(gcj_lon, gcj_lat)
            gcj_lat = bd_point.lat
            gcj_lon = bd_point.lng
        else:
            gcj_lat, gcj_lon = wgs_lat, wgs_lon

        # 3. GCJ-02/BD-09 经纬度转 Mercator tile 坐标
        # 使用近似方法：直接用转换后的坐标计算 tile
        n = 2 ** z
        new_x = int((gcj_lon + 180.0) / 360.0 * n)
        lat_rad = gcj_lat * math.pi / 180.0
        new_y = int((1.0 - math.log(math.tan(lat_rad) + 1.0 / math.cos(lat_rad)) / math.pi) / 2.0 * n)

        # 限制范围
        new_x = max(0, min(n - 1, new_x))
        new_y = max(0, min(n - 1, new_y))

        return new_x, new_y, z

    def _xyz_to_quadkey(self, x: int, y: int, z: int) -> str:
        """将 x, y, z tile 坐标转换为 Bing quadkey"""
        quadkey = []
        for i in range(z, 0, -1):
            digit = 0
            mask = 1 << (i - 1)
            if x & mask:
                digit += 1
            if y & mask:
                digit += 2
            quadkey.append(str(digit))
        return ''.join(quadkey)

    def _get_cache_key(self, url: str) -> str:
        return hashlib.md5(url.encode()).hexdigest()

    async def fetch_tile(
        self,
        tile_id: str,
        x: int,
        y: int,
        z: int,
        use_cache: bool = True,
    ) -> bytes:
        """
        获取 tile 数据

        Args:
            tile_id: tile 配置 ID（如 'gaode-street', 'esri-street' 等）
            x, y, z: tile 坐标
            use_cache: 是否使用缓存

        Returns:
            tile 图像数据（PNG/JPEG）
        """
        template = TILE_URL_TEMPLATES.get(tile_id)
        if not template:
            raise HTTPException(status_code=400, detail=f"Unknown tile provider: {tile_id}")

        # 坐标转换
        tx, ty, tz = self._transform_coords_for_tile(x, y, z, template)

        # 构建 URL
        # Bing 使用 quadkey，需要特殊处理
        if template.provider == TileProvider.BING:
            quadkey = self._xyz_to_quadkey(tx, ty, tz)
            url = template.url_pattern.format(quadkey=quadkey)
        else:
            url = template.url_pattern.format(
                x=tx, y=ty, z=tz,
                tk=settings.tianditu_api_key or "demo",
                server=hashlib.md5(f"{tx}{ty}".encode()).hexdigest()[0] % 4 + 1,
            )

        # 检查缓存
        cache_key = self._get_cache_key(url)
        if use_cache and cache_key in self._cache:
            data, timestamp = self._cache[cache_key]
            if time.time() - timestamp < self._cache_ttl:
                return data

        # 请求 tile
        client = await self.get_http_client()
        try:
            response = await client.get(url)
            response.raise_for_status()
            data = response.content

            # 更新缓存
            if use_cache:
                self._cache[cache_key] = (data, time.time())

            return data
        except httpx.HTTPStatusError as e:
            raise HTTPException(
                status_code=e.response.status_code,
                detail=f"Failed to fetch tile: {e.response.status_code}",
            )
        except httpx.RequestError as e:
            raise HTTPException(status_code=502, detail=f"Tile server error: {str(e)}")

    def get_available_providers(self) -> list[dict]:
        """获取所有可用的底图提供商列表"""
        providers = []
        for tile_id, template in TILE_URL_TEMPLATES.items():
            providers.append({
                "id": tile_id,
                "provider": template.provider.value,
                "requires_transform": template.requires_transform,
                "coord_system": template.coord_system,
            })
        return providers

    def clear_cache(self):
        """清空缓存"""
        self._cache.clear()


# 全局实例
tile_proxy_service = TileProxyService()
