/**
 * CRS 模块类型定义（镜像后端 `crs_types.py`）。
 *
 * 字段命名采用 camelCase（前端惯例），与后端 snake_case 通过 `toApiPayload`
 * 序列化层转换。
 */

export type CRSCategory = 'geographic' | 'encrypted' | 'projected'

export interface CRSDef {
  /** CRS code，如 `'EPSG:4326'` / `'GCJ02'` / `'BD09'` */
  code: string
  /** 人类可读标签 */
  label: string
  category: CRSCategory
  /** EPSG 整数代码；加密系为 null */
  epsg: number | null
  /** proj4 定义串；加密系为 null */
  proj4Def: string | null
  /** 适用区域：`'Global'` / `'China'` / `'Europe'` */
  area: string
  /** 是否已废弃（Phase 2 保留 deprecated 垫片时为 true） */
  deprecated: boolean
}

/** 前端下拉用平铺项（`toApiPayload()` 返回） */
export interface CRSOption {
  code: string
  label: string
  category: CRSCategory
  area: string
  deprecated: boolean
}

/** 坐标点（与后端 `CoordinatePoint` 字段顺序一致：lng 在前，lat 在后） */
export interface CoordinatePoint {
  lng: number
  lat: number
}

/** 转换选项：偏移在 CRS 转换**后**应用（与后端一致） */
export interface TransformOptions {
  lngOffset?: number
  latOffset?: number
}

/** CRS 自动检测结果（镜像后端 `CRSDetectionResult`） */
export interface CRSDetectionResult {
  sourceCrs: string
  /** 0~1，反映检测来源可靠程度 */
  confidence: number
  method: 'rasterio_crs' | 'geojson_crs' | 'bounds_heuristic' | 'default'
  suggestedCrs: string
  needsUserConfirm: boolean
  /** 检测过程说明（前端展示或日志） */
  notes: string
}
