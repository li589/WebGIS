/**
 * 按 activeLayers.order 同步 MapLibre 图层叠序。
 * 约定：order 越大越靠近上层；行政区边界固定置于内容层之上（admin-fill 作锚点）。
 */
import { buildWeatherOverlayIds } from './weather-overlay-maplibre'
import type { ActiveLayer } from '../../stores/layers/types'

type MapInstance = import('maplibre-gl').Map

export interface LayerStackResolveContext {
  getImportedVectorLayerIds: (instanceId: string) => string[]
  getOverlayRasterLayerId: (overlayLayerId: string) => string | null
}

const ADMIN_STACK_IDS = ['admin-fill', 'admin-line'] as const

function collectWeatherLayerIds(map: MapInstance, catalogId: string): string[] {
  const ids = buildWeatherOverlayIds(catalogId)
  const paintOrder = [
    ids.rasterLayerId,
    ids.fillLayerId,
    ids.heatmapLayerId,
    ids.heatmapPointLayerId,
    ids.lineLayerId,
    ids.pointLayerId,
    ids.arrowLayerId,
  ]
  return paintOrder.filter((id) => Boolean(map.getLayer(id)))
}

function resolveMapLibreIds(
  map: MapInstance,
  layer: ActiveLayer,
  ctx: LayerStackResolveContext,
): string[] {
  if (layer.isAdminBoundary) {
    return ADMIN_STACK_IDS.filter((id) => Boolean(map.getLayer(id)))
  }
  if (layer.importedVector) {
    return ctx.getImportedVectorLayerIds(layer.instanceId)
  }
  if (layer.importedRaster) {
    const id = ctx.getOverlayRasterLayerId(layer.importedRaster.overlayLayerId)
    return id ? [id] : []
  }
  // catalog / weather / job overlay：优先天气子层，否则尝试 overlay raster
  const weatherIds = collectWeatherLayerIds(map, layer.catalogId)
  if (weatherIds.length > 0) return weatherIds
  const overlayId = ctx.getOverlayRasterLayerId(layer.catalogId)
  return overlayId ? [overlayId] : []
}

/**
 * 将非边界活动层按 order 自下而上叠到 admin-fill 之下（若存在）。
 * 行政区子层保持相对顺序并置于最上。
 */
export function applyActiveLayerStackOrder(
  map: MapInstance,
  activeLayers: ActiveLayer[],
  ctx: LayerStackResolveContext,
): void {
  const sorted = activeLayers.slice().sort((a, b) => a.order - b.order)
  const content = sorted.filter((l) => !l.isAdminBoundary)
  const hasAdmin = ADMIN_STACK_IDS.some((id) => Boolean(map.getLayer(id)))

  // 最高 order 先移到锚点下，再依次把更低的插到下方 → 最终高 order 更靠上
  let beforeId: string | undefined = hasAdmin ? 'admin-fill' : undefined
  for (let i = content.length - 1; i >= 0; i -= 1) {
    const mlIds = resolveMapLibreIds(map, content[i], ctx)
    for (let j = mlIds.length - 1; j >= 0; j -= 1) {
      const id = mlIds[j]
      if (!map.getLayer(id)) continue
      try {
        map.moveLayer(id, beforeId)
        beforeId = id
      } catch {
        // 图层短暂缺失时忽略
      }
    }
  }

  if (!hasAdmin) return
  // 确保行政区线 / 标注在 fill 之上（地图最上）
  let adminBefore: string | undefined
  for (let i = ADMIN_STACK_IDS.length - 1; i >= 0; i -= 1) {
    const id = ADMIN_STACK_IDS[i]
    if (!map.getLayer(id)) continue
    try {
      map.moveLayer(id, adminBefore)
      adminBefore = id
    } catch {
      // ignore
    }
  }
}
