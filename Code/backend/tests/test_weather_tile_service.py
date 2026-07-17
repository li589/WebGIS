"""天气瓦片服务单元测试。"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from app.weatherengine.tile_service import (
    WeatherTileService,
    _grid_data_for_hour,
    tile_bbox,
    tile_key,
)


class TestTileBbox:
    """测试 Web Mercator z/x/y → EPSG:4326 转换。"""

    def test_tile_bbox_zoom_0_world(self):
        bbox = tile_bbox(0, 0, 0)
        assert bbox.crs == "EPSG:4326"
        assert bbox.west == pytest.approx(-180.0)
        assert bbox.east == pytest.approx(180.0)
        assert bbox.north == pytest.approx(85.0511287798066, rel=1e-9)
        assert bbox.south == pytest.approx(-85.0511287798066, rel=1e-9)

    def test_tile_bbox_zoom_5_25_12(self):
        bbox = tile_bbox(5, 25, 12)
        n = 2 ** 5
        assert bbox.west == pytest.approx(25 / n * 360.0 - 180.0)
        assert bbox.east == pytest.approx(26 / n * 360.0 - 180.0)
        # y=12 的北边纬度应大于 y=13 的南边纬度
        assert bbox.north > bbox.south
        assert abs(bbox.north) <= 85.0511287798066
        assert abs(bbox.south) <= 85.0511287798066


class TestTileKey:
    """测试瓦片缓存键格式。"""

    def test_tile_key_format(self):
        key = tile_key("wind-field", 3, 2, 1, 12, "best_match")
        assert key == "weather:tile:wind-field:z3:x2:y1:h12:mbest_match:pauto"

    def test_tile_key_default_model(self):
        key = tile_key("temperature", 4, 7, 7, 0, None)
        assert key == "weather:tile:temperature:z4:x7:y7:h0:mdefault:pauto"

    def test_tile_key_special_chars_escaped(self):
        key = tile_key("wind-field-850hPa", 2, 1, 1, 6, "ecmwf/res:0.25")
        assert key == "weather:tile:wind-field-850hPa:z2:x1:y1:h6:mecmwf_res_0.25:pauto"

    def test_tile_key_includes_provider(self):
        key = tile_key("wind-field", 3, 2, 1, 12, "best_match", "weatherapi")
        assert key == "weather:tile:wind-field:z3:x2:y1:h12:mbest_match:pweatherapi"
        assert tile_key("wind-field", 3, 2, 1, 12, "best_match", "auto") != key
        assert tile_key("wind-field", 3, 2, 1, 12, "best_match", None) != key


@pytest.fixture
def service():
    return WeatherTileService(max_concurrent=4)


@pytest.fixture
def sample_geojson():
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [113.0, 23.0]},
                "properties": {"wind_speed_10m": 5.2, "wind_direction_10m": 180},
            }
        ],
    }


@pytest.mark.anyio
async def test_invalid_layer_id_raises(service):
    with pytest.raises(ValueError, match="Unsupported weather layer"):
        await service.get_tile("not-a-layer", 3, 2, 1)


@pytest.mark.anyio
async def test_invalid_zoom_raises(service):
    with pytest.raises(ValueError, match="Tile zoom must be"):
        await service.get_tile("wind-field", 13, 0, 0)
    with pytest.raises(ValueError, match="Tile zoom must be"):
        await service.get_tile("wind-field", -1, 0, 0)


@pytest.mark.anyio
async def test_invalid_tile_coordinates_raises(service):
    with pytest.raises(ValueError, match="Invalid tile coordinates"):
        await service.get_tile("wind-field", 2, 4, 0)
    with pytest.raises(ValueError, match="Invalid tile coordinates"):
        await service.get_tile("wind-field", 2, 0, 4)


@pytest.mark.anyio
@patch("app.weatherengine.tile_service.cache_get_json", return_value=None)
@patch("app.weatherengine.tile_service.cache_set_json")
async def test_hour_clamped_and_cache_hit(
    mock_cache_set,
    mock_cache_get,
    service,
    sample_geojson,
):
    with patch.object(service, "_generate_tile", new_callable=AsyncMock) as mock_gen:
        mock_gen.return_value = sample_geojson

        # hour=99 应被钳制到 47
        geojson, status = await service.get_tile("wind-field", 3, 2, 1, hour=99)
        assert status == "miss"
        assert geojson == sample_geojson
        # 调用 _generate_tile 时 hour 已被钳制
        call_kwargs = mock_gen.call_args.kwargs
        assert call_kwargs["hour"] == 47


@pytest.mark.anyio
@patch("app.weatherengine.tile_service.cache_get_json", return_value=None)
@patch("app.weatherengine.tile_service.cache_set_json")
async def test_memory_cache_hit_on_second_call(
    mock_cache_set,
    mock_cache_get,
    service,
    sample_geojson,
):
    with patch.object(service, "_generate_tile", new_callable=AsyncMock) as mock_gen:
        mock_gen.return_value = sample_geojson

        _, status1 = await service.get_tile("wind-field", 3, 2, 1)
        assert status1 == "miss"
        # 同一瓦片第二次请求应命中内存缓存
        _, status2 = await service.get_tile("wind-field", 3, 2, 1)
        assert status2 == "hit"
        assert mock_gen.call_count == 1


@pytest.mark.anyio
@patch("app.weatherengine.tile_service.cache_get_json")
@patch("app.weatherengine.tile_service.cache_set_json")
async def test_redis_cache_hit(
    mock_cache_set,
    mock_cache_get,
    service,
    sample_geojson,
):
    mock_cache_get.return_value = sample_geojson

    with patch.object(service, "_generate_tile") as mock_gen:
        _, status = await service.get_tile("wind-field", 3, 2, 1)
        assert status == "hit"
        mock_gen.assert_not_called()


@pytest.mark.anyio
@patch("app.weatherengine.tile_service.cache_get_json", return_value=None)
@patch("app.weatherengine.tile_service.cache_set_json")
async def test_concurrent_generation_respects_semaphore(
    mock_cache_set,
    mock_cache_get,
    sample_geojson,
):
    """并发请求 6 个不同瓦片时，最多同时进入 _generate_tile 4 个。"""
    service = WeatherTileService(max_concurrent=4)
    active_count = 0
    max_active = 0
    lock = asyncio.Lock()

    async def slow_generate(*args, **kwargs):
        nonlocal active_count, max_active
        async with lock:
            active_count += 1
            max_active = max(max_active, active_count)
        await asyncio.sleep(0.05)
        async with lock:
            active_count -= 1
        return sample_geojson

    with patch.object(service, "_generate_tile", side_effect=slow_generate):
        results = await asyncio.gather(
            *[service.get_tile("wind-field", 3, i, 1) for i in range(6)]
        )

    assert len(results) == 6
    assert max_active <= 4


class TestGridDataForHour:
    """测试 _grid_data_for_hour 按小时索引正确性。"""

    def test_hour_zero_returns_original(self):
        grid_data = {
            "grid": {"rows": 2, "cols": 2},
            "data": {
                "current": {"wind_speed_10m": [1.0, 2.0, 3.0, 4.0]},
                "hourly": {"wind_speed_10m": [[1.0] * 4, [2.0] * 4, [3.0] * 4, [4.0] * 4]},
            },
        }
        result = _grid_data_for_hour(grid_data, 0)
        assert result is grid_data

    def test_extracts_per_point_hour_value(self):
        """验证按小时取值是为每个点取对应时间步，而不是取第 hour 个点的时间序列。"""
        grid_data = {
            "grid": {"rows": 2, "cols": 2},
            "data": {
                "current": {"wind_speed_10m": [0.0, 0.0, 0.0, 0.0]},
                "hourly": {
                    "wind_speed_10m": [
                        [10.0, 11.0, 12.0],  # point 0
                        [20.0, 21.0, 22.0],  # point 1
                        [30.0, 31.0, 32.0],  # point 2
                        [40.0, 41.0, 42.0],  # point 3
                    ],
                    "wind_direction_10m": [
                        [100.0, 110.0, 120.0],
                        [200.0, 210.0, 220.0],
                        [300.0, 310.0, 320.0],
                        [400.0, 410.0, 420.0],
                    ],
                },
            },
        }
        result = _grid_data_for_hour(grid_data, 2)
        current = result["data"]["current"]
        assert current["wind_speed_10m"] == [12.0, 22.0, 32.0, 42.0]
        assert current["wind_direction_10m"] == [120.0, 220.0, 320.0, 420.0]

    def test_falls_back_when_hourly_too_short(self):
        grid_data = {
            "grid": {"rows": 1, "cols": 2},
            "data": {
                "current": {"wind_speed_10m": [1.0, 2.0]},
                "hourly": {
                    "wind_speed_10m": [
                        [10.0, 11.0],
                        [20.0, 21.0],
                    ],
                },
            },
        }
        result = _grid_data_for_hour(grid_data, 5)
        assert result is grid_data

    def test_handles_missing_point_series(self):
        """验证当某个点的时间序列缺失或长度不足时填充 None。"""
        grid_data = {
            "grid": {"rows": 1, "cols": 2},
            "data": {
                "current": {"wind_speed_10m": [1.0, 2.0]},
                "hourly": {
                    "wind_speed_10m": [
                        [10.0, 11.0, 12.0],
                        [20.0, 21.0],  # shorter series
                    ],
                },
            },
        }
        result = _grid_data_for_hour(grid_data, 2)
        current = result["data"]["current"]
        assert current["wind_speed_10m"] == [12.0, None]
