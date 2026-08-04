"""``CRSTransformer`` 单元测试。

覆盖：
- 与旧 ``coordinate_transform_service.wgs84_to_epsg3857`` 精度对比
- GCJ-02/BD-09 与 ``_gcj_bd`` 纯算法完全一致
- UTM 50N ↔ WGS84 北京天安门往返
- EASE-Grid 2.0 (EPSG:6933) 往返 < 1m
- 偏移在 CRS 转换后应用
- LRU 缓存命中
- bounds 转换 + 批量点转换
"""

from __future__ import annotations


from app.services.crs import crs_transformer
from app.services.crs._crs_transformer import CRSTransformer
from app.services.crs._gcj_bd import bd09_to_wgs84, gcj02_to_wgs84

# ── 精度阈值 ──────────────────────────────────────────────────────────
_PRECISION_3857 = 1e-6  # 与旧 wgs84_to_epsg3857 对比精度
_PRECISION_GCJ = 1e-9  # GCJ-02 同算法路径，应几乎完全一致
_PRECISION_UTM = 1e-6  # UTM 往返精度（pyproj 高精度）


# ── 北京天安门测试点 ──────────────────────────────────────────────────
# WGS84 / GCJ-02 / BD-09 三套加密坐标（与 _gcj_bd.py 验证用例一致）
_BEIJING_WGS84 = (116.391226, 39.907397)
_BEIJING_GCJ02 = (116.39747, 39.90880)
_BEIJING_BD09 = (116.40375, 39.91512)
# 北京天安门在 UTM Zone 50N (EPSG:32650) 的坐标（由 _BEIJING_WGS84 经 pyproj 正算得到）
_BEIJING_UTM50 = (447964.931, 4417656.627)


