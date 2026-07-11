import type { WeatherLayerRenderHint } from '../../services/runtime-api'
import type { ActiveLayerDisplay } from '../../stores/layers/types'
import {
  canRenderWeatherOverlayState,
  renderWeatherOverlayState,
  type WeatherOverlayRenderContext,
  type WeatherOverlayState,
} from './weather-overlay-registry'
import { WindParticleOverlayController } from './wind-particle-overlay-controller'

type DebugLogger = (module: string, ...args: unknown[]) => void

interface ResolveWeatherOverlayStatesOptions {
  activeLayers: ActiveLayerDisplay[]
  isWeatherEngineLayer: (catalogId: string) => boolean
  getMergedGeojsonForViewport: (catalogId: string) => WeatherOverlayState['geojsonData']
  buildDefaultWeatherRenderHint: (catalogId: string) => WeatherLayerRenderHint | null
  resolveApiUrl: (url: string) => string
  debugLog: DebugLogger
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

    if (!state || !canRenderWeatherOverlayState(state)) continue
    states.push(state)
  }

  return states
}

interface ReconcileParticleFlowControllerOptions {
  enabledParticleFlowCatalogId: string | null
  targetCatalogIds: Set<string>
  windParticleController: WindParticleOverlayController | null
  removeCatalogOverlay: (catalogId: string) => void
}

export function reconcileParticleFlowController(
  options: ReconcileParticleFlowControllerOptions,
) {
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
  }
}

interface RenderWeatherOverlayBatchOptions {
  targetStates: WeatherOverlayState[]
  overlayToken: number
  getSyncWeatherToken: () => number
  renderContext: WeatherOverlayRenderContext
}

export function renderWeatherOverlayBatch(
  options: RenderWeatherOverlayBatchOptions,
) {
  for (const state of options.targetStates) {
    if (options.overlayToken !== options.getSyncWeatherToken()) return false
    renderWeatherOverlayState(state, options.renderContext, options.overlayToken)
  }

  return true
}

function buildWeatherEngineOverlayState(
  layer: ActiveLayerDisplay,
  options: ResolveWeatherOverlayStatesOptions,
) {
  const geojsonData = options.getMergedGeojsonForViewport(layer.catalogId)
  const renderHint = layer.renderHint ?? options.buildDefaultWeatherRenderHint(layer.catalogId)
  if (!renderHint) return null

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
    renderHint,
    opacity: layer.opacity,
  } satisfies WeatherOverlayState
}

function buildWorkflowOverlayState(
  layer: ActiveLayerDisplay,
  options: ResolveWeatherOverlayStatesOptions,
) {
  const renderHint = layer.jobLayer?.mapLayerPayload?.renderHint
  if (!renderHint) return null

  const geojsonUrl = layer.jobLayer?.mapLayerPayload?.layerAssets?.geojsonUrl
  const geojsonData = layer.jobLayer?.mapLayerPayload?.layerAssets?.geojsonData ?? null
  const cogPreviewUrl = layer.jobLayer?.mapLayerPayload?.layerAssets?.cogPreviewUrl
  const cogBbox = layer.jobLayer?.mapLayerPayload?.layerAssets?.cogBbox ?? null
  const resolvedGeojsonUrl = typeof geojsonUrl === 'string' && geojsonUrl.trim()
    ? options.resolveApiUrl(geojsonUrl)
    : null
  const resolvedCogPreviewUrl = typeof cogPreviewUrl === 'string' && cogPreviewUrl.trim()
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
