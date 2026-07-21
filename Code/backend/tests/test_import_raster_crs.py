"""``/import/*`` CRS 集成测试。

覆盖 Phase 1 新增端点：
- ``GET  /import/crs-options`` — 13 项 CRS
- ``POST /import/transform-point`` — 批量点转换
- ``POST /import/transform-bounds`` — bounds 转换
- ``POST /import/raster`` — 上传 TIF，返回检测 CRS + needs_confirm
- ``POST /import/raster/confirm`` — 重投影到 WGS84 + 重写 bounds

合成 GeoTIFF 用 rasterio + tmp_path fixture（已重定向到项目内 .pytest_tmp）。
"""
from __future__ import annotations

import io
import json
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.services.crs._gcj_bd import gcj02_to_wgs84
from app.services.overlay_registry import get_overlay_spec, unregister_overlay


# ── 合成 GeoTIFF fixtures ────────────────────────────────────────────────


@pytest.fixture
def wgs84_geotiff(tmp_path: Path) -> Path:
    """合成 WGS84 GeoTIFF（32×32 像素，覆盖中国区域 116-117E, 39-40N）。

    32×32 是常见的小栅格尺寸，更接近真实数据。原 2×2 fixture 暴露了
    ``raster_preview_service.py`` 的标量 mask bug（已修复）。
    """
    import numpy as np
    import rasterio
    from rasterio.transform import from_bounds

    path = tmp_path / "wgs84.tif"
    transform = from_bounds(116.0, 39.0, 117.0, 40.0, 32, 32)
    data = np.linspace(1.0, 4.0, 32 * 32, dtype="float32").reshape(32, 32)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=32,
        height=32,
        count=1,
        dtype="float32",
        crs="EPSG:4326",
        transform=transform,
    ) as dst:
        dst.write(data, 1)
    return path


@pytest.fixture
def utm50_geotiff(tmp_path: Path) -> Path:
    """合成 UTM 50N GeoTIFF（32×32 像素，北京附近 1km×1km，分辨率 ~31m/像素）。"""
    import numpy as np
    import rasterio
    from rasterio.transform import from_bounds

    path = tmp_path / "utm50.tif"
    # 北京附近 UTM 50N 1km×1km
    transform = from_bounds(447000.0, 4419000.0, 448000.0, 4420000.0, 32, 32)
    data = np.linspace(1.0, 4.0, 32 * 32, dtype="float32").reshape(32, 32)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=32,
        height=32,
        count=1,
        dtype="float32",
        crs="EPSG:32650",
        transform=transform,
    ) as dst:
        dst.write(data, 1)
    return path


@pytest.fixture
def client() -> TestClient:
    """FastAPI TestClient（dev mode 自动跳过 auth）。"""
    return TestClient(create_app())


# ── /import/crs-options ────────────────────────────────────────────────


class TestCrsOptions:
    """``GET /import/crs-options`` 端点。"""

    def test_returns_13_items(self, client: TestClient) -> None:
        resp = client.get("/import/crs-options")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 13
        codes = {item["code"] for item in data["items"]}
        # 应包含 Phase 1 扩展版全部 13 个 CRS
        expected = {"EPSG:4326", "EPSG:4490", "EPSG:4258", "GCJ02", "BD09",
                    "EPSG:3857", "EPSG:6933", "EPSG:32649", "EPSG:32650",
                    "EPSG:4527", "EPSG:4528", "EPSG:4529", "EPSG:3034"}
        assert codes == expected

    def test_items_have_required_fields(self, client: TestClient) -> None:
        resp = client.get("/import/crs-options")
        items = resp.json()["items"]
        for item in items:
            assert "code" in item
            assert "label" in item
            assert "category" in item
            assert "area" in item
            assert "deprecated" in item
            assert item["category"] in ("geographic", "encrypted", "projected")


# ── /import/transform-point ────────────────────────────────────────────


