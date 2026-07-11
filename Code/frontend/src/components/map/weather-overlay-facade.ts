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
import { WindParticleOverlayController } from './wind-particle-overlay-controller'

type MapInstance = import('maplibre-gl').Map
type DebugLogger = (module: string, ...args: unknown[]) => void

interface WeatherOverlayFacadeDependencies {
  createWindParticleController?: (map: MapInstance) => WindParticleOverlayController
  createSession?: (options: { map: MapInstance; windParticleController: WindParticleOverlayController }) => WeatherOverlaySession
  createScheduler?: (options: { debounceMs: number; debugLog: DebugLogger }) => WeatherOverlaySyncScheduler
  createRuntimeOrchestrator?: (options: {
    map: MapInstance
    resolver: WeatherOverlayResolver
    session: WeatherOverlaySession
    windParticleController: WindParticleController
    getEnabledParticleFlowCatalogId: () => string | null
    getSyncWeatherToken: () => number
    debugLog: DebugLogger
  }) => WeatherOverlayRuntimeOrchestrator
}

type WindParticleController = WindParticleOverlayController

interface CreateWeatherOverlayFacadeOptions {
  map: MapInstance
  getMapReady: () => boolean
  resolver: WeatherOverlayResolver
  getEnabledParticleFlowCatalogId: () => string | null
  debugLog: DebugLogger
  debounceMs?: number
  dependencies?: WeatherOverlayFacadeDependencies
}

export interface WeatherOverlayFacade {
  scheduleSync: () => void
  runSyncNow: () => void
  dispose: () => void
}

export function createWeatherOverlayFacade(
  options: CreateWeatherOverlayFacadeOptions,
): WeatherOverlayFacade {
  const createWindParticleControllerImpl = options.dependencies?.createWindParticleController
    ?? ((map: MapInstance) => new WindParticleOverlayController(map))
  const createSessionImpl = options.dependencies?.createSession ?? createWeatherOverlaySession
  const createSchedulerImpl = options.dependencies?.createScheduler ?? createWeatherOverlaySyncScheduler
  const createRuntimeOrchestratorImpl = options.dependencies?.createRuntimeOrchestrator
    ?? createWeatherOverlayRuntimeOrchestrator

  const windParticleController = createWindParticleControllerImpl(options.map)
  const weatherOverlaySession = createSessionImpl({
    map: options.map,
    windParticleController,
  })
  const weatherOverlaySyncScheduler = createSchedulerImpl({
    debounceMs: options.debounceMs ?? 200,
    debugLog: options.debugLog,
  })
  const runtimeOrchestrator = createRuntimeOrchestratorImpl({
    map: options.map,
    resolver: options.resolver,
    session: weatherOverlaySession,
    windParticleController,
    getEnabledParticleFlowCatalogId: options.getEnabledParticleFlowCatalogId,
    getSyncWeatherToken: weatherOverlaySyncScheduler.getCurrentToken,
    debugLog: options.debugLog,
  })

  return {
    scheduleSync() {
      weatherOverlaySyncScheduler.schedule(() => {
        if (!options.getMapReady()) return
        runtimeOrchestrator.sync(weatherOverlaySyncScheduler.beginSync())
      })
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