class TestTransformPoint:
    """``transform_point`` 单点转换。"""

    def test_wgs84_to_epsg3857_matches_legacy(self):
        """与旧 ``wgs84_to_epsg3857`` 算法对比，1e-6 一致。"""
        from app.services.coordinate_transform_service import wgs84_to_epsg3857

        lng, lat = _BEIJING_WGS84
        legacy = wgs84_to_epsg3857(lng, lat)
        new = crs_transformer.transform_point(lng, lat, "EPSG:4326", "EPSG:3857")
        assert abs(new.lng - legacy.lng) < _PRECISION_3857
        assert abs(new.lat - legacy.lat) < _PRECISION_3857

    def test_gcj02_to_wgs84_matches_pure(self):
        """GCJ02 → WGS84 与 ``_gcj_bd.gcj02_to_wgs84`` 完全一致。"""
        lng, lat = _BEIJING_GCJ02
        expected = gcj02_to_wgs84(lng, lat)
        result = crs_transformer.transform_point(lng, lat, "GCJ02", "EPSG:4326")
        assert abs(result.lng - expected.lng) < _PRECISION_GCJ
        assert abs(result.lat - expected.lat) < _PRECISION_GCJ

    def test_bd09_to_wgs84_matches_pure(self):
        """BD09 → WGS84 与 ``_gcj_bd.bd09_to_wgs84`` 完全一致。"""
        lng, lat = _BEIJING_BD09
        expected = bd09_to_wgs84(lng, lat)
        result = crs_transformer.transform_point(lng, lat, "BD09", "EPSG:4326")
        assert abs(result.lng - expected.lng) < _PRECISION_GCJ
        assert abs(result.lat - expected.lat) < _PRECISION_GCJ

    def test_utm50_to_wgs84_beijing(self):
        """EPSG:32650 → EPSG:4326：北京天安门 UTM 反算。"""
        lng, lat = _BEIJING_UTM50
        result = crs_transformer.transform_point(lng, lat, "EPSG:32650", "EPSG:4326")
        # 与 WGS84 真值对比（pyproj 往返精度极高）
        assert abs(result.lng - _BEIJING_WGS84[0]) < _PRECISION_UTM
        assert abs(result.lat - _BEIJING_WGS84[1]) < _PRECISION_UTM

    def test_wgs84_to_utm50_roundtrip(self):
        """WGS84 → UTM 50N → WGS84 往返一致。"""
        lng, lat = _BEIJING_WGS84
        utm = crs_transformer.transform_point(lng, lat, "EPSG:4326", "EPSG:32650")
        back = crs_transformer.transform_point(
            utm.lng, utm.lat, "EPSG:32650", "EPSG:4326"
        )
        assert abs(back.lng - lng) < 1e-9
        assert abs(back.lat - lat) < 1e-9

    def test_ease_grid_roundtrip(self):
        """EPSG:6933 ↔ EPSG:4326 往返，误差 < 1m（≈ 1e-5 度）。"""
        # 用中国区域内一点（EASE-Grid 在中纬度精度足够）
        lng, lat = 105.0, 30.0
        to_ease = crs_transformer.transform_point(lng, lat, "EPSG:4326", "EPSG:6933")
        back = crs_transformer.transform_point(
            to_ease.lng, to_ease.lat, "EPSG:6933", "EPSG:4326"
        )
        assert abs(back.lng - lng) < 1e-5
        assert abs(back.lat - lat) < 1e-5

    def test_transform_gauss_kruger_4527_to_wgs84(self):
        """EPSG:4527 → EPSG:4326：北京天安门 GK zone 39 反算（往返一致）。

        先 WGS84 → GK 4527 正算得到北京 GK 坐标，再反算回 WGS84 验证往返一致。
        GK zone 39（CM 117°E，false easting 39500000）：北京 116.39°E 在 CM 以西
        0.6°，easting 应略小于 39500000（false_easting 39500000 + 负偏移）。
        """
        lng, lat = _BEIJING_WGS84
        gk = crs_transformer.transform_point(lng, lat, "EPSG:4326", "EPSG:4527")
        # easting 范围：北京在 CM 以西，easting < 39500000 + small offset
        assert 39400000 < gk.lng < 39550000
        # 北京 39.91°N → northing ≈ 4420000m
        assert 4400000 < gk.lat < 4450000
        # 反算回 WGS84 应与原值一致（pyproj 往返精度极高）
        back = crs_transformer.transform_point(gk.lng, gk.lat, "EPSG:4527", "EPSG:4326")
        assert abs(back.lng - lng) < 1e-9
        assert abs(back.lat - lat) < 1e-9

    def test_transform_lambert_3034_to_wgs84(self):
        """EPSG:3034 → EPSG:4326：欧洲中部点 LCC Europe 反算（往返一致）。

        用 (10.5°E, 53.0°N) 验证往返一致。EPSG:3034 (ETRS89 / LCC Europe) 原点
        (4000000, 2800000)，lat_0=52°N。测试点选 lat=53°（原点以北），确保
        Y > 2800000。LCC 投影非线性较强，往返精度约 1e-8 度（~1mm）。
        """
        lng, lat = 10.5, 53.0
        lcc = crs_transformer.transform_point(lng, lat, "EPSG:4326", "EPSG:3034")
        # LCC Europe 坐标范围：lat=53° 在原点以北，Y 应 > 2800000
        assert 4000000 < lcc.lng < 5000000
        assert 2800000 < lcc.lat < 3500000
        # 反算回 WGS84 应与原值一致（LCC 非线性投影，1e-7 ≈ 1cm）
        back = crs_transformer.transform_point(
            lcc.lng, lcc.lat, "EPSG:3034", "EPSG:4326"
        )
        assert abs(back.lng - lng) < 1e-7
        assert abs(back.lat - lat) < 1e-7

    def test_offset_applied_when_source_equals_target(self):
        """source == target：仅应用偏移。"""
        result = crs_transformer.transform_point(
            0, 0, "EPSG:4326", "EPSG:4326", 1.0, 2.0
        )
        assert result.lng == 1.0
        assert result.lat == 2.0

    def test_offset_applied_after_crs_transform(self):
        """偏移在 CRS 转换后应用：结果 = 纯转换 + offset。"""
        lng, lat = 116.0, 39.0
        pure = crs_transformer.transform_point(lng, lat, "EPSG:4326", "EPSG:3857")
        with_offset = crs_transformer.transform_point(
            lng, lat, "EPSG:4326", "EPSG:3857", 1.0, 2.0
        )
        assert abs(with_offset.lng - (pure.lng + 1.0)) < 1e-9
        assert abs(with_offset.lat - (pure.lat + 2.0)) < 1e-9

    def test_offset_applied_after_encrypted_transform(self):
        """加密系转换 + 偏移：偏移在 GCJ-02 → WGS84 后应用。"""
        lng, lat = _BEIJING_GCJ02
        pure = crs_transformer.transform_point(lng, lat, "GCJ02", "EPSG:4326")
        with_offset = crs_transformer.transform_point(
            lng, lat, "GCJ02", "EPSG:4326", 0.5, -0.3
        )
        assert abs(with_offset.lng - (pure.lng + 0.5)) < 1e-9
        assert abs(with_offset.lat - (pure.lat + -0.3)) < 1e-9

    def test_source_equals_target_no_offset(self):
        """source == target 且无偏移：原样返回。"""
        result = crs_transformer.transform_point(
            116.391, 39.907, "EPSG:4326", "EPSG:4326"
        )
        assert result.lng == 116.391
        assert result.lat == 39.907

    def test_gcj02_to_epsg3857_via_wgs84(self):
        """GCJ02 → EPSG:3857（混合路径：GCJ02 → WGS84 → EPSG:3857）。"""
        from app.services.coordinate_transform_service import wgs84_to_epsg3857

        lng, lat = _BEIJING_GCJ02
        result = crs_transformer.transform_point(lng, lat, "GCJ02", "EPSG:3857")
        # 先 GCJ02 -> WGS84
        w = gcj02_to_wgs84(lng, lat)
        # 再 WGS84 -> 3857
        expected = wgs84_to_epsg3857(w.lng, w.lat)
        assert abs(result.lng - expected.lng) < _PRECISION_3857
        assert abs(result.lat - expected.lat) < _PRECISION_3857

    def test_bd09_to_gcj02(self):
        """BD09 → GCJ02（经 WGS84 中转）。"""
        lng, lat = _BEIJING_BD09
        result = crs_transformer.transform_point(lng, lat, "BD09", "GCJ02")
        # 期望路径：BD09 -> WGS84 -> GCJ02
        w = bd09_to_wgs84(lng, lat)
        from app.services.crs._gcj_bd import wgs84_to_gcj02

        expected = wgs84_to_gcj02(w.lng, w.lat)
        assert abs(result.lng - expected.lng) < _PRECISION_GCJ
        assert abs(result.lat - expected.lat) < _PRECISION_GCJ


