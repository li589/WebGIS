"""
Open-Meteo API 性能测试脚本

测试内容：
1. 单点位天气查询延迟（p50, p95, p99）
2. 不同 bbox 大小的数据传输量
3. 并发请求下的性能表现
4. 缓存命中率对性能的影响
"""

from __future__ import annotations

import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from statistics import mean, median

# 添加 backend 和 Code 根目录到 sys.path（与 conftest.py 保持一致）
_BACKEND_ROOT = Path(__file__).resolve().parent.parent
_CODE_ROOT = _BACKEND_ROOT.parent

for path in (str(_BACKEND_ROOT), str(_CODE_ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)

from app.weatherengine.client import OpenMeteoClient
from app.weatherengine.service import WeatherEngineService


class OpenMeteoPerformanceTests:
    """Open-Meteo API 性能测试"""

    def test_single_point_query_latency(self) -> None:
        """测试单点位天气查询延迟"""
        client = OpenMeteoClient()

        latitudes = [22.5, 23.0, 23.5, 24.0, 24.5]
        longitudes = [113.0, 113.5, 114.0, 114.5, 115.0]

        latencies = []

        for lat, lon in zip(latitudes, longitudes):
            start = time.perf_counter()
            result = client.fetch_point_forecast(
                latitude=lat,
                longitude=lon,
                variables=["temperature_2m", "wind_speed_10m", "wind_direction_10m"],
            )
            elapsed = time.perf_counter() - start
            latencies.append(elapsed)

        latencies.sort()
        p50 = latencies[len(latencies) // 2]
        p95 = latencies[int(len(latencies) * 0.95)]
        p99 = latencies[int(len(latencies) * 0.99)]

        print("\n单点位查询延迟统计：")
        print(f"  平均: {mean(latencies):.3f}s")
        print(f"  中位数: {median(latencies):.3f}s")
        print(f"  P50: {p50:.3f}s")
        print(f"  P95: {p95:.3f}s")
        print(f"  P99: {p99:.3f}s")
        print(f"  最小: {min(latencies):.3f}s")
        print(f"  最大: {max(latencies):.3f}s")

        # 性能基准：P95 < 2s
        assert p95 < 2.0, f"P95 延迟 {p95:.3f}s 超过 2s 基准"

    def test_data_transfer_size(self) -> None:
        """测试不同 bbox 大小的数据传输量"""
        client = OpenMeteoClient()

        test_cases = [
            ("小范围 (1°x1°)", 22.5, 113.0, 23.5, 114.0),
            ("中范围 (2°x2°)", 22.0, 112.0, 24.0, 114.0),
            ("大范围 (5°x5°)", 20.0, 110.0, 25.0, 115.0),
        ]

        for name, south, west, north, east in test_cases:
            start = time.perf_counter()
            result = client.fetch_point_forecast(
                latitude=(south + north) / 2,
                longitude=(west + east) / 2,
                variables=["temperature_2m", "wind_speed_10m", "wind_direction_10m"],
            )
            elapsed = time.perf_counter() - start

            # 估算数据大小
            data_size = len(str(result))

            print(f"\n{name}:")
            print(f"  延迟: {elapsed:.3f}s")
            print(f"  数据大小: {data_size / 1024:.2f} KB")

    def test_concurrent_requests(self) -> None:
        """测试并发请求下的性能表现"""
        client = OpenMeteoClient()

        def fetch_weather(lat: float, lon: float) -> tuple[float, float]:
            start = time.perf_counter()
            client.fetch_point_forecast(
                latitude=lat,
                longitude=lon,
                variables=["temperature_2m", "wind_speed_10m"],
            )
            elapsed = time.perf_counter() - start
            return (lat, elapsed)

        # 并发请求数
        num_requests = 10
        latitudes = [22.0 + i * 0.1 for i in range(num_requests)]
        longitudes = [113.0 + i * 0.1 for i in range(num_requests)]

        start_total = time.perf_counter()

        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [
                executor.submit(fetch_weather, lat, lon)
                for lat, lon in zip(latitudes, longitudes)
            ]
            results = [f.result() for f in futures]

        total_elapsed = time.perf_counter() - start_total
        latencies = [elapsed for _, elapsed in results]

        print(f"\n并发请求性能统计（{num_requests} 个请求，5 个并发）：")
        print(f"  总耗时: {total_elapsed:.3f}s")
        print(f"  平均延迟: {mean(latencies):.3f}s")
        print(f"  中位数: {median(latencies):.3f}s")
        print(f"  最小: {min(latencies):.3f}s")
        print(f"  最大: {max(latencies):.3f}s")
        print(f"  吞吐量: {num_requests / total_elapsed:.2f} req/s")

    def test_cache_hit_rate(self) -> None:
        """测试缓存命中率对性能的影响"""
        service = WeatherEngineService()

        # 第一次查询（缓存未命中）
        start1 = time.perf_counter()
        result1 = service.get_point_weather(
            layer_id="wind-field",
            latitude=22.5,
            longitude=113.5,
            forecast_hours=[0, 1, 2, 3],
        )
        elapsed1 = time.perf_counter() - start1

        # 第二次查询相同参数（缓存命中）
        start2 = time.perf_counter()
        result2 = service.get_point_weather(
            layer_id="wind-field",
            latitude=22.5,
            longitude=113.5,
            forecast_hours=[0, 1, 2, 3],
        )
        elapsed2 = time.perf_counter() - start2

        # 第三次查询不同参数（缓存未命中）
        start3 = time.perf_counter()
        result3 = service.get_point_weather(
            layer_id="wind-field",
            latitude=23.0,
            longitude=114.0,
            forecast_hours=[0, 1, 2, 3],
        )
        elapsed3 = time.perf_counter() - start3

        print("\n缓存命中率测试：")
        print(f"  第一次查询（未命中）: {elapsed1:.3f}s")
        print(f"  第二次查询（命中）: {elapsed2:.3f}s")
        print(f"  第三次查询（未命中）: {elapsed3:.3f}s")
        print(f"  缓存加速比: {elapsed1 / elapsed2:.2f}x")

        # 缓存命中应该显著快于未命中
        if elapsed2 > 0:
            speedup = elapsed1 / elapsed2
            print(
                f"  缓存效果: {'显著' if speedup > 2 else '一般' if speedup > 1.5 else '不明显'}"
            )


if __name__ == "__main__":
    test = OpenMeteoPerformanceTests()

    print("=" * 60)
    print("Open-Meteo API 性能测试")
    print("=" * 60)

    print("\n1. 单点位查询延迟测试")
    test.test_single_point_query_latency()

    print("\n2. 数据传输量测试")
    test.test_data_transfer_size()

    print("\n3. 并发请求性能测试")
    test.test_concurrent_requests()

    print("\n4. 缓存命中率测试")
    test.test_cache_hit_rate()

    print("\n" + "=" * 60)
    print("性能测试完成")
    print("=" * 60)
