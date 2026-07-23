"""全球对齐格网 / 半开瓦片归属。"""

from __future__ import annotations

import pytest

from app.weatherengine.field_mapping import (
    aligned_grid_axes,
    lat_centers_half_open,
    lon_centers_half_open,
    point_in_tile_half_open,
)
from app.weatherengine.tile_service import tile_bbox, zoom_to_resolution
from shared.contracts.api_contracts import BoundingBox


class TestAlignedGridAxes:
    def test_adjacent_lon_tiles_share_no_centers(self):
        res = 1.0
        left = BoundingBox(
            west=110.0, south=20.0, east=115.0, north=25.0, crs="EPSG:4326"
        )
        right = BoundingBox(
            west=115.0, south=20.0, east=120.0, north=25.0, crs="EPSG:4326"
        )
        _, lons_l, _ = aligned_grid_axes(left, res)
        _, lons_r, _ = aligned_grid_axes(right, res)
        assert set(lons_l).isdisjoint(set(lons_r))
        # 贴合：左瓦最东格心 + res == 右瓦最西格心
        assert max(lons_l) + res == pytest.approx(min(lons_r))

    def test_adjacent_lat_tiles_share_no_centers(self):
        res = 1.0
        north_tile = BoundingBox(
            west=110.0, south=25.0, east=115.0, north=30.0, crs="EPSG:4326"
        )
        south_tile = BoundingBox(
            west=110.0, south=20.0, east=115.0, north=25.0, crs="EPSG:4326"
        )
        lats_n, _, _ = aligned_grid_axes(north_tile, res)
        lats_s, _, _ = aligned_grid_axes(south_tile, res)
        assert set(lats_n).isdisjoint(set(lats_s))

    def test_web_mercator_neighbors_at_high_lat(self):
        """高纬相邻 y 瓦片：半开归属无共点（旧算法高纬叠框更明显）。"""
        z = 5
        res = zoom_to_resolution(z)
        # 选较高纬度的一列瓦片
        a = tile_bbox(z, 20, 8)
        b = tile_bbox(z, 20, 9)
        assert a.south == pytest.approx(b.north)
        lats_a, lons_a, _ = aligned_grid_axes(a, res)
        lats_b, lons_b, _ = aligned_grid_axes(b, res)
        assert set(lats_a).isdisjoint(set(lats_b))
        assert set(zip(lons_a, lats_a) if False else lats_a).isdisjoint(set(lats_b))
        # 经度列在同 x 应对齐
        assert (
            set(lons_a) == set(lons_b)
            or set(lons_a).issubset(set(lons_b))
            or set(lons_b).issubset(set(lons_a))
        )

    def test_half_open_predicates(self):
        assert point_in_tile_half_open(
            110.0, 25.0, west=110, south=20, east=115, north=25
        )
        assert not point_in_tile_half_open(
            115.0, 22.0, west=110, south=20, east=115, north=25
        )
        assert not point_in_tile_half_open(
            112.0, 20.0, west=110, south=20, east=115, north=25
        )

    def test_centers_on_global_lattice(self):
        lons = lon_centers_half_open(-180.0, -170.0, 5.0)
        assert all(
            abs((lon / 5.0) - 0.5 - round(lon / 5.0 - 0.5)) < 1e-9 for lon in lons
        )
        lats = lat_centers_half_open(0.0, 10.0, 2.5)
        # 北→南
        assert lats == sorted(lats, reverse=True)

    def test_equator_neighbor_tiles_are_lattice_continuous(self):
        """跨赤道相邻 Mercator 瓦片：格心应相差恰好一个 res，无空洞/重叠。"""
        z = 3
        res = zoom_to_resolution(z)
        north_tile = tile_bbox(z, 4, 3)  # south≈0
        south_tile = tile_bbox(z, 4, 4)  # north≈0
        assert north_tile.south == pytest.approx(south_tile.north)
        lats_n, _, _ = aligned_grid_axes(north_tile, res)
        lats_s, _, _ = aligned_grid_axes(south_tile, res)
        assert lats_n and lats_s
        assert set(lats_n).isdisjoint(set(lats_s))
        assert min(lats_n) - max(lats_s) == pytest.approx(res)
