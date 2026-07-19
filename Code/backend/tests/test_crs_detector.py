"""``CRSDetector`` 单元测试。

覆盖：
- ``detect_from_raster``：合成 GeoTIFF（WGS84 / UTM 50N / CGCS2000 / 无 CRS）
- ``detect_from_geojson``：旧格式 crs 字段 / RFC 7946 默认 / 无法解析
- ``detect_from_bounds``：地理坐标系 / 投影坐标系 / 异常 bounds
- ``_parse_crs_name``：urn / EPSG / 别名 / 无法解析
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.services.crs import crs_detector
from app.services.crs._crs_detector import CRSDetector, _CONFIRM_THRESHOLD


# ── 合成 GeoTIFF fixture ──────────────────────────────────────────────

@pytest.fixture
def wgs84_geotiff(tmp_path: Path) -> Path:
    """合成 WGS84 GeoTIFF（1×1 像素，覆盖中国区域）。"""
    import numpy as np
    import rasterio
    from rasterio.transform import from_bounds

    path = tmp_path / "wgs84.tif"
    transform = from_bounds(116.0, 39.0, 117.0, 40.0, 1, 1)
    data = np.array([[1.0]], dtype="float32")
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=1,
        height=1,
        count=1,
        dtype="float32",
        crs="EPSG:4326",
        transform=transform,
    ) as dst:
        dst.write(data, 1)
    return path


@pytest.fixture
def utm50_geotiff(tmp_path: Path) -> Path:
    """合成 UTM 50N GeoTIFF（1×1 像素，北京附近）。"""
    import numpy as np
    import rasterio
    from rasterio.transform import from_bounds

    path = tmp_path / "utm50.tif"
    # 北京附近 UTM 50N 1km×1km
    transform = from_bounds(447000.0, 4419000.0, 448000.0, 4420000.0, 1, 1)
    data = np.array([[1.0]], dtype="float32")
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=1,
        height=1,
        count=1,
        dtype="float32",
        crs="EPSG:32650",
        transform=transform,
    ) as dst:
        dst.write(data, 1)
    return path


@pytest.fixture
def gk4527_geotiff(tmp_path: Path) -> Path:
    """合成 CGCS2000 / GK zone 39 GeoTIFF（1×1 像素，北京附近）。

    EPSG:4527 false easting = 39500000，北京天安门 X≈39564000, Y≈4440000。
    """
    import numpy as np
    import rasterio
    from rasterio.transform import from_bounds

    path = tmp_path / "gk4527.tif"
    # 北京附近 GK zone 39 1km×1km
    transform = from_bounds(39563000.0, 4439000.0, 39564000.0, 4440000.0, 1, 1)
    data = np.array([[1.0]], dtype="float32")
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=1,
        height=1,
        count=1,
        dtype="float32",
        crs="EPSG:4527",
        transform=transform,
    ) as dst:
        dst.write(data, 1)
    return path


@pytest.fixture
def lambert3034_geotiff(tmp_path: Path) -> Path:
    """合成 ETRS89 / LCC Europe GeoTIFF（1×1 像素，中欧附近）。

    EPSG:3034 原点 (4000000, 2800000)，德国中部 X≈4400000, Y≈3100000。
    """
    import numpy as np
    import rasterio
    from rasterio.transform import from_bounds

    path = tmp_path / "lambert3034.tif"
    # 中欧 1km×1km
    transform = from_bounds(4400000.0, 3100000.0, 4401000.0, 3101000.0, 1, 1)
    data = np.array([[1.0]], dtype="float32")
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=1,
        height=1,
        count=1,
        dtype="float32",
        crs="EPSG:3034",
        transform=transform,
    ) as dst:
        dst.write(data, 1)
    return path


@pytest.fixture
def no_crs_geotiff(tmp_path: Path) -> Path:
    """合成无 CRS 元数据的 GeoTIFF（bounds 在地理范围内）。"""
    import numpy as np
    import rasterio
    from rasterio.transform import from_bounds

    path = tmp_path / "no_crs.tif"
    transform = from_bounds(116.0, 39.0, 117.0, 40.0, 1, 1)
    data = np.array([[1.0]], dtype="float32")
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=1,
        height=1,
        count=1,
        dtype="float32",
        crs=None,
        transform=transform,
    ) as dst:
        dst.write(data, 1)
    return path


# ── detect_from_raster ────────────────────────────────────────────────

class TestDetectFromRaster:
    def test_wgs84_geotiff(self, wgs84_geotiff: Path):
        """WGS84 GeoTIFF：返回 EPSG:4326，confidence ≥ 0.9。"""
        result = crs_detector.detect_from_raster(wgs84_geotiff)
        assert result.source_crs == "EPSG:4326"
        assert result.confidence >= 0.9
        assert result.method == "rasterio_crs"
        assert result.needs_user_confirm is False

    def test_utm50_geotiff(self, utm50_geotiff: Path):
        """UTM 50N GeoTIFF：返回 EPSG:32650，confidence ≥ 0.9，需用户确认（非 WGS84 等价系）。"""
        result = crs_detector.detect_from_raster(utm50_geotiff)
        assert result.source_crs == "EPSG:32650"
        assert result.confidence >= 0.9
        assert result.method == "rasterio_crs"
        assert result.needs_user_confirm is True

    def test_gk4527_geotiff(self, gk4527_geotiff: Path):
        """CGCS2000 / GK zone 39 GeoTIFF：返回 EPSG:4527，confidence ≥ 0.9，需用户确认。"""
        result = crs_detector.detect_from_raster(gk4527_geotiff)
        assert result.source_crs == "EPSG:4527"
        assert result.confidence >= 0.9
        assert result.method == "rasterio_crs"
        assert result.needs_user_confirm is True

    def test_lambert3034_geotiff(self, lambert3034_geotiff: Path):
        """ETRS89 / LCC Europe GeoTIFF：返回 EPSG:3034，confidence ≥ 0.9，需用户确认。"""
        result = crs_detector.detect_from_raster(lambert3034_geotiff)
        assert result.source_crs == "EPSG:3034"
        assert result.confidence >= 0.9
        assert result.method == "rasterio_crs"
        assert result.needs_user_confirm is True

    def test_no_crs_geotiff_falls_back_to_bounds(self, no_crs_geotiff: Path):
        """无 CRS 元数据：降级用 bounds 启发式，confidence 降低。"""
        result = crs_detector.detect_from_raster(no_crs_geotiff)
        # bounds (116,39,117,40) 在地理范围内 → 启发式判 WGS84
        assert result.source_crs == "EPSG:4326"
        assert result.confidence < 0.7  # 降权
        assert result.needs_user_confirm is True
        assert "无 CRS 元数据" in result.notes

    def test_nonexistent_file(self, tmp_path: Path):
        """文件不存在：返回默认 WGS84 + 低 confidence。"""
        result = crs_detector.detect_from_raster(tmp_path / "nonexistent.tif")
        assert result.source_crs == "EPSG:4326"
        assert result.confidence == 0.0
        assert result.needs_user_confirm is True
        assert "读取栅格失败" in result.notes

    def test_geographic_crs_with_projected_bounds(
        self, tmp_path: Path
    ):
        """CRS 声明地理系但 bounds 超出 ±180/±90：提示可能实际为投影系。"""
        import numpy as np
        import rasterio
        from rasterio.transform import from_bounds

        path = tmp_path / "mismatch.tif"
        # 故意声明 EPSG:4326 但 bounds 用投影坐标
        transform = from_bounds(447000.0, 4419000.0, 448000.0, 4420000.0, 1, 1)
        data = np.array([[1.0]], dtype="float32")
        with rasterio.open(
            path,
            "w",
            driver="GTiff",
            width=1,
            height=1,
            count=1,
            dtype="float32",
            crs="EPSG:4326",
            transform=transform,
        ) as dst:
            dst.write(data, 1)

        result = crs_detector.detect_from_raster(path)
        # 应检测到不匹配并降权
        assert result.confidence < 0.7
        assert result.needs_user_confirm is True
        assert "超出 ±180/±90" in result.notes


# ── detect_from_geojson ───────────────────────────────────────────────

class TestDetectFromGeojson:
    def test_explicit_crs_4490(self):
        """GeoJSON 含 crs 字段声明 EPSG:4490。"""
        geojson = {
            "type": "FeatureCollection",
            "crs": {
                "type": "name",
                "properties": {"name": "urn:ogc:def:crs:EPSG::4490"},
            },
            "features": [],
        }
        result = crs_detector.detect_from_geojson(geojson)
        assert result.source_crs == "EPSG:4490"
        assert result.confidence == 0.9
        assert result.method == "geojson_crs"
        assert result.needs_user_confirm is False

    def test_no_crs_defaults_wgs84(self):
        """GeoJSON 无 crs 字段：按 RFC 7946 默认 WGS84。"""
        geojson = {"type": "FeatureCollection", "features": []}
        result = crs_detector.detect_from_geojson(geojson)
        assert result.source_crs == "EPSG:4326"
        assert result.confidence == 0.9
        assert result.method == "default"
        assert result.needs_user_confirm is False

    def test_unparseable_crs_name(self):
        """crs.name 无法解析：返回 WGS84 + 低 confidence。"""
        geojson = {
            "type": "FeatureCollection",
            "crs": {
                "type": "name",
                "properties": {"name": "some-unknown-crs"},
            },
            "features": [],
        }
        result = crs_detector.detect_from_geojson(geojson)
        assert result.source_crs == "EPSG:4326"
        assert result.confidence == 0.5
        assert result.needs_user_confirm is True

    def test_epsg_short_form(self):
        """crs.name 用 'EPSG:4258' 短格式。"""
        geojson = {
            "type": "FeatureCollection",
            "crs": {
                "type": "name",
                "properties": {"name": "EPSG:4258"},
            },
            "features": [],
        }
        result = crs_detector.detect_from_geojson(geojson)
        assert result.source_crs == "EPSG:4258"
        assert result.method == "geojson_crs"

    def test_missing_properties(self):
        """crs 字段存在但缺 properties：返回默认 WGS84。"""
        geojson = {
            "type": "FeatureCollection",
            "crs": {"type": "name"},  # 无 properties
            "features": [],
        }
        result = crs_detector.detect_from_geojson(geojson)
        assert result.source_crs == "EPSG:4326"
        assert result.needs_user_confirm is True


# ── detect_from_bounds ────────────────────────────────────────────────

class TestDetectFromBounds:
    def test_geographic_bounds_china(self):
        """中国区域地理 bounds：confidence 0.5，需确认。"""
        result = crs_detector.detect_from_bounds((73.0, 15.0, 137.0, 59.0))
        assert result.source_crs == "EPSG:4326"
        assert result.confidence == 0.5
        assert result.method == "bounds_heuristic"
        assert result.needs_user_confirm is True

    def test_projected_bounds_utm(self):
        """投影坐标系 bounds（UTM 数值）：confidence 0.3，需确认。"""
        result = crs_detector.detect_from_bounds(
            (447950.0, 4419460.0, 448000.0, 4419500.0)
        )
        assert result.source_crs == "EPSG:32650"
        assert result.confidence == 0.3
        assert result.method == "bounds_heuristic"
        assert result.needs_user_confirm is True

    def test_detect_from_bounds_gauss_kruger_zone39(self):
        """GK zone 39 false easting 模式：建议 EPSG:4527。"""
        result = crs_detector.detect_from_bounds(
            (39500000.0, 4400000.0, 39510000.0, 4410000.0)
        )
        assert result.source_crs == "EPSG:4527"
        assert result.suggested_crs == "EPSG:4527"
        assert result.confidence == 0.5
        assert result.method == "bounds_heuristic"
        assert result.needs_user_confirm is True
        assert "高斯-克吕格" in result.notes

    def test_detect_from_bounds_gauss_kruger_zone40(self):
        """GK zone 40 false easting 模式：建议 EPSG:4528。"""
        result = crs_detector.detect_from_bounds(
            (40500000.0, 3500000.0, 40510000.0, 3510000.0)
        )
        assert result.source_crs == "EPSG:4528"
        assert result.suggested_crs == "EPSG:4528"
        assert result.confidence == 0.5
        assert result.method == "bounds_heuristic"
        assert result.needs_user_confirm is True

    def test_detect_from_bounds_gauss_kruger_zone41(self):
        """GK zone 41 false easting 模式：建议 EPSG:4529。"""
        result = crs_detector.detect_from_bounds(
            (41500000.0, 4500000.0, 41510000.0, 4510000.0)
        )
        assert result.source_crs == "EPSG:4529"
        assert result.suggested_crs == "EPSG:4529"
        assert result.confidence == 0.5
        assert result.method == "bounds_heuristic"
        assert result.needs_user_confirm is True

    def test_detect_from_bounds_lambert_europe(self):
        """Lambert Europe 范围 bounds：建议 EPSG:3034。"""
        result = crs_detector.detect_from_bounds(
            (4000000.0, 2500000.0, 4500000.0, 3000000.0)
        )
        assert result.source_crs == "EPSG:3034"
        assert result.suggested_crs == "EPSG:3034"
        assert result.confidence == 0.3
        assert result.method == "bounds_heuristic"
        assert result.needs_user_confirm is True
        assert "Lambert Europe" in result.notes

    def test_global_bounds(self):
        """全球 bounds：判定地理坐标系。"""
        result = crs_detector.detect_from_bounds((-180.0, -90.0, 180.0, 90.0))
        assert result.source_crs == "EPSG:4326"
        assert result.confidence == 0.5

    def test_invalid_bounds_west_gt_east(self):
        """bounds west >= east：无法明确分类，默认 WGS84。"""
        result = crs_detector.detect_from_bounds((100.0, 30.0, 50.0, 40.0))
        # west > east，is_geographic 判定为 False，进入兜底分支
        assert result.source_crs == "EPSG:4326"
        assert result.confidence == 0.3
        assert result.needs_user_confirm is True


# ── _parse_crs_name ───────────────────────────────────────────────────

class TestParseCrsName:
    @pytest.mark.parametrize(
        "name,expected",
        [
            ("urn:ogc:def:crs:EPSG::4326", "EPSG:4326"),
            ("urn:ogc:def:crs:EPSG::4490", "EPSG:4490"),
            ("urn:ogc:def:crs:EPSG::4258", "EPSG:4258"),
            ("EPSG:4326", "EPSG:4326"),
            ("epsg:4490", "EPSG:4490"),
            ("WGS84", "EPSG:4326"),
            ("wgs 84", "EPSG:4326"),
            ("CGCS2000", "EPSG:4490"),
            ("cgcs 2000", "EPSG:4490"),
            ("ETRS89", "EPSG:4258"),
            ("GCJ-02", "GCJ02"),
            ("GCJ02", "GCJ02"),
            ("BD-09", "BD09"),
            ("BD09", "BD09"),
        ],
    )
    def test_known_names(self, name: str, expected: str):
        assert CRSDetector._parse_crs_name(name) == expected

    @pytest.mark.parametrize(
        "name",
        ["", "unknown-crs", "FOO:123", "invalid", None],
    )
    def test_unparseable(self, name):
        assert CRSDetector._parse_crs_name(name or "") is None


# ── 置信度阈值一致性 ──────────────────────────────────────────────────

class TestConfidenceThreshold:
    def test_threshold_value(self):
        """确认阈值 0.7（与模块常量一致）。"""
        assert _CONFIRM_THRESHOLD == 0.7

    def test_high_confidence_no_confirm(self, wgs84_geotiff: Path):
        """WGS84 等价系（EPSG:4326）即便高 confidence 也不需确认。"""
        result = crs_detector.detect_from_raster(wgs84_geotiff)
        assert result.confidence >= _CONFIRM_THRESHOLD
        assert result.needs_user_confirm is False

    def test_low_confidence_needs_confirm(self):
        """confidence < 0.7 时 needs_user_confirm=True。"""
        result = crs_detector.detect_from_bounds((73.0, 15.0, 137.0, 59.0))
        assert result.confidence < _CONFIRM_THRESHOLD
        assert result.needs_user_confirm is True
