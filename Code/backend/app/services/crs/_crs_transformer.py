"""CRS 转换器 — pyproj 包装 + GCJ-02/BD-09 委托 + 偏移应用。

设计要点：
- 类级 LRU 缓存 ``_CACHE`` 按 ``(source_code, target_code)`` 缓存 pyproj.Transformer
- 加密坐标系（GCJ02/BD09）路由到 ``_gcj_bd`` 模块，不走 pyproj
- ``always_xy=True`` 因代码库统一用 (lng, lat) 顺序（pyproj 默认是 (lat, lon)）
- 偏移在 CRS 转换**之后**应用（per user spec "在此基础上引入了偏移"）
- 模块级单例 ``crs_transformer``

使用示例::

    from app.services.crs import crs_transformer
    pt = crs_transformer.transform_point(116.39747, 39.9088, 'GCJ02', 'EPSG:4326')
    # CoordinatePoint(lng=116.391226, lat=39.907397)
"""
from __future__ import annotations

from typing import Iterable

from . import _gcj_bd
from .crs_registry import get_crs
from .crs_types import CRSCategory, CoordinatePoint


class CRSTransformer:
    """CRS 转换器（pyproj + GCJ-02/BD-09 + 偏移）。

    线程安全：pyproj.Transformer 实例本身线程安全，缓存可跨线程共享。
    """

    # 类级 LRU 缓存：key = (source_code, target_code)，value = pyproj.Transformer
    # 加密系（GCJ02/BD09）不缓存（走纯 Python 算法，无 Transformer 实例）
    _CACHE: dict[tuple[str, str], "object"] = {}

    # ── 公共 API ─────────────────────────────────────────────────────────

    def transform_point(
        self,
        lng: float,
        lat: float,
        source_code: str,
        target_code: str,
        lng_offset: float = 0.0,
        lat_offset: float = 0.0,
    ) -> CoordinatePoint:
        """转换单点 (lng, lat) 从 source_code 到 target_code。

        Args:
            lng: 经度（或源投影 X）
            lat: 纬度（或源投影 Y）
            source_code: 源 CRS code（如 'EPSG:4326'、'GCJ02'）
            target_code: 目标 CRS code
            lng_offset: 经度方向偏移（在 CRS 转换**后**应用，单位与 target_code 一致）
            lat_offset: 纬度方向偏移（同上）

        Returns:
            转换后的 ``CoordinatePoint(lng, lat)``
        """
        # source == target：跳过 CRS 转换，仅应用偏移
        if source_code == target_code:
            return CoordinatePoint(lng=lng + lng_offset, lat=lat + lat_offset)

        src_encrypted = self._is_encrypted(source_code)
        tgt_encrypted = self._is_encrypted(target_code)

        if src_encrypted or tgt_encrypted:
            x, y = self._transform_encrypted(lng, lat, source_code, target_code)
        else:
            transformer = self._get_transformer(source_code, target_code)
            x, y = transformer.transform(lng, lat)

        # 偏移在 CRS 转换后应用
        return CoordinatePoint(lng=x + lng_offset, lat=y + lat_offset)

    def transform_bounds(
        self,
        west: float,
        south: float,
        east: float,
        north: float,
        source_code: str,
        target_code: str,
    ) -> tuple[float, float, float, float]:
        """转换 bounds 从 source_code 到 target_code。

        委托 ``rasterio.warp.transform_bounds``（与 ``universal_reader.py:374`` 一致），
        加密系先逐角点转 WGS84 再走 rasterio。

        Args:
            west, south, east, north: 源 bounds
            source_code, target_code: 源/目标 CRS code

        Returns:
            ``(west, south, east, north)`` 目标 bounds
        """
        if source_code == target_code:
            return (west, south, east, north)

        src_encrypted = self._is_encrypted(source_code)
        tgt_encrypted = self._is_encrypted(target_code)

        if src_encrypted and tgt_encrypted:
            # 加密系 -> 加密系：四角点逐个转，取 min/max
            return self._transform_bounds_via_corners(
                west, south, east, north, source_code, target_code
            )

        if src_encrypted:
            # 加密系 -> 标准系：先加密系 -> WGS84（角点），再 WGS84 -> 目标（rasterio）
            w, s = self._transform_encrypted(west, south, source_code, "EPSG:4326")
            e, n = self._transform_encrypted(east, north, source_code, "EPSG:4326")
            # 加密偏移非线性，四角都要转
            w2, s2 = self._transform_encrypted(east, south, source_code, "EPSG:4326")
            e2, n2 = self._transform_encrypted(west, north, source_code, "EPSG:4326")
            wgs_w = min(w, e, w2, e2)
            wgs_s = min(s, n, s2, n2)
            wgs_e = max(w, e, w2, e2)
            wgs_n = max(s, n, s2, n2)
            if target_code == "EPSG:4326":
                return (wgs_w, wgs_s, wgs_e, wgs_n)
            return self._rasterio_transform_bounds(
                wgs_w, wgs_s, wgs_e, wgs_n, "EPSG:4326", target_code
            )

        if tgt_encrypted:
            # 标准系 -> 加密系：先标准系 -> WGS84（rasterio），再 WGS84 -> 加密系（角点）
            if source_code != "EPSG:4326":
                w, s, e, n = self._rasterio_transform_bounds(
                    west, south, east, north, source_code, "EPSG:4326"
                )
            else:
                w, s, e, n = west, south, east, north
            return self._transform_bounds_via_corners(
                w, s, e, n, "EPSG:4326", target_code
            )

        # 标准系 -> 标准系：rasterio 一次搞定
        return self._rasterio_transform_bounds(
            west, south, east, north, source_code, target_code
        )

    def transform_points_batch(
        self,
        points: Iterable[tuple[float, float]],
        source_code: str,
        target_code: str,
        lng_offset: float = 0.0,
        lat_offset: float = 0.0,
    ) -> list[CoordinatePoint]:
        """批量转换点（用于 CSV 导入）。

        Args:
            points: 可迭代的 ``(lng, lat)`` 元组
            source_code, target_code: 源/目标 CRS code
            lng_offset, lat_offset: 偏移（CRS 转换后应用）

        Returns:
            ``list[CoordinatePoint]``，顺序与输入一致
        """
        # 物化以便可能多次遍历
        points_list = list(points)

        # 空输入快速返回（pyproj.itransform 不接受空迭代器）
        if not points_list:
            return []

        if source_code == target_code:
            return [
                CoordinatePoint(lng=lng + lng_offset, lat=lat + lat_offset)
                for lng, lat in points_list
            ]

        src_encrypted = self._is_encrypted(source_code)
        tgt_encrypted = self._is_encrypted(target_code)

        results: list[CoordinatePoint] = []
        if src_encrypted or tgt_encrypted:
            for lng, lat in points_list:
                x, y = self._transform_encrypted(lng, lat, source_code, target_code)
                results.append(
                    CoordinatePoint(lng=x + lng_offset, lat=y + lat_offset)
                )
        else:
            transformer = self._get_transformer(source_code, target_code)
            # itransform 接受迭代器，输出 (x, y) 元组
            for x, y in transformer.itransform(points_list):
                results.append(
                    CoordinatePoint(lng=x + lng_offset, lat=y + lat_offset)
                )
        return results

    # ── 内部辅助 ─────────────────────────────────────────────────────────

    @staticmethod
    def _is_encrypted(code: str) -> bool:
        """判断 CRS code 是否为加密系（GCJ02/BD09）。"""
        crs_def = get_crs(code)
        return crs_def is not None and crs_def.category == CRSCategory.ENCRYPTED

    def _get_transformer(self, source_code: str, target_code: str):
        """获取或缓存 pyproj.Transformer（always_xy=True）。

        加密系不应调用本方法（应在 ``transform_point`` 中提前路由到
        ``_transform_encrypted``）。
        """
        cache_key = (source_code, target_code)
        cached = self._CACHE.get(cache_key)
        if cached is not None:
            return cached
        import pyproj

        transformer = pyproj.Transformer.from_crs(
            source_code, target_code, always_xy=True
        )
        self._CACHE[cache_key] = transformer
        return transformer

    def _transform_encrypted(
        self,
        lng: float,
        lat: float,
        source_code: str,
        target_code: str,
    ) -> tuple[float, float]:
        """加密系转换路由（GCJ02/BD09 任意方向）。

        支持路径：
        - GCJ02 ↔ WGS84 (近似 EPSG:4326)
        - BD09 ↔ WGS84
        - GCJ02 ↔ BD09 (经 WGS84)
        - GCJ02/BD09 ↔ EPSG:3857 (经 WGS84 + pyproj)
        - GCJ02/BD09 ↔ 任意标准投影系 (经 WGS84 + pyproj)
        """
        # ── 直连路径（最高频，零开销）────────────────────────────────
        if source_code == "GCJ02" and target_code == "EPSG:4326":
            p = _gcj_bd.gcj02_to_wgs84(lng, lat)
            return (p.lng, p.lat)
        if source_code == "BD09" and target_code == "EPSG:4326":
            p = _gcj_bd.bd09_to_wgs84(lng, lat)
            return (p.lng, p.lat)
        if source_code == "EPSG:4326" and target_code == "GCJ02":
            p = _gcj_bd.wgs84_to_gcj02(lng, lat)
            return (p.lng, p.lat)
        if source_code == "EPSG:4326" and target_code == "BD09":
            p = _gcj_bd.wgs84_to_bd09(lng, lat)
            return (p.lng, p.lat)
        if source_code == "GCJ02" and target_code == "BD09":
            w = _gcj_bd.gcj02_to_wgs84(lng, lat)
            b = _gcj_bd.wgs84_to_bd09(w.lng, w.lat)
            return (b.lng, b.lat)
        if source_code == "BD09" and target_code == "GCJ02":
            w = _gcj_bd.bd09_to_wgs84(lng, lat)
            g = _gcj_bd.wgs84_to_gcj02(w.lng, w.lat)
            return (g.lng, g.lat)

        # ── 通用路径：先到 WGS84，再到目标 ───────────────────────────
        if source_code in ("GCJ02", "BD09"):
            if source_code == "GCJ02":
                w = _gcj_bd.gcj02_to_wgs84(lng, lat)
            else:
                w = _gcj_bd.bd09_to_wgs84(lng, lat)
            if target_code == "EPSG:4326":
                return (w.lng, w.lat)
            # WGS84 -> 任意投影系
            transformer = self._get_transformer("EPSG:4326", target_code)
            x, y = transformer.transform(w.lng, w.lat)
            return (x, y)

        # source 是标准系，target 是加密系
        if source_code != "EPSG:4326":
            transformer = self._get_transformer(source_code, "EPSG:4326")
            lng, lat = transformer.transform(lng, lat)
        # 现在 source 已是 WGS84，转目标加密系
        if target_code == "GCJ02":
            p = _gcj_bd.wgs84_to_gcj02(lng, lat)
            return (p.lng, p.lat)
        if target_code == "BD09":
            p = _gcj_bd.wgs84_to_bd09(lng, lat)
            return (p.lng, p.lat)

        raise ValueError(
            f"Unsupported encrypted transform: {source_code} -> {target_code}"
        )

    def _transform_bounds_via_corners(
        self,
        west: float,
        south: float,
        east: float,
        north: float,
        source_code: str,
        target_code: str,
    ) -> tuple[float, float, float, float]:
        """四角点逐个转换并取 min/max（用于加密系 bounds 转换）。

        加密偏移是非线性的，不能像线性投影那样用 densify_pts 采样。
        四角点近似已足够（GCJ-02 偏移在 0.001° 量级，区域内变化 < 0.0001°）。
        """
        corners = [
            (west, south),
            (east, south),
            (east, north),
            (west, north),
        ]
        xs: list[float] = []
        ys: list[float] = []
        for lng, lat in corners:
            x, y = self._transform_encrypted(lng, lat, source_code, target_code)
            xs.append(x)
            ys.append(y)
        return (min(xs), min(ys), max(xs), max(ys))

    @staticmethod
    def _rasterio_transform_bounds(
        west: float,
        south: float,
        east: float,
        north: float,
        source_code: str,
        target_code: str,
    ) -> tuple[float, float, float, float]:
        """用 rasterio.warp.transform_bounds 转标准系 bounds。"""
        from rasterio.warp import transform_bounds

        return transform_bounds(
            source_code,
            target_code,
            west,
            south,
            east,
            north,
            densify_pts=21,
        )


# 模块级单例
crs_transformer = CRSTransformer()
