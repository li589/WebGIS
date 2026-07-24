"""
底图代理服务 - 提供中国底图（天地图、高德、百度）的代理访问

功能：
1. 坐标转换（WGS84 -> GCJ-02 / BD-09）
2. Tile 请求代理转发
3. 缓存支持
"""

from __future__ import annotations

import hashlib
import math
import time
from collections import OrderedDict
from dataclasses import dataclass
from enum import Enum
from typing import Optional

import httpx
from fastapi import HTTPException

from app.core.config import settings
from app.services.crs import CoordinatePoint
from app.services.crs._gcj_bd import wgs84_to_bd09, wgs84_to_gcj02


class TileProvider(Enum):
    """支持的底图提供商"""

    TIANDITU = "tianditu"  # 天地图
    GAODE = "gaode"  # 高德
    BAIDU = "baidu"  # 百度
    BING = "bing"  # Bing
    # 以下为直接访问的提供商（无需坐标转换）
    ESRI = "esri"  # Esri
    OSM = "osm"  # OpenStreetMap
    OSM_FR = "osm_fr"  # OSM France


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
        url_pattern="https://webrd0{server}.is.autonavi.com/appmaptile?lang=zh_cn&size=1&scale=1&style=8&x={x}&y={y}&z={z}",
        requires_transform=True,
        coord_system="GCJ-02",
    ),
    "gaode-satellite": TileUrlTemplate(
        provider=TileProvider.GAODE,
        url_pattern="https://webst0{server}.is.autonavi.com/appmaptile?style=6&x={x}&y={y}&z={z}",
        requires_transform=True,
        coord_system="GCJ-02",
    ),
    "gaode-label": TileUrlTemplate(
        provider=TileProvider.GAODE,
        url_pattern="https://webst0{server}.is.autonavi.com/appmaptile?style=8&x={x}&y={y}&z={z}",
        requires_transform=True,
        coord_system="GCJ-02",
    ),
    # 百度地图（BD-09 坐标系）
    # 注意：百度 tile 服务器不支持 HTTPS（SSL 握手失败），必须使用 HTTP
    # 百度 tile 服务需要 ak 认证，未配置时返回 503 错误
    "baidu-street": TileUrlTemplate(
        provider=TileProvider.BAIDU,
        url_pattern="http://online{server}.map.bdimg.com/onlinelabel/?qt=tile&x={x}&y={y}&z={z}&styles=pl&scaler=1&p=1&ak={ak}",
        requires_transform=True,
        coord_system="BD-09",
    ),
    "baidu-satellite": TileUrlTemplate(
        provider=TileProvider.BAIDU,
        url_pattern="http://shangetu{server}.map.bdimg.com/it/u=x={x};y={y};z={z};v=009;type=sate&fm=46&ak={ak}",
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
    "esri-terrain": TileUrlTemplate(
        provider=TileProvider.ESRI,
        url_pattern="https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}",
        requires_transform=False,
        coord_system="WGS84",
    ),
    # OSM（直接访问）
    # 注意：tile.openstreetmap.org 在国内网络环境下不可达，改用德国镜像
    "osm-standard": TileUrlTemplate(
        provider=TileProvider.OSM,
        url_pattern="https://tile.openstreetmap.de/{z}/{x}/{y}.png",
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
        url_pattern="https://ecn.t0.tiles.virtualearth.net/tiles/r{quadkey}.png?g=14245",
        requires_transform=False,
        coord_system="WGS84",
    ),
    "bing-aerial": TileUrlTemplate(
        provider=TileProvider.BING,
        url_pattern="https://ecn.t0.tiles.virtualearth.net/tiles/a{quadkey}.png?g=14245",
        requires_transform=False,
        coord_system="WGS84",
    ),
    "bing-dark": TileUrlTemplate(
        provider=TileProvider.BING,
        url_pattern="https://ecn.t0.tiles.virtualearth.net/tiles/h{quadkey}.png?g=14245",
        requires_transform=False,
        coord_system="WGS84",
    ),
    # CARTO（直接访问）
    # 注意：a.basemaps.cartocdn.com 在国内不可达，改用 b 子域名
    "carto-light": TileUrlTemplate(
        provider=TileProvider.OSM,
        url_pattern="https://b.basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png",
        requires_transform=False,
        coord_system="WGS84",
    ),
    "carto-dark": TileUrlTemplate(
        provider=TileProvider.OSM,
        url_pattern="https://b.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png",
        requires_transform=False,
        coord_system="WGS84",
    ),
    # Stadia（已迁移到 PolyMaps，需要 API Key，暂时禁用）
    # "stadia-streets": TileUrlTemplate(
    #     provider=TileProvider.OSM,
    #     url_pattern="https://tiles.stadiamaps.com/tiles/stamen_toner/{z}/{x}/{y}.png",
    #     requires_transform=False,
    #     coord_system="WGS84",
    # ),
    # "stadia-dark": TileUrlTemplate(
    #     provider=TileProvider.OSM,
    #     url_pattern="https://tiles.stadiamaps.com/tiles/alidade_smooth_dark/{z}/{x}/{y}.png",
    #     requires_transform=False,
    #     coord_system="WGS84",
    # ),
    # "stadia-satellite": TileUrlTemplate(
    #     provider=TileProvider.OSM,
    #     url_pattern="https://tiles.stadiamaps.com/tiles/stamen_toner_satellite/{z}/{x}/{y}.png",
    #     requires_transform=False,
    #     coord_system="WGS84",
    # ),
    "esri-dark": TileUrlTemplate(
        provider=TileProvider.ESRI,
        url_pattern="https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}",
        requires_transform=False,
        coord_system="WGS84",
    ),
    "esri-light": TileUrlTemplate(
        provider=TileProvider.ESRI,
        url_pattern="https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}",
        requires_transform=False,
        coord_system="WGS84",
    ),
}