class TestTransformPoint:
    """``POST /import/transform-point`` 端点。"""

    def test_batch_gcj02_to_wgs84(self, client: TestClient) -> None:
        """批量 GCJ02 → WGS84，结果与 ``_gcj_bd.gcj02_to_wgs84`` 一致。"""
        points = [[116.39747, 39.90880], [121.47370, 31.23040]]
        resp = client.post(
            "/import/transform-point",
            json={
                "points": points,
                "source_crs": "GCJ02",
                "target_crs": "EPSG:4326",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 2
        for (lng, lat), result in zip(points, data["points"]):
            expected = gcj02_to_wgs84(lng, lat)
            assert abs(result[0] - expected.lng) < 1e-9
            assert abs(result[1] - expected.lat) < 1e-9

    def test_with_offset(self, client: TestClient) -> None:
        """偏移在 CRS 转换后应用。"""
        resp = client.post(
            "/import/transform-point",
            json={
                "points": [[0.0, 0.0]],
                "source_crs": "EPSG:4326",
                "target_crs": "EPSG:4326",
                "lng_offset": 1.0,
                "lat_offset": 2.0,
            },
        )
        assert resp.status_code == 200
        result = resp.json()["points"][0]
        assert abs(result[0] - 1.0) < 1e-9
        assert abs(result[1] - 2.0) < 1e-9

    def test_empty_points(self, client: TestClient) -> None:
        """空点列表应返回空结果（不报错）。"""
        resp = client.post(
            "/import/transform-point",
            json={"points": [], "source_crs": "EPSG:4326", "target_crs": "EPSG:3857"},
        )
        assert resp.status_code == 200
        assert resp.json()["count"] == 0
        assert resp.json()["points"] == []


# ── /import/transform-bounds ───────────────────────────────────────────


class TestTransformBounds:
    """``POST /import/transform-bounds`` 端点。"""

    def test_utm50_to_wgs84(self, client: TestClient) -> None:
        """EPSG:32650 → EPSG:4326 bounds 转换，结果应在中国区域。"""
        # 北京附近 1km×1km UTM 50N
        resp = client.post(
            "/import/transform-bounds",
            json={
                "bounds": [447000.0, 4419000.0, 448000.0, 4420000.0],
                "source_crs": "EPSG:32650",
                "target_crs": "EPSG:4326",
            },
        )
        assert resp.status_code == 200
        w, s, e, n = resp.json()["bounds"]
        # 应在中国区域
        assert 70 < w < 140
        assert 0 < s < 60
        assert w < e
        assert s < n
        # 中心点应接近北京
        center_lng = (w + e) / 2
        center_lat = (s + n) / 2
        assert abs(center_lng - 116.39) < 0.1
        assert abs(center_lat - 39.91) < 0.1

    def test_gcj02_to_wgs84_bounds(self, client: TestClient) -> None:
        """GCJ02 → WGS84 bounds：WGS84 应比 GCJ02 略偏西/南。"""
        resp = client.post(
            "/import/transform-bounds",
            json={
                "bounds": [116.0, 39.0, 117.0, 40.0],
                "source_crs": "GCJ02",
                "target_crs": "EPSG:4326",
            },
        )
        assert resp.status_code == 200
        w, s, e, n = resp.json()["bounds"]
        # 加密偏移约 +0.006°，WGS84 应比 GCJ02 偏西/南
        assert w < 116.0
        assert s < 39.0

    def test_invalid_bounds_length(self, client: TestClient) -> None:
        """bounds 元素数 != 4 应返回 400。"""
        resp = client.post(
            "/import/transform-bounds",
            json={"bounds": [1.0, 2.0, 3.0], "source_crs": "EPSG:4326"},
        )
        assert resp.status_code == 400


# ── /import/raster (upload) ────────────────────────────────────────────


class TestImportRaster:
    """``POST /import/raster`` 上传端点。"""

    def test_upload_wgs84_no_confirm(self, client: TestClient, wgs84_geotiff: Path) -> None:
        """上传 WGS84 TIF：needs_confirm=False，bounds 在 ±180/±90 内。"""
        try:
            with wgs84_geotiff.open("rb") as f:
                resp = client.post(
                    "/import/raster",
                    files={"file": ("wgs84.tif", f, "image/tiff")},
                )
            assert resp.status_code == 200
            data = resp.json()
            assert data["source_crs"] == "EPSG:4326"
            assert data["needs_confirm"] is False
            bounds = data["bounds"]
            assert -180 <= bounds[0] <= 180
            assert -90 <= bounds[1] <= 90
        finally:
            # 清理动态注册的 overlay
            layer_id = resp.json().get("layer_id") if resp.status_code == 200 else None
            if layer_id:
                client.delete(f"/import/raster/{layer_id}")

    def test_upload_utm50_needs_confirm(self, client: TestClient, utm50_geotiff: Path) -> None:
        """上传 EPSG:32650 TIF：needs_confirm=True，suggested_crs='EPSG:32650'。"""
        layer_id = None
        try:
            with utm50_geotiff.open("rb") as f:
                resp = client.post(
                    "/import/raster",
                    files={"file": ("utm50.tif", f, "image/tiff")},
                )
            assert resp.status_code == 200
            data = resp.json()
            assert data["source_crs"] == "EPSG:32650"
            assert data["needs_confirm"] is True
            assert data["suggested_crs"] == "EPSG:32650"
            layer_id = data["layer_id"]
        finally:
            if layer_id:
                client.delete(f"/import/raster/{layer_id}")


# ── /import/raster/confirm ─────────────────────────────────────────────


class TestRasterConfirm:
    """``POST /import/raster/confirm`` 端点。"""

    def test_confirm_utm50_to_wgs84(
        self, client: TestClient, utm50_geotiff: Path
    ) -> None:
        """上传 UTM 50N → confirm 用 source_crs='EPSG:32650' → 返回 WGS84 bounds。"""
        layer_id = None
        try:
            # 1. 上传
            with utm50_geotiff.open("rb") as f:
                resp = client.post(
                    "/import/raster",
                    files={"file": ("utm50.tif", f, "image/tiff")},
                )
            assert resp.status_code == 200
            layer_id = resp.json()["layer_id"]

            # 2. confirm
            resp = client.post(
                "/import/raster/confirm",
                json={
                    "layer_id": layer_id,
                    "source_crs": "EPSG:32650",
                    "lng_offset": 0.0,
                    "lat_offset": 0.0,
                },
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["source_crs"] == "EPSG:32650"
            assert data["target_crs"] == "EPSG:4326"
            assert data["applied_offset"] == [0.0, 0.0]
            w, s, e, n = data["bounds"]
            # WGS84 bounds 应在中国区域
            assert 70 < w < 140
            assert 0 < s < 60
            assert w < e and s < n

            # 3. 验证 overlay_registry 中 OverlaySpec.crs == 'EPSG:4326'
            spec = get_overlay_spec(layer_id)
            assert spec is not None
            assert spec.crs == "EPSG:4326"

            # 4. 验证 bounds.json 已更新
            from app.core.config import settings
            output_root = Path(settings.output_root) if settings.output_root else Path.cwd() / "imports_output"
            bounds_path = output_root / "imports" / layer_id / "bounds.json"
            bounds_data = json.loads(bounds_path.read_text(encoding="utf-8"))
            assert bounds_data["meta"]["crs"] == "EPSG:4326"
            assert bounds_data["meta"]["confirmed_source_crs"] == "EPSG:32650"
        finally:
            if layer_id:
                unregister_overlay(layer_id)
                client.delete(f"/import/raster/{layer_id}")

    def test_confirm_with_offset(
        self, client: TestClient, wgs84_geotiff: Path
    ) -> None:
        """confirm 带偏移：bounds 应在原 WGS84 基础上加 offset。"""
        layer_id = None
        try:
            with wgs84_geotiff.open("rb") as f:
                resp = client.post(
                    "/import/raster",
                    files={"file": ("wgs84.tif", f, "image/tiff")},
                )
            assert resp.status_code == 200
            layer_id = resp.json()["layer_id"]
            original_bounds = resp.json()["bounds"]

            # confirm 带 0.5° lng offset + 0.3° lat offset
            resp = client.post(
                "/import/raster/confirm",
                json={
                    "layer_id": layer_id,
                    "source_crs": "EPSG:4326",
                    "lng_offset": 0.5,
                    "lat_offset": 0.3,
                },
            )
            assert resp.status_code == 200
            data = resp.json()
            w, s, e, n = data["bounds"]
            # 偏移应在原 bounds 上加 0.5/0.3
            assert abs(w - (original_bounds[0] + 0.5)) < 1e-6
            assert abs(s - (original_bounds[1] + 0.3)) < 1e-6
            assert abs(e - (original_bounds[2] + 0.5)) < 1e-6
            assert abs(n - (original_bounds[3] + 0.3)) < 1e-6
        finally:
            if layer_id:
                unregister_overlay(layer_id)
                client.delete(f"/import/raster/{layer_id}")
