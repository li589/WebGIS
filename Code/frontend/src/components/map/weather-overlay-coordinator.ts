import type { WeatherLayerRenderHint } from '../../services/runtime-api'
import type { ActiveLayerDisplay } from '../../stores/layers/types'
import {
  canRenderWeatherOverlayState,
  renderWeatherOverlayState,
  type WeatherOverlayRenderContext,
  type WeatherOverlayState,
} from './weather-overlay-registry'
import type { WindParticleControllerContract } from './wind-particle-controller-contract'

type DebugLogger = (module: string, ...args: unknown[]) => void

interface ResolveWeatherOverlayStatesOptions {
  activeLayers: ActiveLayerDisplay[]
  isWeatherEngineLayer: (catalogId: string) => boolean
  getMergedGeojsonForViewport: (catalogId: string) => WeatherOverlayState['geojsonData']
  /** 瓦片请求的目标视口 bounds（灰底占位用）；可选，缺省时占位不生效 */
  getViewportBounds?: (catalogId: string) => WeatherOverlayState['viewportBounds']
  buildDefaultWeatherRenderHint: (catalogId: string) => WeatherLayerRenderHint | null
  resolveApiUrl: (url: string) => string
  debugLog: DebugLogger
}

/**
 * grid_fill 图层的「上一良好快照」：瓦片合并瞬态为空（平移/缩放/退避窗口）时
 * 沿用快照，避免本 sync 把图层排除出 targets → prune 销毁 WebGL 层 → 下轮重建
 * 的「销毁-重建」闪烁循环。快照数据按地理锚定，新数据到达后自然被覆盖。
 */
const lastGoodGridFillStates = new Map<string, WeatherOverlayState>()

/**
 * particle_flow / barb 图层的「上一良好快照」：与 grid_fill 同理。
 * 缩放后瓦片合并瞬态为 null 时，若直接跳过状态 → reconcileParticleFlowController
 * 调用 reset() 销毁控制器（流线层/等值线层全部消失）→ 新瓦片到达后需完整重建，
 * 期间视口完全空白。沿用快照数据可保持画面，新数据到达后自然覆盖。
 */
const lastGoodParticleFlowStates = new Map<string, WeatherOverlayState>()

function hasInlineOrUrlData(state: WeatherOverlayState): boolean {
  return Boolean(state.geojsonData || state.geojsonUrl || (state.cogPreviewUrl && state.cogBbox))
}

export function resolveWeatherOverlayStates(
  options: ResolveWeatherOverlayStatesOptions,
): WeatherOverlayState[] {
  const states: WeatherOverlayState[] = []
  options.debugLog(
    'WeatherOverlayCoordinator',
    'resolveWeatherOverlayStates START',
    'activeLayersCount',
    options.activeLayers.length,
  )

  for (const layer of options.activeLayers) {
    if (!layer.visible || layer.isAdminBoundary) continue

    const state = options.isWeatherEngineLayer(layer.catalogId)
      ? buildWeatherEngineOverlayState(layer, options)
      : buildWorkflowOverlayState(layer, options)

    if (!state) continue

    if (state.renderHint.paint_mode === 'grid_fill') {
      if (hasInlineOrUrlData(state)) {
        lastGoodGridFillStates.set(layer.catalogId, state)
        states.push(state)
        continue
      }
      const lastGood = lastGoodGridFillStates.get(layer.catalogId)
      if (lastGood) {
        // 沿用快照数据（地理锚定），但透明度/视口占位用当前值
        states.push({
          ...lastGood,
          opacity: state.opacity,
          viewportBounds: state.viewportBounds ?? lastGood.viewportBounds ?? null,
        })
      } else if (state.viewportBounds) {
        // 首次加载：暂无数据，仅灰底占位
        states.push(state)
      }
      continue
    }

    // particle_flow / barb：有数据时保存快照；无数据时沿用快照避免控制器被 reset
    if (state.renderHint.paint_mode === 'particle_flow' || state.renderHint.paint_mode === 'barb') {
      if (hasInlineOrUrlData(state)) {
        lastGoodParticleFlowStates.set(layer.catalogId, state)
        states.push(state)
        continue
      }
      const lastGood = lastGoodParticleFlowStates.get(layer.catalogId)
      if (lastGood) {
        // 沿用上一良好数据（地理锚定），保持流线/粒子画面，
        // 新瓦片到达后 dataVersion bump → 新 sync 自然覆盖
        states.push({ ...lastGood, opacity: state.opacity })
      }
      continue
    }

    if (!canRenderWeatherOverlayState(state)) continue
    states.push(state)
  }

  return states
}

/** 图层移除时清理快照（session removeCatalogOverlay 之外显式调用） */
export function clearLastGoodGridFillState(catalogId: string): void {
  lastGoodGridFillStates.delete(catalogId)
  lastGoodParticleFlowStates.delete(catalogId)
}

interface ReconcileParticleFlowControllerOptions {
  enabledParticleFlowCatalogId: string | null
  targetCatalogIds: Set<string>
  windParticleController: WindParticleControllerContract | null
  removeCatalogOverlay: (catalogId: string) => void
}

export function reconcileParticleFlowController(options: ReconcileParticleFlowControllerOptions) {
  const { enabledParticleFlowCatalogId, targetCatalogIds, windParticleController } = options
  if (!windParticleController) return

  if (enabledParticleFlowCatalogId && !targetCatalogIds.has(enabledParticleFlowCatalogId)) {
    windParticleController.reset()
    windParticleController.activeCatalogId = null
  }

  if (enabledParticleFlowCatalogId !== windParticleController.activeCatalogId) {
    const previousParticleFlowCatalogId = windParticleController.activeCatalogId
    windParticleController.reset()
    windParticleController.activeCatalogId = enabledParticleFlowCatalogId

    if (previousParticleFlowCatalogId) {
      options.removeCatalogOverlay(previousParticleFlowCatalogId)
    }
  }
}

