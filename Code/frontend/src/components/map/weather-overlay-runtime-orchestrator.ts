import {
  createWeatherOverlayRenderContext,
  pruneStaleWeatherOverlays,
  reconcileParticleFlowController,
  renderWeatherOverlayBatch,
} from './weather-overlay-coordinator'
import { isPerfEnabled, perfIncSync, perfMark } from '../../utils/perf-probe'
import type { WeatherOverlayResolver } from './weather-overlay-resolver'
import { createWeatherOverlayServices } from './weather-overlay-services'
import type { WeatherOverlaySession } from './weather-overlay-session'
import type { WindParticleControllerContract } from './wind-particle-controller-contract'
import type { ScalarFieldWebGLController } from './scalar-field-webgl-controller'
import type { WindDisplayMode } from './wind-display-mode'

type MapInstance = import('maplibre-gl').Map
type DebugLogger = (module: string, ...args: unknown[]) => void

interface WeatherOverlayRuntimeOrchestratorDependencies {
  createOverlayServices?: typeof createWeatherOverlayServices
  createRenderContext?: typeof createWeatherOverlayRenderContext
  pruneStale?: typeof pruneStaleWeatherOverlays
  reconcileParticleFlow?: typeof reconcileParticleFlowController
  renderBatch?: typeof renderWeatherOverlayBatch
}

interface CreateWeatherOverlayRuntimeOrchestratorOptions {
  map: MapInstance
  resolver: WeatherOverlayResolver
  session: WeatherOverlaySession
  windParticleController: WindParticleControllerContract
  scalarFieldController?: ScalarFieldWebGLController | null
  getEnabledParticleFlowCatalogId: () => string | null
  getWindDisplayMode?: () => WindDisplayMode
  getSmoothRendering?: () => boolean
  getSyncWeatherToken: () => number
  debugLog: DebugLogger
  dependencies?: WeatherOverlayRuntimeOrchestratorDependencies
}

export interface WeatherOverlayRuntimeOrchestrator {
  sync: (overlayToken: number) => void
}

export function createWeatherOverlayRuntimeOrchestrator(
  options: CreateWeatherOverlayRuntimeOrchestratorOptions,
): WeatherOverlayRuntimeOrchestrator {
  const createOverlayServicesImpl =
    options.dependencies?.createOverlayServices ?? createWeatherOverlayServices
  const createRenderContextImpl =
    options.dependencies?.createRenderContext ?? createWeatherOverlayRenderContext
  const pruneStaleImpl = options.dependencies?.pruneStale ?? pruneStaleWeatherOverlays
  const reconcileParticleFlowImpl =
    options.dependencies?.reconcileParticleFlow ?? reconcileParticleFlowController
  const renderBatchImpl = options.dependencies?.renderBatch ?? renderWeatherOverlayBatch

  return {
    sync(overlayToken: number) {
      const syncStartedAt = isPerfEnabled() ? performance.now() : 0
      perfIncSync()
      const targetStates = options.resolver.resolveStates()
      const enabledFlowId = options.getEnabledParticleFlowCatalogId()
      const targetCatalogIds = new Set(targetStates.map((state) => state.catalogId))

      options.debugLog(
        'WeatherOverlayRuntimeOrchestrator',
        'sync start',
        'token',
        overlayToken,
        'enabledFlowId',
        enabledFlowId,
        'targets',
        targetStates.map((state) => ({
          catalogId: state.catalogId,
          paint_mode: state.renderHint.paint_mode,
          hasInlineGeojson: !!state.geojsonData,
          url: state.geojsonUrl,
        })),
      )

      pruneStaleImpl(
        options.session.renderedCatalogIds,
        targetCatalogIds,
        options.session.removeCatalogOverlay,
      )

      reconcileParticleFlowImpl({
        enabledParticleFlowCatalogId: enabledFlowId,
        targetCatalogIds,
        windParticleController: options.windParticleController,
        removeCatalogOverlay: options.session.removeCatalogOverlay,
      })

      const overlayServices = createOverlayServicesImpl({
        map: options.map,
        windParticleController: options.windParticleController,
        scalarFieldController: options.scalarFieldController ?? null,
        getSyncWeatherToken: options.getSyncWeatherToken,
        getEnabledParticleFlowCatalogId: options.getEnabledParticleFlowCatalogId,
        getWindDisplayMode: options.getWindDisplayMode,
        getSmoothRendering: options.getSmoothRendering,
      })

      renderBatchImpl({
        targetStates,
        overlayToken,
        getSyncWeatherToken: options.getSyncWeatherToken,
        renderContext: createRenderContextImpl({
          enabledParticleFlowCatalogId: enabledFlowId,
          markRendered: options.session.markRendered,
          ...overlayServices,
        }),
      })

      if (isPerfEnabled()) {
        perfMark('overlay.syncMs', {
          ms: Math.round(performance.now() - syncStartedAt),
          token: overlayToken,
          targets: targetStates.length,
          wind: enabledFlowId,
        })
      }
    },
  }
}
