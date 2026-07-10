from __future__ import annotations

from dataclasses import dataclass
from math import atan2, cos, log, pi, sin, sqrt, tan
from typing import Literal

CoordinateSystem = Literal['EPSG:3857', 'GCJ-02', 'BD-09']

# WGS84 椭球体参数
_WGS84_A = 6378245.0
_WGS84_EE = 0.00669342162296594323


@dataclass(frozen=True)
class CoordinatePoint:
    lng: float
    lat: float


def _out_of_china(lng: float, lat: float) -> bool:
    return not (72.004 <= lng <= 137.8347 and 0.8293 <= lat <= 55.8271)


def _transform_lat(lng: float, lat: float) -> float:
    ret = -100.0 + 2.0 * lng + 3.0 * lat + 0.2 * lat * lat + 0.1 * lng * lat + 0.2 * sqrt(abs(lng))
    ret += (20.0 * sin(6.0 * lng * pi) + 20.0 * sin(2.0 * lng * pi)) * 2.0 / 3.0
    ret += (20.0 * sin(lat * pi) + 40.0 * sin(lat / 3.0 * pi)) * 2.0 / 3.0
    ret += (160.0 * sin(lat / 12.0 * pi) + 320 * sin(lat * pi / 30.0)) * 2.0 / 3.0
    return ret


def _transform_lng(lng: float, lat: float) -> float:
    ret = 300.0 + lng + 2.0 * lat + 0.1 * lng * lng + 0.1 * lng * lat + 0.1 * sqrt(abs(lng))
    ret += (20.0 * sin(6.0 * lng * pi) + 20.0 * sin(2.0 * lng * pi)) * 2.0 / 3.0
    ret += (20.0 * sin(lng * pi) + 40.0 * sin(lng / 3.0 * pi)) * 2.0 / 3.0
    ret += (150.0 * sin(lng / 12.0 * pi) + 300.0 * sin(lng / 30.0 * pi)) * 2.0 / 3.0
    return ret


def gcj02_to_wgs84(lng: float, lat: float) -> CoordinatePoint:
    if _out_of_china(lng, lat):
        return CoordinatePoint(lng=lng, lat=lat)
    dlat = _transform_lat(lng - 105.0, lat - 35.0)
    dlng = _transform_lng(lng - 105.0, lat - 35.0)
    radlat = lat / 180.0 * pi
    magic = 1 - _WGS84_EE * sin(radlat) ** 2
    sqrt_magic = sqrt(magic)
    dlat = (dlat * 180.0) / ((_WGS84_A * (1 - _WGS84_EE)) / (magic * sqrt_magic) * pi)
    dlng = (dlng * 180.0) / (_WGS84_A / sqrt_magic * cos(radlat) * pi)
    return CoordinatePoint(lng=lng * 2 - (lng + dlng), lat=lat * 2 - (lat + dlat))


def wgs84_to_epsg3857(lng: float, lat: float) -> CoordinatePoint:
    origin_shift = 20037508.342789244
    max_lat = 85.05112878
    clipped_lat = max(-max_lat, min(max_lat, lat))
    x = lng * origin_shift / 180.0
    y = log(tan((90.0 + clipped_lat) * pi / 360.0)) * origin_shift / pi
    return CoordinatePoint(lng=x, lat=y)


def bd09_to_gcj02(lng: float, lat: float) -> CoordinatePoint:
    x = lng - 0.0065
    y = lat - 0.006
    z = sqrt(x * x + y * y) - 0.00002 * sin(y * pi * 3000.0 / 180.0)
    theta = atan2(y, x) - 0.000003 * cos(x * pi * 3000.0 / 180.0)
    return CoordinatePoint(lng=z * cos(theta), lat=z * sin(theta))


def bd09_to_wgs84(lng: float, lat: float) -> CoordinatePoint:
    gcj = bd09_to_gcj02(lng, lat)
    return gcj02_to_wgs84(gcj.lng, gcj.lat)


def wgs84_to_gcj02(lng: float, lat: float) -> CoordinatePoint:
    """WGS84 转 GCJ-02"""
    if _out_of_china(lng, lat):
        return CoordinatePoint(lng=lng, lat=lat)
    dlat = _transform_lat(lng - 105.0, lat - 35.0)
    dlng = _transform_lng(lng - 105.0, lat - 35.0)
    radlat = lat / 180.0 * pi
    magic = 1 - _WGS84_EE * sin(radlat) ** 2
    sqrt_magic = sqrt(magic)
    dlat = (dlat * 180.0) / ((_WGS84_A * (1 - _WGS84_EE)) / (magic * sqrt_magic) * pi)
    dlng = (dlng * 180.0) / (_WGS84_A / sqrt_magic * cos(radlat) * pi)
    return CoordinatePoint(lng=lng + dlng, lat=lat + dlat)


def wgs84_to_bd09(lng: float, lat: float) -> CoordinatePoint:
    """WGS84 转 BD-09（先转 GCJ-02，再转 BD-09）"""
    gcj = wgs84_to_gcj02(lng, lat)
    x = gcj.lng
    y = gcj.lat
    z = sqrt(x * x + y * y) + 0.00002 * sin(y * pi * 3000.0 / 180.0)
    theta = atan2(y, x) + 0.000003 * cos(x * pi * 3000.0 / 180.0)
    return CoordinatePoint(lng=z * cos(theta), lat=z * sin(theta))


def transform_point(lng: float, lat: float, source: CoordinateSystem, target: CoordinateSystem = 'EPSG:3857') -> CoordinatePoint:
    if source == target:
        return CoordinatePoint(lng=lng, lat=lat)
    if source == 'BD-09' and target == 'EPSG:3857':
        point = bd09_to_wgs84(lng, lat)
        return wgs84_to_epsg3857(point.lng, point.lat)
    if source == 'GCJ-02' and target == 'EPSG:3857':
        point = gcj02_to_wgs84(lng, lat)
        return wgs84_to_epsg3857(point.lng, point.lat)
    if source == 'BD-09' and target == 'GCJ-02':
        return bd09_to_gcj02(lng, lat)
    raise ValueError(f'Unsupported transform: {source} -> {target}')
