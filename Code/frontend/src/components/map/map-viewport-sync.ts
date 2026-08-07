/**
 * 地图视口同步（组件层 re-export shim）。
 *
 * D1 修复后：实现已整体迁移至 src/utils/map-viewport.ts（纯函数、无组件依赖），
 * stores/services 直接依赖 utils；本文件 re-export 保持既有组件导入兼容。
 */
export {
  buildMapViewportSnapshot,
  estimateLngBoundsFromCenter,
  isNearGlobalLngSpan,
  NEAR_GLOBAL_LNG_SPAN_DEG,
  normalizeLngBounds,
  preferVisibleLngBounds,
  resolveVisibleLngBounds,
  resolveVisibleViewportBBox,
  type MapViewportBounds,
  type MapViewportReader,
  type MapViewportSnapshot,
} from '../../utils/map-viewport'