class TileProxyService:
    """底图代理服务"""

    _MAX_CACHE_ENTRIES = 512

    def __init__(self):
        self._http_client: Optional[httpx.AsyncClient] = None
        # OrderedDict LRU：url_hash -> (data, timestamp)
        self._cache: OrderedDict[str, tuple[bytes, float]] = OrderedDict()
        self._cache_ttl = int(
            getattr(settings, "tile_proxy_cache_ttl_seconds", 3600) or 3600
        )

    async def get_http_client(self) -> httpx.AsyncClient:
        if self._http_client is None:
            # 分层超时：连接超时短（5s）让不可达底图快速失败，读取超时长（30s）允许慢速 CDN
            self._http_client = httpx.AsyncClient(
                timeout=httpx.Timeout(connect=5.0, read=30.0, write=10.0, pool=5.0),
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
        n = 2**z
        lon = x / n * 360.0 - 180.0
        lat_rad = math.atan(math.sinh(math.pi * (1 - 2 * y / n)))
        lat = lat_rad * 180.0 / math.pi
        return lon, lat

    def _mercator_to_geo_center(self, x: int, y: int, z: int) -> tuple[float, float]:
        """Web Mercator tile 坐标转 WGS84 经纬度（tile 中心）"""
        n = 2**z
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
            target = wgs84_to_gcj02(wgs_lon, wgs_lat)
            gcj_lon, gcj_lat = target.lng, target.lat
        elif template.coord_system == "BD-09":
            target = wgs84_to_bd09(wgs_lon, wgs_lat)
            gcj_lon, gcj_lat = target.lng, target.lat
        else:
            gcj_lon, gcj_lat = wgs_lon, wgs_lat

        # 3. 将目标坐标系经纬度转换为 Mercator tile 坐标
        merc = self._lonlat_to_mercator(gcj_lon, gcj_lat)
        n = 2**z
        new_x = int((merc.lng + 20037508.342789244) / 20037508.342789244 / 2 * n)
        new_y = int((20037508.342789244 - merc.lat) / 20037508.342789244 / 2 * n)

        # 限制范围
        new_x = max(0, min(n - 1, new_x))
        new_y = max(0, min(n - 1, new_y))

        return new_x, new_y, z

    def _lonlat_to_mercator(self, lng: float, lat: float) -> "CoordinatePoint":
        """经纬度转 Web Mercator"""
        import math

        origin_shift = 20037508.342789244
        max_lat = 85.05112878
        clipped_lat = max(-max_lat, min(max_lat, lat))
        mx = lng * origin_shift / 180.0
        my = (
            math.log(math.tan((90.0 + clipped_lat) * math.pi / 360.0))
            * origin_shift
            / math.pi
        )
        return CoordinatePoint(lng=mx, lat=my)

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
        return "".join(quadkey)

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
            raise HTTPException(
                status_code=400, detail=f"Unknown tile provider: {tile_id}"
            )

        from app.services.config_service import get_effective_api_key

        tianditu_key = get_effective_api_key("tianditu") or ""
        baidu_key = get_effective_api_key("baidu") or ""

        # 天地图需要 API Key（tk），未配置时返回明确错误
        if template.provider == TileProvider.TIANDITU and not tianditu_key:
            raise HTTPException(
                status_code=503,
                detail="天地图需要配置 API Key（设置页或 BACKEND_TIANDITU_API_KEY）。请从 https://console.tianditu.gov.cn/ 申请 Key。",
            )

        # 百度需要 API Key（ak），未配置时返回明确错误（否则百度返回空白 tile）
        if template.provider == TileProvider.BAIDU and not baidu_key:
            raise HTTPException(
                status_code=503,
                detail="百度地图需要配置 API Key（设置页或 BACKEND_BAIDU_API_KEY）。请从 https://lbsyun.baidu.com/ 申请 ak。",
            )

        # 坐标转换
        tx, ty, tz = self._transform_coords_for_tile(x, y, z, template)

        # 构建 URL
        # Bing 使用 quadkey，需要特殊处理
        if template.provider == TileProvider.BING:
            quadkey = self._xyz_to_quadkey(tx, ty, tz)
            url = template.url_pattern.format(quadkey=quadkey)
        else:
            # 只传递模板中需要的参数
            format_args = {"x": tx, "y": ty, "z": tz}
            # 只有天地图模板需要 tk 参数
            if "{tk}" in template.url_pattern:
                format_args["tk"] = tianditu_key
            # 百度模板需要 ak 参数
            if "{ak}" in template.url_pattern:
                format_args["ak"] = baidu_key
            # 高德/百度模板需要 server 子域名编号（1-4），用于负载均衡
            if "{server}" in template.url_pattern:
                # 修复：hexdigest()[0] 是字符串字符，必须先 int(..., 16) 转为整数才能取模
                format_args["server"] = (
                    int(hashlib.md5(f"{tx}{ty}".encode()).hexdigest()[0], 16) % 4 + 1
                )
            url = template.url_pattern.format(**format_args)

        # 检查缓存（LRU）
        cache_key = self._get_cache_key(url)
        if use_cache and cache_key in self._cache:
            data, timestamp = self._cache[cache_key]
            if time.time() - timestamp < self._cache_ttl:
                self._cache.move_to_end(cache_key)
                return data
            self._cache.pop(cache_key, None)

        # 请求 tile
        client = await self.get_http_client()
        try:
            response = await client.get(url)
            response.raise_for_status()
            data = response.content

            # 更新缓存
            if use_cache:
                self._cache[cache_key] = (data, time.time())
                self._cache.move_to_end(cache_key)
                while len(self._cache) > self._MAX_CACHE_ENTRIES:
                    self._cache.popitem(last=False)

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
            providers.append(
                {
                    "id": tile_id,
                    "provider": template.provider.value,
                    "requires_transform": template.requires_transform,
                    "coord_system": template.coord_system,
                }
            )
        return providers

    def clear_cache(self):
        """清空缓存"""
        self._cache.clear()


# 全局实例
tile_proxy_service = TileProxyService()
