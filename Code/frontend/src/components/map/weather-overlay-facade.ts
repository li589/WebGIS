import type { WeatherOverlayResolver } from './weather-overlay-resolver'
import {
  createWeatherOverlayRuntimeOrchestrator,
  type WeatherOverlayRuntimeOrchestrator,
} from './weather-overlay-runtime-orchestrator'
import { createWeatherOverlaySession, type WeatherOverlaySession } from './weather-overlay-session'
import {
  createWeatherOverlaySyncScheduler,
  type WeatherOverlaySyncScheduler,
} from './weather-overlay-sync-scheduler'
import type { WindParticleControllerContract } from './wind-particle-controller-contract'
import { createDefaultWindParticleController } from './wind-particle-controller-factory'
import { ScalarFieldWebGLController } from './scalar-field-webgl-controller'
import type { WindDisplayMode } from './wind-display-mode'

type MapInstance = import('maplibre-gl').Map
type DebugLogger = (module: string, ...args: unknown[]) => void

interface WeatherOverlayFacadeDependencies {
  createWindParticleController?: (map: MapInstance) => WindParticleControllerContract
  createScalarFieldController?: (map: MapInstance) => ScalarFieldWebGLController | null
  createSession?: (options: {
    map: MapInstance
    windParticleController: WindParticleControllerContract
    scalarFieldController: ScalarFieldWebGLController | null
  }) => WeatherOverlaySession
  createScheduler?: (options: {
    debounceMs: number
    zoomDebounceMs?: number
    hourDebounceMs?: number
    debugLog: DebugLogger
  }) => WeatherOverlaySyncScheduler
  createRuntimeOrchestrator?: (options: {
    map: MapInstance
    resolver: WeatherOverlayResolver
    session: WeatherOverlaySession
    windParticleController: WindParticleController
    scalarFieldController: ScalarFieldWebGLController | null
    getEnabledParticleFlowCatalogId: () => string | null
    getWindDisplayMode?: () => WindDisplayMode
    getSyncWeatherToken: () => number
    debugLog: DebugLogger
  }) => WeatherOverlayRuntimeOrchestrator
}

type WindParticleController = WindParticleControllerContract

interface CreateWeatherOverlayFacadeOptions {
  map: MapInstance
  getMapReady: () => boolean
  resolver: WeatherOverlayResolver
  getEnabledParticleFlowCatalogId: () => string | null
  getWindDisplayMode?: () => WindDisplayMode
  debugLog: DebugLogger
  debounceMs?: number
  dependencies?: WeatherOverlayFacadeDependencies
}

export interface WeatherOverlayFacade {
  scheduleSync: (reason?: 'move' | 'zoom' | 'data' | 'hour') => void
  runSyncNow: () => void
  dispose: () => void
}

export function createWeatherOverlayFacade(
  options: CreateWeatherOverlayFacadeOptions,
): WeatherOverlayFacade {
  const createWindParticleControllerImpl = options.dependencies?.createWindParticleController
    ?? createDefaultWindParticleController
  const createScalarFieldControllerImpl = options.dependencies?.createScalarFieldController
    ?? ((map: MapInstance) => new ScalarFieldWebGLController(map))
  const createSessionImpl = options.dependencies?.createSession ?? createWeatherOverlaySession
  const createSchedulerImpl = options.dependencies?.createScheduler ?? createWeatherOverlaySyncScheduler
  const createRuntimeOrchestratorImpl = options.dependencies?.createRuntimeOrchestrator
    ?? createWeatherOverlayRuntimeOrchestrator

  const windParticleController = createWindParticleControllerImpl(options.map)
  const scalarFieldController = createScalarFieldControllerImpl(options.map)
  const weatherOverlaySession = createSessionImpl({
    map: options.map,
    windParticleController,
    scalarFieldController,
  })
  const weatherOverlaySyncScheduler = createSchedulerImpl({
    debounceMs: options.debounceMs ?? 200,
    zoomDebounceMs: 110,
    hourDebounceMs: 100,
    debugLog: options.debugLog,
  })
  const runtimeOrchestrator = createRuntimeOrchestratorImpl({
    map: options.map,
    resolver: options.resolver,
    session: weatherOverlaySession,
    windParticleController,
    scalarFieldController,
    getEnabledParticleFlowCatalogId: options.getEnabledParticleFlowCatalogId,
    getWindDisplayMode: options.getWindDisplayMode,
    getSyncWeatherToken: weatherOverlaySyncScheduler.getCurrentToken,
    debugLog: options.debugLog,
  })

  return {
    scheduleSync(reason: 'move' | 'zoom' | 'data' | 'hour' = 'data') {
      weatherOverlaySyncScheduler.schedule(() => {
        if (!options.getMapReady()) return
        runtimeOrchestrator.sync(weatherOverlaySyncScheduler.beginSync())
      }, reason)
    },
    runSyncNow() {
      weatherOverlaySyncScheduler.runNow(() => {
        if (!options.getMapReady()) return
        runtimeOrchestrator.sync(weatherOverlaySyncScheduler.beginSync())
      })
    },
    dispose() {
      weatherOverlaySyncScheduler.dispose()
      weatherOverlaySession.removeAllOverlays()
    },
  }
}
