/**
 * 风场渲染共享类型与常量。
 * 所有风场图层（粒子流、等值线、风羽）共享此文件中的类型定义和常量。
 */

// ── GeoJSON 风场数据 ──────────────────────────────────────

export interface WindGeoJSONFeature {
  type: 'Feature'
  geometry: { type: string; coordinates: number[] }
  properties: {
    row?: number
    col?: number
    height?: string
    wind_speed_10m?: number
    wind_direction_10m?: number
    [key: string]: unknown
  }
}

export interface WindGeoJSON {
  type: 'FeatureCollection'
  features: WindGeoJSONFeature[]
}

// ── 共享常量 ──────────────────────────────────────────────

/** 高度后缀默认值（气象高度层） */
export const DEFAULT_HEIGHT_SUFFIX = '10m'

/** MapLibre 地图事件名 */
export const MAP_EVENT_MOVE = 'move'
export const MAP_EVENT_MOVESTART = 'movestart'
export const MAP_EVENT_MOVEEND = 'moveend'
export const MAP_EVENT_RESIZE = 'resize'

/** 最小可视 zoom 级别（所有风场图层的统一阈值） */
export const MIN_VISIBLE_ZOOM = 3
