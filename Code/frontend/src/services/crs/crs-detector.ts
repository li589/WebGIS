/**
 * CRS 自动检测器 — 客户端轻量 bounds 启发式。
 *
 * 镜像后端 `_crs_detector.py` 的 `detect_from_bounds` 方法（Task 6.4.3 增强版，
 * 含 GK/Lambert 启发式）。raster 检测交给后端 `/import/raster` 端点，前端只做
 * bounds 启发式（用于无 CRS 元数据时的兜底建议）。
 *
 * 判断规则：
 * - west/east 在 ±180 内且 south/north 在 ±90 内 → 地理坐标系（confidence 0.5）
 * - X 在 39000000-42000000 → 高斯-克吕格 3 度带 zone 39/40/41（confidence 0.5）
 * - X 在 1000000-8000000 → Lambert Europe EPSG:3034（confidence 0.3）
 * - 其他大数值 → 默认 UTM 50N（confidence 0.3）
 * - 其他 → 默认 WGS84（confidence 0.3）
 */
import type { CRSDetectionResult } from './crs-types'

/** 客户端 bounds 启发式（与后端 _crs_detector.detect_from_bounds 一致，含 GK/Lambert 增强） */
export function detectFromBounds(bounds: [number, number, number, number]): CRSDetectionResult {
  const [w, s, e, n] = bounds
  const isGeographic =
    w >= -180 &&
    w <= 180 &&
    e >= -180 &&
    e <= 180 &&
    s >= -90 &&
    s <= 90 &&
    n >= -90 &&
    n <= 90 &&
    w < e &&
    s < n
  if (isGeographic) {
    return {
      sourceCrs: 'EPSG:4326',
      confidence: 0.5,
      method: 'bounds_heuristic',
      suggestedCrs: 'EPSG:4326',
      needsUserConfirm: true,
      notes: `bounds (${w},${s},${e},${n}) 在 ±180/±90 内，推断为地理坐标系`,
    }
  }
  if (Math.abs(w) > 180 || Math.abs(e) > 180) {
    // 高斯-克吕格 3 度带 false easting 模式：X 在 39000000-42000000（zone 39/40/41）
    if ((w > 39000000 && w < 42000000) || (e > 39000000 && e < 42000000)) {
      const midX = (w + e) / 2
      const zone = Math.floor(midX / 1000000)
      const suggested = zone === 40 ? 'EPSG:4528' : zone === 41 ? 'EPSG:4529' : 'EPSG:4527'
      return {
        sourceCrs: suggested,
        confidence: 0.5,
        method: 'bounds_heuristic',
        suggestedCrs: suggested,
        needsUserConfirm: true,
        notes: `bounds 匹配高斯-克吕格 3 度带（zone ${zone}），建议 ${suggested}`,
      }
    }
    // Lambert Europe (EPSG:3034, LCC Europe) 范围
    // 注意：EPSG:3035 是 LAEA（方位等积），不是 LCC；用户需求的"兰伯特等角圆锥"
    // 对应 EPSG:3034 (ETRS89 / LCC Europe)。
    if (w > 1000000 && w < 8000000 && e > 1000000 && e < 8000000) {
      return {
        sourceCrs: 'EPSG:3034',
        confidence: 0.3,
        method: 'bounds_heuristic',
        suggestedCrs: 'EPSG:3034',
        needsUserConfirm: true,
        notes: 'bounds 在 Lambert Europe 范围内，建议 EPSG:3034',
      }
    }
    return {
      sourceCrs: 'EPSG:32650',
      confidence: 0.3,
      method: 'bounds_heuristic',
      suggestedCrs: 'EPSG:32650',
      needsUserConfirm: true,
      notes: 'bounds 数值超出 ±180，推断为投影坐标系（默认建议 UTM 50N）',
    }
  }
  return {
    sourceCrs: 'EPSG:4326',
    confidence: 0.3,
    method: 'bounds_heuristic',
    suggestedCrs: 'EPSG:4326',
    needsUserConfirm: true,
    notes: 'bounds 无法明确分类，默认 WGS84',
  }
}
