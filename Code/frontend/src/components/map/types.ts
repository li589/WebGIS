/**
 * 风场渲染共享类型与常量。
 * 所有风场图层（粒子流、等值线、风羽）共享此文件中的类型定义和常量。
 *
 * D1 修复后：真源已移至 src/types/map-geo.ts，本文件 re-export 保持向后兼容。
 */

export {
  DEFAULT_HEIGHT_SUFFIX,
  MAP_EVENT_MOVE,
  MAP_EVENT_MOVEEND,
  MAP_EVENT_MOVESTART,
  MAP_EVENT_RESIZE,
  MIN_VISIBLE_ZOOM,
  type WindGeoJSON,
  type WindGeoJSONFeature,
} from '../../types/map-geo'
