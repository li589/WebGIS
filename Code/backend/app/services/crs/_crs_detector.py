"""CRS 自动检测器 — 从 rasterio/GeoJSON/bounds 推断坐标系。

三层检测策略：
1. ``detect_from_raster``：用 rasterio 读 GeoTIFF 的 CRS 元数据（最可靠）
2. ``detect_from_geojson``：读 GeoJSON 的 ``crs`` 字段（RFC 7946 前格式）
3. ``detect_from_bounds``：基于 bounds 数值范围的启发式（最不可靠）

置信度阈值：
- ``confidence >= 0.9``：来源可靠（rasterio CRS / GeoJSON 显式声明），无需用户确认
- ``0.5 <= confidence < 0.9``：来源部分可靠，建议用户确认
- ``confidence < 0.5``：纯启发式，**必须**用户确认

使用示例::

    from app.services.crs import crs_detector
    result = crs_detector.detect_from_raster(Path("data.tif"))
    if result.needs_user_confirm:
        # 弹前端确认框
        ...
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .crs_registry import get_crs, suggest_gk_zone, suggest_utm_zone


# 置信度阈值：低于此值时前端必须弹确认框
_CONFIRM_THRESHOLD = 0.7


@dataclass(frozen=True)
class CRSDetectionResult:
    """CRS 检测结果。

    Attributes:
        source_crs: 检测到的 CRS code（如 ``'EPSG:32650'``）；未识别返回
            ``'EPSG:4326'`` 作默认值（GeoJSON RFC 7946 默认 WGS84）。
        confidence: 0.0~1.0，反映检测来源的可靠程度。
        method: 检测方法标识：``'rasterio_crs'`` | ``'geojson_crs'`` |
            ``'bounds_heuristic'`` | ``'default'``。
        suggested_crs: 建议用户确认的 CRS code（通常等同 ``source_crs``，
            但当 ``source_crs`` 为默认值时可能是启发式推断的候选）。
        needs_user_confirm: ``True`` 时前端应弹确认对话框让用户校验/覆盖。
        notes: 检测过程说明（用于前端展示或日志）。
    """

    source_crs: str
    confidence: float
    method: str
    suggested_crs: str
    needs_user_confirm: bool
    notes: str


class CRSDetector:
    """CRS 自动检测器（单例）。"""

    def detect_from_raster(self, path: Path) -> CRSDetectionResult:
        """从栅格文件（GeoTIFF 等）的 CRS 元数据检测。

        优先用 ``rasterio.open(path).crs.to_epsg()`` 取标准 EPSG 代码；
        若 CRS 含 ``CGCS2000`` 字样则判为 EPSG:4490（与 WGS84 数值等价）。

        Args:
            path: 栅格文件路径

        Returns:
            ``CRSDetectionResult``，method 为 ``'rasterio_crs'``
        """
        try:
            import rasterio
        except ImportError as exc:
            return CRSDetectionResult(
                source_crs="EPSG:4326",
                confidence=0.0,
                method="default",
                suggested_crs="EPSG:4326",
                needs_user_confirm=True,
                notes=f"rasterio 不可用，无法检测: {exc}",
            )

        try:
            with rasterio.open(str(path)) as dataset:
                crs = dataset.crs
                west, south, east, north = dataset.bounds
        except Exception as exc:
            return CRSDetectionResult(
                source_crs="EPSG:4326",
                confidence=0.0,
                method="default",
                suggested_crs="EPSG:4326",
                needs_user_confirm=True,
                notes=f"读取栅格失败: {exc}",
            )

        if crs is None:
            # 无 CRS 元数据：用 bounds 启发式
            bounds_result = self.detect_from_bounds((west, south, east, north))
            return CRSDetectionResult(
                source_crs=bounds_result.source_crs,
                confidence=bounds_result.confidence * 0.8,  # 无元数据，降权
                method="rasterio_crs",
                suggested_crs=bounds_result.suggested_crs,
                needs_user_confirm=True,
                notes=f"栅格无 CRS 元数据，按 bounds 启发式推断: {bounds_result.notes}",
            )

        # 优先用 to_epsg() 取整数 EPSG 代码
        epsg = crs.to_epsg() if hasattr(crs, "to_epsg") else None
        crs_str = str(crs)

        # 区分 CGCS2000 (4490) 与 WGS84 (4326)：rasterio CRS 字符串含 CGCS2000
        if "CGCS2000" in crs_str or "CGCS 2000" in crs_str:
            source_crs = "EPSG:4490"
            notes = "rasterio CRS 含 CGCS2000 标识，判定为 EPSG:4490"
        elif epsg is not None:
            source_crs = f"EPSG:{epsg}"
            notes = f"rasterio CRS EPSG:{epsg}"
        else:
            # 非 EPSG 的 CRS（如 proj4 字符串），尝试用 registry 反查
            registry_match = get_crs(crs_str)
            if registry_match is not None:
                source_crs = registry_match.code
                notes = f"rasterio CRS 匹配 registry: {crs_str}"
            else:
                # 未识别的 CRS：用 bounds 启发式给建议
                bounds_result = self.detect_from_bounds((west, south, east, north))
                return CRSDetectionResult(
                    source_crs=crs_str,
                    confidence=0.4,
                    method="rasterio_crs",
                    suggested_crs=bounds_result.suggested_crs,
                    needs_user_confirm=True,
                    notes=f"rasterio CRS 未在 registry 注册: {crs_str}；bounds 启发式建议: {bounds_result.suggested_crs}",
                )

        # 二次校验：若声明是地理坐标系但 bounds 数值超出 ±180/±90，
        # 可能是 CRS 元数据与实际数据不匹配（如投影数据被误标为 EPSG:4326）
        if source_crs in ("EPSG:4326", "EPSG:4490", "EPSG:4258"):
            if abs(west) > 180 or abs(east) > 180 or abs(south) > 90 or abs(north) > 90:
                bounds_result = self.detect_from_bounds((west, south, east, north))
                return CRSDetectionResult(
                    source_crs=source_crs,
                    confidence=0.4,
                    method="rasterio_crs",
                    suggested_crs=bounds_result.suggested_crs,
                    needs_user_confirm=True,
                    notes=(
                        f"CRS 声明为 {source_crs}（地理系）但 bounds "
                        f"({west:.2f},{south:.2f},{east:.2f},{north:.2f}) "
                        f"超出 ±180/±90，可能实际为投影坐标系。"
                        f"启发式建议: {bounds_result.suggested_crs}"
                    ),
                )

        # 正常路径：CRS 元数据可靠
        in_registry = get_crs(source_crs) is not None
        confidence = 0.95 if in_registry else 0.7
        # needs_user_confirm 语义：源 CRS 非 WGS84 等价系时必须确认
        # （即便 CRS 元数据可靠，非 WGS84 数据仍需重投影 + 用户知晓）
        # WGS84 等价系：EPSG:4326 (WGS84)、EPSG:4490 (CGCS2000，与 WGS84 数值等价)
        needs_confirm = source_crs not in ("EPSG:4326", "EPSG:4490")
        return CRSDetectionResult(
            source_crs=source_crs,
            confidence=confidence,
            method="rasterio_crs",
            suggested_crs=source_crs,
            needs_user_confirm=needs_confirm,
            notes=notes,
        )

    def detect_from_geojson(self, geojson: dict[str, Any]) -> CRSDetectionResult:
        """从 GeoJSON 的 ``crs`` 字段检测。

        RFC 7946 (2015) 移除了 ``crs`` 字段，规定 GeoJSON 默认 WGS84 (EPSG:4326)。
        但旧格式（RFC 7946 前）在顶层有 ``crs`` 字段：
        ``{"crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:EPSG::4490"}}}``

        Args:
            geojson: GeoJSON 对象（dict）

        Returns:
            ``CRSDetectionResult``，method 为 ``'geojson_crs'`` 或 ``'default'``
        """
        crs_field = geojson.get("crs")
        if crs_field is None:
            # RFC 7946 默认 WGS84
            return CRSDetectionResult(
                source_crs="EPSG:4326",
                confidence=0.9,
                method="default",
                suggested_crs="EPSG:4326",
                needs_user_confirm=False,
                notes="GeoJSON 无 crs 字段，按 RFC 7946 默认 WGS84 (EPSG:4326)",
            )

        # 旧格式：{"crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:EPSG::4490"}}}
        try:
            name = crs_field.get("properties", {}).get("name", "")
        except (AttributeError, TypeError):
            name = ""

        # 解析 urn:ogc:def:crs:EPSG::4490 / EPSG:4490 / epsg:4490 等格式
        source_crs = self._parse_crs_name(name)
        if source_crs is None:
            return CRSDetectionResult(
                source_crs="EPSG:4326",
                confidence=0.5,
                method="geojson_crs",
                suggested_crs="EPSG:4326",
                needs_user_confirm=True,
                notes=f"GeoJSON crs.name 无法解析: {name!r}，默认 WGS84",
            )

        in_registry = get_crs(source_crs) is not None
        confidence = 0.9 if in_registry else 0.6
        return CRSDetectionResult(
            source_crs=source_crs,
            confidence=confidence,
            method="geojson_crs",
            suggested_crs=source_crs,
            needs_user_confirm=confidence < _CONFIRM_THRESHOLD,
            notes=f"GeoJSON crs.name = {name!r} -> {source_crs}",
        )

    def detect_from_bounds(
        self, bounds: tuple[float, float, float, float]
    ) -> CRSDetectionResult:
        """基于 bounds 数值范围的启发式检测（最不可靠）。

        判断规则（优先级从高到低）：
        1. west/east 在 ±180 内且 south/north 在 ±90 内 → 地理坐标系（confidence 0.5）
        2. 数值在 ±20037508 范围 → Web Mercator / EPSG:3857（confidence 0.6）
        3. 高斯-克吕格 3 度带 false easting 模式 → 对应 GK 带（confidence 0.5）
        4. Lambert Europe 范围 → EPSG:3034（confidence 0.3）
        5. 投影系大数值 → 用 bounds 中心经度推断 UTM 带（confidence 0.4）
        6. 其他 → 默认 WGS84（confidence 0.3）

        Args:
            bounds: ``(west, south, east, north)``

        Returns:
            ``CRSDetectionResult``，method 为 ``'bounds_heuristic'``
        """
        west, south, east, north = bounds

        # 检查是否为地理坐标系范围
        is_geographic = (
            -180 <= west <= 180
            and -180 <= east <= 180
            and -90 <= south <= 90
            and -90 <= north <= 90
            and west < east
            and south < north
        )

        if is_geographic:
            # 进一步细化：中国区域 → 可能是 CGCS2000 (4490) 或 WGS84 (4326)
            # 无法区分，默认 WGS84（两者数值等价）
            return CRSDetectionResult(
                source_crs="EPSG:4326",
                confidence=0.5,
                method="bounds_heuristic",
                suggested_crs="EPSG:4326",
                needs_user_confirm=True,
                notes=f"bounds ({west:.2f},{south:.2f},{east:.2f},{north:.2f}) 在 ±180/±90 内，推断为地理坐标系",
            )

        # EASE-Grid 2.0 Global (EPSG:6933)：对称角点约 ±17.37e6 × ±7.31e6，
        # 宽高比约 2.37，易被误判为 Web Mercator（max 也 < 20.1e6）。
        max_abs = max(abs(west), abs(east), abs(south), abs(north))
        x_span = abs(east - west)
        y_span = abs(north - south)
        if (
            max_abs > 1_000_000
            and max_abs <= 18_000_000
            and y_span > 0
            and 2.0 < x_span / y_span < 2.7
            and abs(west + east) < 1e5
            and abs(south + north) < 1e5
        ):
            return CRSDetectionResult(
                source_crs="EPSG:6933",
                confidence=0.65,
                method="bounds_heuristic",
                suggested_crs="EPSG:6933",
                needs_user_confirm=True,
                notes=(
                    f"bounds ({west:.0f},{south:.0f},{east:.0f},{north:.0f}) "
                    f"接近 EASE-Grid 2.0 Global（宽高比 {x_span / y_span:.2f}），"
                    f"建议 EPSG:6933，需用户确认"
                ),
            )

        # Web Mercator (EPSG:3857)：全球/大区 Web 地图投影。
        # 要求跨度足够大，避免 UTM 局部米制框（~4e6 northing）被误判。
        if max_abs > 5_000_000 and max_abs <= 20_100_000 and x_span > 1_000_000:
            if y_span > 0 and 0.3 < x_span / y_span < 3.5:
                return CRSDetectionResult(
                    source_crs="EPSG:3857",
                    confidence=0.6,
                    method="bounds_heuristic",
                    suggested_crs="EPSG:3857",
                    needs_user_confirm=True,
                    notes=(
                        f"bounds ({west:.0f},{south:.0f},{east:.0f},{north:.0f}) "
                        f"在 Web Mercator 范围内（max={max_abs:.0f}），"
                        f"建议 EPSG:3857，需用户确认"
                    ),
                )

        # 投影坐标系：大数值
        if abs(west) > 180 or abs(east) > 180:
            # 高斯-克吕格 3 度带 false easting 模式：X 在 39000000-42000000 范围
            # （zone 39/40/41，覆盖北京/上海/东北；false_easting = zone × 1000000 + 500000）
            if 39000000 < west < 42000000 or 39000000 < east < 42000000:
                # 按中央子午线推断 zone
                mid_x = (west + east) / 2
                zone = int(mid_x // 1000000)
                if zone == 39:
                    suggested = "EPSG:4527"
                elif zone == 40:
                    suggested = "EPSG:4528"
                elif zone == 41:
                    suggested = "EPSG:4529"
                else:
                    suggested = "EPSG:4527"
                return CRSDetectionResult(
                    source_crs=suggested,
                    confidence=0.5,
                    method="bounds_heuristic",
                    suggested_crs=suggested,
                    needs_user_confirm=True,
                    notes=(
                        f"bounds ({west:.0f},{south:.0f},{east:.0f},{north:.0f}) "
                        f"匹配高斯-克吕格 3 度带 false easting 模式（zone {zone}），"
                        f"建议 {suggested}，需用户确认"
                    ),
                )

            # 高斯-克吕格 3 度带（更广范围）：false_easting = zone × 1000000 + 500000
            # zone 25-45 → X 在 25500000-45500000
            if 25500000 < max_abs < 45500000:
                mid_x = (west + east) / 2
                zone = int(mid_x // 1000000)
                gk_code = suggest_gk_zone(zone * 3.0)
                if gk_code is not None:
                    return CRSDetectionResult(
                        source_crs=gk_code,
                        confidence=0.45,
                        method="bounds_heuristic",
                        suggested_crs=gk_code,
                        needs_user_confirm=True,
                        notes=(
                            f"bounds ({west:.0f},{south:.0f},{east:.0f},{north:.0f}) "
                            f"匹配高斯-克吕格 3 度带（zone {zone}），"
                            f"建议 {gk_code}，需用户确认"
                        ),
                    )

            # Lambert Europe (EPSG:3034, LCC Europe) 范围
            if 1000000 < west < 8000000 and 1000000 < east < 8000000:
                return CRSDetectionResult(
                    source_crs="EPSG:3034",
                    confidence=0.3,
                    method="bounds_heuristic",
                    suggested_crs="EPSG:3034",
                    needs_user_confirm=True,
                    notes=(
                        f"bounds ({west:.0f},{south:.0f},{east:.0f},{north:.0f}) "
                        f"在 Lambert Europe 范围内，建议 EPSG:3034，需用户确认"
                    ),
                )

            # UTM / 投影兜底：用 northing 粗估纬度 + 区域默认经度，调用 suggest_utm_zone
            mid_x = (west + east) / 2.0
            mid_y = (south + north) / 2.0
            # 南半球 UTM 常带 false northing 1e7
            if mid_y >= 1.0e7:
                approx_lat = -max(0.0, min(80.0, (10_000_000.0 - mid_y) / 111320.0))
            else:
                approx_lat = max(-80.0, min(84.0, mid_y / 111320.0))
            # 无带号时无法从 easting 反算经度；中国常用北纬取 116°E（UTM50），否则 0°
            approx_lng = 116.0 if 15.0 <= abs(approx_lat) <= 55.0 else 0.0
            # 带内 easting（~100k–900k）优先 UTM，勿用 GK（GK 有 8 位 false easting）
            if 100_000 <= abs(mid_x) <= 900_000:
                utm_code = suggest_utm_zone(approx_lng, approx_lat)
                return CRSDetectionResult(
                    source_crs=utm_code,
                    confidence=0.4,
                    method="bounds_heuristic",
                    suggested_crs=utm_code,
                    needs_user_confirm=True,
                    notes=(
                        f"bounds ({west:.2f},{south:.2f},{east:.2f},{north:.2f}) "
                        f"像 UTM 米制；粗估 lat≈{approx_lat:.1f} → 建议 {utm_code}，需用户确认"
                    ),
                )
            return CRSDetectionResult(
                source_crs=suggest_utm_zone(approx_lng, approx_lat),
                confidence=0.3,
                method="bounds_heuristic",
                suggested_crs=suggest_utm_zone(approx_lng, approx_lat),
                needs_user_confirm=True,
                notes=(
                    f"bounds ({west:.2f},{south:.2f},{east:.2f},{north:.2f}) "
                    f"数值超出 ±180，推断为投影坐标系（建议 "
                    f"{suggest_utm_zone(approx_lng, approx_lat)}，需用户确认）"
                ),
            )

        # 兜底
        return CRSDetectionResult(
            source_crs="EPSG:4326",
            confidence=0.3,
            method="bounds_heuristic",
            suggested_crs="EPSG:4326",
            needs_user_confirm=True,
            notes=f"bounds ({west:.2f},{south:.2f},{east:.2f},{north:.2f}) 无法明确分类，默认 WGS84",
        )

    def detect_xy_swap(
        self,
        bounds: tuple[float, float, float, float],
        *,
        source_crs: str = "EPSG:4326",
    ) -> tuple[bool, str]:
        """检测 bounds 的 XY 轴是否被颠倒。

        对于地理坐标系（EPSG:4326/4490/4258），正常顺序为
        (west, south, east, north) 即 (lng, lat, lng, lat)。
        若数据被颠倒为 (lat, lng, lat, lng)，则：
        - bounds[0]（应为 west/lng）出现在 ±90 范围
        - bounds[1]（应为 south/lat）出现在 ±180 范围

        Args:
            bounds: ``(west, south, east, north)``
            source_crs: 源 CRS code

        Returns:
            (is_swapped, note) — is_swapped=True 表示需要交换 XY。
        """
        west, south, east, north = bounds

        # 仅对地理坐标系检测 XY 颠倒
        if source_crs not in ("EPSG:4326", "EPSG:4490", "EPSG:4258"):
            return (False, "非地理坐标系，跳过 XY 颠倒检测")

        # 正常地理坐标：|west|,|east| <= 180，|south|,|north| <= 90
        # 颠倒情况：|west|,|east| > 90 但 <= 180（实为 lat），|south|,|north| > 180（实为 lng）
        # 更精确：west/south 中有一个的绝对值超出其正常范围
        west_oob = abs(west) > 180
        south_oob = abs(south) > 90
        east_oob = abs(east) > 180
        north_oob = abs(north) > 90

        # 典型颠倒：south/north 出现 > 90 的值（实为经度），west/east 在 ±90 内（实为纬度）
        if (south_oob or north_oob) and not (west_oob or east_oob):
            return (
                True,
                f"bounds ({west:.4f},{south:.4f},{east:.4f},{north:.4f}) "
                f"疑似 XY 颠倒：south/north 超出 ±90（实为经度），"
                f"west/east 在 ±90 内（实为纬度）",
            )

        # 另一种颠倒模式：west > south 且 east > north（数值上 X 恒大于 Y）
        # 在中国区域（lng 73-135, lat 18-53），正常情况下 lng > lat
        # 但若数据为 (lat, lng, lat, lng)，则 west=lat < south=lng，不成立
        # 这种模式不太可靠，仅作辅助
        if abs(south) > 90 and abs(north) > 90 and abs(west) <= 90 and abs(east) <= 90:
            return (
                True,
                f"bounds ({west:.4f},{south:.4f},{east:.4f},{north:.4f}) "
                f"XY 颠倒：west/east 在 ±90 内（实为纬度），"
                f"south/north 超出 ±90（实为经度）",
            )

        return (False, "XY 轴序正常")

    @staticmethod
    def _parse_crs_name(name: str) -> str | None:
        """解析 CRS 名称字符串为 registry code。

        支持格式：
        - ``urn:ogc:def:crs:EPSG::4490`` → ``EPSG:4490``
        - ``EPSG:4490`` → ``EPSG:4490``
        - ``epsg:4490`` → ``EPSG:4490``
        - ``WGS84`` / ``CGCS2000`` → ``EPSG:4326`` / ``EPSG:4490``
        """
        if not name:
            return None
        name = name.strip()

        # urn:ogc:def:crs:EPSG::4490
        if "urn:ogc:def:crs" in name.lower():
            parts = name.split(":")
            # 取最后一段数字
            for part in reversed(parts):
                if part.isdigit():
                    return f"EPSG:{int(part)}"

        # EPSG:4490 / epsg:4490
        lower = name.lower()
        if lower.startswith("epsg:"):
            try:
                code = int(name.split(":")[1])
                return f"EPSG:{code}"
            except (IndexError, ValueError):
                return None

        # 常见别名
        aliases = {
            "wgs84": "EPSG:4326",
            "wgs 84": "EPSG:4326",
            "cgcs2000": "EPSG:4490",
            "cgcs 2000": "EPSG:4490",
            "etrs89": "EPSG:4258",
            "gcj-02": "GCJ02",
            "gcj02": "GCJ02",
            "bd-09": "BD09",
            "bd09": "BD09",
        }
        if lower in aliases:
            return aliases[lower]

        return None


# 模块级单例
crs_detector = CRSDetector()
