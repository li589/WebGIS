/**
 * GCJ-02 / BD-09 纯 TypeScript 加密坐标转换算法。
 *
 * 从后端 `_gcj_bd.py` 直译。保留 `_WGS84_A = 6378245.0`（Krasovsky 1940 长半轴）—
 * 这是 GCJ-02 算法故意使用的常量，**不要改成 WGS84 的 6378137.0**，否则 GCJ-02
 * 偏移计算会出错。
 *
 * GCJ-02（火星坐标系）和 BD-09（百度坐标系）不是标准 EPSG 坐标系，而是中国
 * 官方/商业机构在 WGS84 基础上叠加的非线性加密偏移。本模块用纯 TS 实现逆向算法，
 * 不依赖 proj4。
 *
 * 导出 6 个函数，签名 `(lng, lat) => [number, number]`（返回 tuple，与后端
 * `CoordinatePoint` 字段顺序一致）。
 */

// Krasovsky 1940 长半轴 — GCJ-02 算法使用的椭球参数（故意的，非 WGS84 a=6378137）
const _WGS84_A = 6378245.0
// GCJ-02 算法使用的椭球第一偏心率平方（Krasovsky 1940）
const _WGS84_EE = 0.00669342162296594323

function _outOfChina(lng: number, lat: number): boolean {
  return !(72.004 <= lng && lng <= 137.8347 && 0.8293 <= lat && lat <= 55.8271)
}

function _transformLat(lng: number, lat: number): number {
  let ret = -100.0 + 2.0 * lng + 3.0 * lat + 0.2 * lat * lat + 0.1 * lng * lat + 0.2 * Math.sqrt(Math.abs(lng))
  ret += (20.0 * Math.sin(6.0 * lng * Math.PI) + 20.0 * Math.sin(2.0 * lng * Math.PI)) * 2.0 / 3.0
  ret += (20.0 * Math.sin(lat * Math.PI) + 40.0 * Math.sin(lat / 3.0 * Math.PI)) * 2.0 / 3.0
  ret += (160.0 * Math.sin(lat / 12.0 * Math.PI) + 320 * Math.sin(lat * Math.PI / 30.0)) * 2.0 / 3.0
  return ret
}

function _transformLng(lng: number, lat: number): number {
  let ret = 300.0 + lng + 2.0 * lat + 0.1 * lng * lng + 0.1 * lng * lat + 0.1 * Math.sqrt(Math.abs(lng))
  ret += (20.0 * Math.sin(6.0 * lng * Math.PI) + 20.0 * Math.sin(2.0 * lng * Math.PI)) * 2.0 / 3.0
  ret += (20.0 * Math.sin(lng * Math.PI) + 40.0 * Math.sin(lng / 3.0 * Math.PI)) * 2.0 / 3.0
  ret += (150.0 * Math.sin(lng / 12.0 * Math.PI) + 300.0 * Math.sin(lng / 30.0 * Math.PI)) * 2.0 / 3.0
  return ret
}

export function gcj02ToWgs84(lng: number, lat: number): [number, number] {
  if (_outOfChina(lng, lat)) return [lng, lat]
  let dlat = _transformLat(lng - 105.0, lat - 35.0)
  let dlng = _transformLng(lng - 105.0, lat - 35.0)
  const radlat = lat / 180.0 * Math.PI
  const magic = 1 - _WGS84_EE * Math.sin(radlat) ** 2
  const sqrtMagic = Math.sqrt(magic)
  dlat = (dlat * 180.0) / ((_WGS84_A * (1 - _WGS84_EE)) / (magic * sqrtMagic) * Math.PI)
  dlng = (dlng * 180.0) / (_WGS84_A / sqrtMagic * Math.cos(radlat) * Math.PI)
  return [lng * 2 - (lng + dlng), lat * 2 - (lat + dlat)]
}

export function wgs84ToGcj02(lng: number, lat: number): [number, number] {
  if (_outOfChina(lng, lat)) return [lng, lat]
  let dlat = _transformLat(lng - 105.0, lat - 35.0)
  let dlng = _transformLng(lng - 105.0, lat - 35.0)
  const radlat = lat / 180.0 * Math.PI
  const magic = 1 - _WGS84_EE * Math.sin(radlat) ** 2
  const sqrtMagic = Math.sqrt(magic)
  dlat = (dlat * 180.0) / ((_WGS84_A * (1 - _WGS84_EE)) / (magic * sqrtMagic) * Math.PI)
  dlng = (dlng * 180.0) / (_WGS84_A / sqrtMagic * Math.cos(radlat) * Math.PI)
  return [lng + dlng, lat + dlat]
}

export function bd09ToGcj02(lng: number, lat: number): [number, number] {
  const x = lng - 0.0065
  const y = lat - 0.006
  const z = Math.sqrt(x * x + y * y) - 0.00002 * Math.sin(y * Math.PI * 3000.0 / 180.0)
  const theta = Math.atan2(y, x) - 0.000003 * Math.cos(x * Math.PI * 3000.0 / 180.0)
  return [z * Math.cos(theta), z * Math.sin(theta)]
}

export function gcj02ToBd09(lng: number, lat: number): [number, number] {
  const x = lng
  const y = lat
  const z = Math.sqrt(x * x + y * y) + 0.00002 * Math.sin(y * Math.PI * 3000.0 / 180.0)
  const theta = Math.atan2(y, x) + 0.000003 * Math.cos(x * Math.PI * 3000.0 / 180.0)
  return [z * Math.cos(theta), z * Math.sin(theta)]
}

export function bd09ToWgs84(lng: number, lat: number): [number, number] {
  const gcj = bd09ToGcj02(lng, lat)
  return gcj02ToWgs84(gcj[0], gcj[1])
}

export function wgs84ToBd09(lng: number, lat: number): [number, number] {
  const gcj = wgs84ToGcj02(lng, lat)
  return gcj02ToBd09(gcj[0], gcj[1])
}