"""GCJ-02 / BD-09 纯 Python 加密坐标转换算法。

从 ``app/services/coordinate_transform_service.py`` 原样搬迁。
保留 ``_WGS84_A = 6378245.0``（Krasovsky 1940 长半轴）— 这是 GCJ-02 算法
故意使用的常量，**不要改成 WGS84 的 6378137.0**，否则 GCJ-02 偏移计算会出错。

GCJ-02（火星坐标系）和 BD-09（百度坐标系）不是标准 EPSG 坐标系，
而是中国官方/商业机构在 WGS84 基础上叠加的非线性加密偏移。
本模块用纯 Python 实现逆向算法，不依赖 pyproj。
"""
from __future__ import annotations

from math import atan2, cos, log, pi, sin, sqrt

from .crs_types import CoordinatePoint

# Krasovsky 1940 长半轴 — GCJ-02 算法使用的椭球参数（故意的，非 WGS84 a=6378137）
_WGS84_A = 6378245.0
# GCJ-02 算法使用的椭球第一偏心率平方（Krasovsky 1940）
_WGS84_EE = 0.00669342162296594323


def _out_of_china(lng: float, lat: float) -> bool:
    """判断点是否在中国境外（境外不应用 GCJ-02 偏移）。"""
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
    """GCJ-02 → WGS84（逆向偏移）。中国境外原样返回。"""
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


def wgs84_to_gcj02(lng: float, lat: float) -> CoordinatePoint:
    """WGS84 → GCJ-02（正向偏移）。中国境外原样返回。"""
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


def bd09_to_gcj02(lng: float, lat: float) -> CoordinatePoint:
    """BD-09 → GCJ-02。"""
    x = lng - 0.0065
    y = lat - 0.006
    z = sqrt(x * x + y * y) - 0.00002 * sin(y * pi * 3000.0 / 180.0)
    theta = atan2(y, x) - 0.000003 * cos(x * pi * 3000.0 / 180.0)
    return CoordinatePoint(lng=z * cos(theta), lat=z * sin(theta))


def gcj02_to_bd09(lng: float, lat: float) -> CoordinatePoint:
    """GCJ-02 → BD-09（百度坐标系正向偏移，``bd09_to_gcj02`` 的逆运算）。"""
    x = lng
    y = lat
    z = sqrt(x * x + y * y) + 0.00002 * sin(y * pi * 3000.0 / 180.0)
    theta = atan2(y, x) + 0.000003 * cos(x * pi * 3000.0 / 180.0)
    return CoordinatePoint(lng=z * cos(theta), lat=z * sin(theta))


def bd09_to_wgs84(lng: float, lat: float) -> CoordinatePoint:
    """BD-09 → WGS84（先 BD-09 → GCJ-02 → WGS84）。"""
    gcj = bd09_to_gcj02(lng, lat)
    return gcj02_to_wgs84(gcj.lng, gcj.lat)


def wgs84_to_bd09(lng: float, lat: float) -> CoordinatePoint:
    """WGS84 → BD-09（先 WGS84 → GCJ-02 → BD-09）。"""
    gcj = wgs84_to_gcj02(lng, lat)
    return gcj02_to_bd09(gcj.lng, gcj.lat)