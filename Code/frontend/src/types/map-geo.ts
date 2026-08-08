/**
 * 风场 GeoJSON 数据与地图事件共享类型/常量。
 *
 * 从 components/map/types.ts 提取（D1 依赖倒置修复）：
 * stores/ 与 services/ 应依赖本模块，不得反向依赖 components/map/。
 * components/map/types.ts 保留 re-export 以兼容既有组件导入。
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

/** 最小可视 zoom 级别（所有风场图层的统一阈值）。
 *  设为 0 使全球视图下也可见风场图层（粒子数量会根据 zoom 降级）。 */
export const MIN_VISIBLE_ZOOM = 0
