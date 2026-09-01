/**
 * 分析工具 × 图层能力解析：栅格/矢量 overlay id、输入类型推导。
 * 供 tool-page-model、analysis-runner、AutoStatsCard 共用，避免口径漂移。
 */
import type { ActiveLayerDisplay } from '../../../stores/layers/types'
import type { AnalysisToolDescriptor } from '../../../services/analysis-api'

export interface ToolRunContext {
  displayLayer: ActiveLayerDisplay
  selectedMapPoint: { lng: number; lat: number } | null
  hasMapBBox: boolean
}

export interface ToolInputRequirement {
  needsRaster: boolean
  needsVector: boolean
  needsPoint: boolean
  needsMapBBox: boolean
}

/**
 * 图层是否具备可读栅格 overlay。
 * 不含纯矢量导入、行政区、无物化产物的占位层；天气层由调用方 is_weather 另行过滤。
 */
export function layerHasReadableRaster(layer: ActiveLayerDisplay): boolean {
  if (layer.isImportedRaster || layer.importedRasterOverlayLayerId) return true
  // 导入/绘制矢量不是栅格输入（勿因 dataState=real 误报 has_raster）
  if (layer.isImported) return false
  if (layer.isAdminBoundary) return false
  if (layer.jobLayer?.mapLayerPayload) return true
  // 目录科学/静态 overlay：catalogId 即可作 overlay_layer_id
  if (
    (layer.dataState === 'catalog' || layer.dataState === 'real') &&
    layer.catalogId &&
    !layer.importedVectorBackendLayerId
  ) {
    return true
  }
  return false
}

/** 提交 / 点查 / 分区统计用的 overlay_layer_id */
export function resolveRasterOverlayId(layer: ActiveLayerDisplay): string | null {
  if (layer.importedRasterOverlayLayerId) return layer.importedRasterOverlayLayerId
  if (layer.isImportedRaster && layer.catalogId) return layer.catalogId
  if (layer.isImported || layer.isAdminBoundary) return null
  const assetOverlayId = layer.jobLayer?.mapLayerPayload?.layerAssets?.overlayLayerId
  if (assetOverlayId) return assetOverlayId
  if (
    (layer.dataState === 'catalog' || layer.dataState === 'real') &&
    layer.catalogId &&
    !layer.importedVectorBackendLayerId
  ) {
    return layer.catalogId
  }
  return null
}

/** 已登记后端的导入矢量层 id */
export function resolveVectorBackendId(layer: ActiveLayerDisplay): string | null {
  return layer.importedVectorBackendLayerId ?? null
}

/** 有矢量几何但未登记后端（绘制草稿等） */
export function hasDraftVector(layer: ActiveLayerDisplay): boolean {
  return Boolean(layer.isImported && !layer.importedVectorBackendLayerId)
}

export function hasPersistedVector(layer: ActiveLayerDisplay): boolean {
  return Boolean(layer.importedVectorBackendLayerId)
}

export function buildToolRunContext(
  displayLayer: ActiveLayerDisplay,
  selectedMapPoint: { lng: number; lat: number } | null,
  hasMapBBox: boolean,
): ToolRunContext {
  return { displayLayer, selectedMapPoint, hasMapBBox }
}

const RASTER_TOOL_IDS = new Set([
  'gis.clip',
  'gis.reclassify',
  'gis.zonal_stats',
  'gis.contour',
  'gis.slope_aspect',
  'gis.raster_calc',
  'gis.raster_to_vector',
  'gis.watershed',
])

/** 从目录 input_kinds 与 tool_id 推导前置数据需求 */
export function inferToolInputRequirement(tool: AnalysisToolDescriptor): ToolInputRequirement {
  const kinds = new Set(tool.input_kinds.map((k) => k.toLowerCase()))
  const needsRaster = kinds.has('raster') || RASTER_TOOL_IDS.has(tool.tool_id)
  const needsVector = kinds.has('vector') && !kinds.has('point')
  const needsPoint =
    kinds.has('point') || tool.tool_id === 'gis.buffer' || tool.tool_id === 'gis.watershed'
  const needsMapBBox = tool.tool_id === 'gis.clip'
  return { needsRaster, needsVector, needsPoint, needsMapBBox }
}

/** AutoStats / 多图层对比：从 active layer 记录解析栅格 overlay id */
export function resolveRasterOverlayIdFromActiveLayer(layer: {
  visible?: boolean
  importedRaster?: { overlayLayerId?: string } | null
  importedRasterOverlayLayerId?: string
  importedVector?: unknown
  importedVectorBackendLayerId?: string
  catalogId: string
  dataState?: string
  isImportedRaster?: boolean
  isImported?: boolean
  isAdminBoundary?: boolean
}): string | null {
  if (layer.importedRaster?.overlayLayerId) return layer.importedRaster.overlayLayerId
  if (layer.importedRasterOverlayLayerId) return layer.importedRasterOverlayLayerId
  if (layer.isImportedRaster) return layer.catalogId
  if (layer.isImported || layer.isAdminBoundary || layer.importedVector) return null
  if (layer.importedVectorBackendLayerId) return null
  if (layer.dataState === 'catalog' || layer.dataState === 'real') return layer.catalogId || null
  return null
}

export function activeLayerHasReadableRaster(layer: {
  importedRaster?: unknown
  importedRasterOverlayLayerId?: string
  importedVector?: unknown
  importedVectorBackendLayerId?: string
  catalogId: string
  dataState?: string
  isImportedRaster?: boolean
  isImported?: boolean
  isAdminBoundary?: boolean
}): boolean {
  return resolveRasterOverlayIdFromActiveLayer(layer) != null
}