export function pruneStaleWeatherOverlays(
  renderedCatalogIds: Iterable<string>,
  targetCatalogIds: Set<string>,
  removeCatalogOverlay: (catalogId: string) => void,
) {
  for (const catalogId of renderedCatalogIds) {
    if (!targetCatalogIds.has(catalogId)) {
      removeCatalogOverlay(catalogId)
    }
  }
}

interface CreateWeatherOverlayRenderContextOptions {
  enabledParticleFlowCatalogId: string | null
  markRendered: (catalogId: string) => void
  syncWeatherCogOverlay: WeatherOverlayRenderContext['syncWeatherCogOverlay']
  syncWeatherGridFillOverlay: WeatherOverlayRenderContext['syncWeatherGridFillOverlay']
  syncWeatherHeatmapOverlay: WeatherOverlayRenderContext['syncWeatherHeatmapOverlay']
  syncWeatherPointOverlay: WeatherOverlayRenderContext['syncWeatherPointOverlay']
  syncWindParticleFlow: WeatherOverlayRenderContext['syncWindParticleFlow']
  syncScalarFieldWebGL: WeatherOverlayRenderContext['syncScalarFieldWebGL']
}

export function createWeatherOverlayRenderContext(
  options: CreateWeatherOverlayRenderContextOptions,
): WeatherOverlayRenderContext {
  return {
    enabledParticleFlowCatalogId: options.enabledParticleFlowCatalogId,
    markRendered: options.markRendered,
    syncWeatherCogOverlay: options.syncWeatherCogOverlay,
    syncWeatherGridFillOverlay: options.syncWeatherGridFillOverlay,
    syncWeatherHeatmapOverlay: options.syncWeatherHeatmapOverlay,
    syncWeatherPointOverlay: options.syncWeatherPointOverlay,
    syncWindParticleFlow: options.syncWindParticleFlow,
    syncScalarFieldWebGL: options.syncScalarFieldWebGL,
  }
}

interface RenderWeatherOverlayBatchOptions {
  targetStates: WeatherOverlayState[]
  overlayToken: number
  getSyncWeatherToken: () => number
  renderContext: WeatherOverlayRenderContext
}

export function renderWeatherOverlayBatch(options: RenderWeatherOverlayBatchOptions) {
  for (const state of options.targetStates) {
    if (options.overlayToken !== options.getSyncWeatherToken()) return false
    renderWeatherOverlayState(state, options.renderContext, options.overlayToken)
  }

  return true
}

function buildWeatherEngineOverlayState(
  layer: ActiveLayerDisplay,
  options: ResolveWeatherOverlayStatesOptions,
): WeatherOverlayState | null {
  const geojsonData = options.getMergedGeojsonForViewport(layer.catalogId)
  const renderHint = layer.renderHint ?? options.buildDefaultWeatherRenderHint(layer.catalogId)
  if (!renderHint) return null

  const viewportBounds = options.getViewportBounds?.(layer.catalogId) ?? null

  options.debugLog(
    'WeatherOverlayCoordinator',
    'resolveWeatherOverlay',
    layer.catalogId,
    'paint_mode',
    renderHint.paint_mode,
    'hasInlineGeojson',
    !!geojsonData,
    'featureCount',
    geojsonData && 'features' in geojsonData && Array.isArray(geojsonData.features)
      ? geojsonData.features.length
      : 0,
    'source',
    'tileManager',
  )

  return {
    catalogId: layer.catalogId,
    geojsonUrl: null,
    geojsonData,
    cogPreviewUrl: null,
    cogBbox: null,
    viewportBounds,
    renderHint,
    opacity: layer.opacity,
  } satisfies WeatherOverlayState
}

function buildWorkflowOverlayState(
  layer: ActiveLayerDisplay,
  options: ResolveWeatherOverlayStatesOptions,
): WeatherOverlayState | null {
  const renderHint = layer.jobLayer?.mapLayerPayload?.renderHint
  if (!renderHint) return null

  const geojsonUrl = layer.jobLayer?.mapLayerPayload?.layerAssets?.geojsonUrl
  const geojsonData = layer.jobLayer?.mapLayerPayload?.layerAssets?.geojsonData ?? null
  const cogPreviewUrl = layer.jobLayer?.mapLayerPayload?.layerAssets?.cogPreviewUrl
  const cogBbox = layer.jobLayer?.mapLayerPayload?.layerAssets?.cogBbox ?? null
  const resolvedGeojsonUrl =
    typeof geojsonUrl === 'string' && geojsonUrl.trim() ? options.resolveApiUrl(geojsonUrl) : null
  const resolvedCogPreviewUrl =
    typeof cogPreviewUrl === 'string' && cogPreviewUrl.trim()
      ? options.resolveApiUrl(cogPreviewUrl)
      : null

  options.debugLog(
    'WeatherOverlayCoordinator',
    'resolveWeatherOverlay',
    layer.catalogId,
    'paint_mode',
    renderHint.paint_mode,
    'hasInlineGeojson',
    !!geojsonData,
    'geojsonUrl',
    resolvedGeojsonUrl,
  )

  return {
    catalogId: layer.catalogId,
    geojsonUrl: resolvedGeojsonUrl,
    geojsonData,
    cogPreviewUrl: resolvedCogPreviewUrl,
    cogBbox,
    renderHint,
    opacity: layer.opacity,
  } satisfies WeatherOverlayState
}