class TestLRUCache:
    """LRU 缓存行为。"""

    def test_cache_hit(self, monkeypatch):
        """连续两次相同 (source, target) 调用，第二次 ``_CACHE`` 命中。"""
        # 清空缓存
        CRSTransformer._CACHE.clear()
        # 用 monkeypatch 计数 from_crs 调用
        import pyproj

        call_count = 0
        original_from_crs = pyproj.Transformer.from_crs

        def counting_from_crs(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return original_from_crs(*args, **kwargs)

        monkeypatch.setattr(pyproj.Transformer, "from_crs", counting_from_crs)
        try:
            # 第一次调用：cache miss
            crs_transformer.transform_point(116.0, 39.0, "EPSG:4326", "EPSG:3857")
            assert call_count == 1
            # 第二次调用：cache hit
            crs_transformer.transform_point(117.0, 40.0, "EPSG:4326", "EPSG:3857")
            assert call_count == 1  # 仍为 1，未再次构造
        finally:
            CRSTransformer._CACHE.clear()

    def test_encrypted_not_cached(self, monkeypatch):
        """加密系转换不触发 pyproj.Transformer.from_crs。"""
        CRSTransformer._CACHE.clear()
        import pyproj

        call_count = 0
        original_from_crs = pyproj.Transformer.from_crs

        def counting_from_crs(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return original_from_crs(*args, **kwargs)

        monkeypatch.setattr(pyproj.Transformer, "from_crs", counting_from_crs)
        try:
            # GCJ02 -> WGS84 纯算法，不触发 from_crs
            crs_transformer.transform_point(
                _BEIJING_GCJ02[0], _BEIJING_GCJ02[1], "GCJ02", "EPSG:4326"
            )
            assert call_count == 0
            assert len(CRSTransformer._CACHE) == 0
        finally:
            CRSTransformer._CACHE.clear()


class TestTransformBounds:
    """``transform_bounds`` 测试。"""

    def test_wgs84_to_wgs84_identity(self):
        """source == target：原样返回。"""
        bounds = (73.0, 15.0, 137.0, 59.0)
        result = crs_transformer.transform_bounds(*bounds, "EPSG:4326", "EPSG:4326")
        assert result == bounds

    def test_utm50_to_wgs84_bounds(self):
        """EPSG:32650 → EPSG:4326 bounds 转换。"""
        # 北京附近 1km x 1km 区域（基于天安门 UTM 坐标）
        e0, n0 = _BEIJING_UTM50
        bounds = (e0 - 500, n0 - 500, e0 + 500, n0 + 500)
        w, s, e, n = crs_transformer.transform_bounds(
            *bounds, "EPSG:32650", "EPSG:4326"
        )
        # 应在中国区域内
        assert 70 < w < 140
        assert 0 < s < 60
        assert w < e
        assert s < n
        # 中心点应接近天安门
        center_lng = (w + e) / 2
        center_lat = (s + n) / 2
        assert abs(center_lng - _BEIJING_WGS84[0]) < 0.01
        assert abs(center_lat - _BEIJING_WGS84[1]) < 0.01

    def test_gcj02_to_wgs84_bounds(self):
        """GCJ02 → WGS84 bounds：四角点转换后取 min/max。"""
        bounds = (116.0, 39.0, 117.0, 40.0)
        w, s, e, n = crs_transformer.transform_bounds(*bounds, "GCJ02", "EPSG:4326")
        # WGS84 应比 GCJ02 略偏西/南（加密偏移约 +0.006°）
        assert w < 116.0
        assert s < 39.0
        assert e < 117.0
        assert n < 40.0
        # 偏移量级合理（< 0.02°）
        assert abs(w - 116.0) < 0.02
        assert abs(n - 40.0) < 0.02


class TestTransformPointsBatch:
    """``transform_points_batch`` 批量转换。"""

    def test_batch_wgs84_to_gcj02(self):
        """批量 WGS84 → GCJ02，结果与逐点一致。"""
        points = [(116.391, 39.907), (121.473, 31.230), (113.264, 23.129)]
        batch = crs_transformer.transform_points_batch(points, "EPSG:4326", "GCJ02")
        assert len(batch) == 3
        for (lng, lat), pt in zip(points, batch):
            expected = crs_transformer.transform_point(lng, lat, "EPSG:4326", "GCJ02")
            assert abs(pt.lng - expected.lng) < 1e-9
            assert abs(pt.lat - expected.lat) < 1e-9

    def test_batch_with_offset(self):
        """批量转换 + 偏移。"""
        points = [(0, 0), (1, 1)]
        result = crs_transformer.transform_points_batch(
            points, "EPSG:4326", "EPSG:4326", 0.5, 0.5
        )
        assert result[0].lng == 0.5
        assert result[0].lat == 0.5
        assert result[1].lng == 1.5
        assert result[1].lat == 1.5

    def test_batch_epsg3857(self):
        """批量 WGS84 → EPSG:3857，结果与逐点一致。"""
        points = [(_BEIJING_WGS84[0], _BEIJING_WGS84[1]), (0, 0)]
        batch = crs_transformer.transform_points_batch(points, "EPSG:4326", "EPSG:3857")
        assert len(batch) == 2
        for (lng, lat), pt in zip(points, batch):
            expected = crs_transformer.transform_point(
                lng, lat, "EPSG:4326", "EPSG:3857"
            )
            assert abs(pt.lng - expected.lng) < 1e-9
            assert abs(pt.lat - expected.lat) < 1e-9

    def test_batch_empty(self):
        """空输入返回空列表。"""
        result = crs_transformer.transform_points_batch([], "EPSG:4326", "EPSG:3857")
