import type { TileSourceConfig, TileSourceId } from '../../services/api-config'

type MapInstance = import('maplibre-gl').Map
type RasterSourceSpecification = import('maplibre-gl').RasterSourceSpecification
type RasterTileSource = import('maplibre-gl').RasterTileSource

const TILE_SOURCE_ID = 'tile-base'
const TILE_LAYER_ID = 'tile-base-raster'
const TILE_ERROR_WINDOW_MS = 5000
const TILE_ERROR_THRESHOLD = 15

export interface BasemapModule {
  ensureInitialLayer: (sourceId: TileSourceId) => void
  switchTileSource: (sourceId: TileSourceId) => void
  scheduleTileSourceSwitch: (sourceId: TileSourceId) => void
  handleTileError: (failedProvider: string | null) => void
  handleMapErrorEvent: (event: unknown) => void
  retryTileLoad: () => void
  dispose: () => void
}

interface CreateBasemapModuleOptions {
  map: MapInstance
  getTileConfig: (sourceId: TileSourceId) => TileSourceConfig | undefined
  getCurrentTileSourceId: () => TileSourceId
  setTileLoadFailed: (failed: boolean) => void
  setTileFailedProvider: (provider: string | null) => void
  setSourceTransitioning: (transitioning: boolean) => void
  onAfterSourceSwitch?: () => void
  dependencies?: {
    setTimeout?: typeof setTimeout
    clearTimeout?: typeof clearTimeout
    now?: () => number
  }
}

export function createBasemapModule(options: CreateBasemapModuleOptions): BasemapModule {
  const setTimeoutImpl = options.dependencies?.setTimeout ?? setTimeout
  const clearTimeoutImpl = options.dependencies?.clearTimeout ?? clearTimeout
  const nowImpl = options.dependencies?.now ?? Date.now

  const tileErrorTimestamps: number[] = []
  let switchTileToken = 0
  let sourceTransitionTimer: ReturnType<typeof setTimeout> | null = null
  let tileSourceDebounceHandle: ReturnType<typeof setTimeout> | null = null

  function ensureTileLayer(sourceId: TileSourceId) {
    const cfg = options.getTileConfig(sourceId)
    if (!cfg) return

    if (!options.map.getSource(TILE_SOURCE_ID)) {
      options.map.addSource(TILE_SOURCE_ID, {
        type: 'raster',
        tiles: [cfg.urlTemplate],
        tileSize: cfg.tileSize ?? 256,
        attribution: cfg.attribution,
        maxzoom: 18,
        scheme: 'xyz',
      } as RasterSourceSpecification)
    }

    if (!options.map.getLayer(TILE_LAYER_ID)) {
      const beforeLayerId = options.map.getLayer('admin-fill') ? 'admin-fill' : undefined
      options.map.addLayer(
        {
          id: TILE_LAYER_ID,
          type: 'raster',
          source: TILE_SOURCE_ID,
          layout: { visibility: 'none' },
          paint: {
            'raster-opacity': 0.88,
            'raster-saturation': cfg.saturation,
            'raster-brightness-max': Math.min(1.0, 1.0 + cfg.brightness),
            'raster-brightness-min': Math.max(0.0, Math.min(1.0, cfg.brightness)),
            'raster-contrast': cfg.contrast,
          },
        },
        beforeLayerId,
      )
    }
  }

  function triggerSourceTransition() {
    options.setSourceTransitioning(true)
    if (sourceTransitionTimer !== null) clearTimeoutImpl(sourceTransitionTimer)
    sourceTransitionTimer = setTimeoutImpl(() => {
      options.setSourceTransitioning(false)
      sourceTransitionTimer = null
    }, 260)
  }

  function resetTileErrorState() {
    options.setTileLoadFailed(false)
    options.setTileFailedProvider(null)
    tileErrorTimestamps.length = 0
  }

  function switchTileSource(sourceId: TileSourceId) {
    resetTileErrorState()

    if (sourceId === 'none') {
      if (options.map.getLayer(TILE_LAYER_ID)) {
        options.map.setLayoutProperty(TILE_LAYER_ID, 'visibility', 'none')
      }
      return
    }

    const cfg = options.getTileConfig(sourceId)
    if (!cfg) return

    const existingSource = options.map.getSource(TILE_SOURCE_ID) as RasterTileSource | undefined
    if (existingSource && existingSource.type === 'raster') {
      existingSource.setTiles([cfg.urlTemplate])
      options.map.triggerRepaint()
    }

    ensureTileLayer(sourceId)

    if (options.map.getLayer(TILE_LAYER_ID)) {
      options.map.setLayoutProperty(TILE_LAYER_ID, 'visibility', 'visible')
      options.map.setPaintProperty(TILE_LAYER_ID, 'raster-opacity', 0.88)
      options.map.setPaintProperty(TILE_LAYER_ID, 'raster-saturation', cfg.saturation)
      options.map.setPaintProperty(TILE_LAYER_ID, 'raster-brightness-max', Math.min(1.0, 1.0 + cfg.brightness))
      options.map.setPaintProperty(TILE_LAYER_ID, 'raster-brightness-min', Math.max(0.0, Math.min(1.0, cfg.brightness)))
      options.map.setPaintProperty(TILE_LAYER_ID, 'raster-contrast', cfg.contrast)
    }
  }

  function scheduleTileSourceSwitch(sourceId: TileSourceId) {
    if (tileSourceDebounceHandle !== null) {
      clearTimeoutImpl(tileSourceDebounceHandle)
    }
    const token = ++switchTileToken
    tileSourceDebounceHandle = setTimeoutImpl(() => {
      tileSourceDebounceHandle = null
      if (token !== switchTileToken) return
      triggerSourceTransition()
      switchTileSource(sourceId)
      options.onAfterSourceSwitch?.()
    }, 80)
  }

  function handleTileError(failedProvider: string | null) {
    const now = nowImpl()
    while (tileErrorTimestamps.length > 0 && now - tileErrorTimestamps[0] > TILE_ERROR_WINDOW_MS) {
      tileErrorTimestamps.shift()
    }
    tileErrorTimestamps.push(now)

    if (tileErrorTimestamps.length > TILE_ERROR_THRESHOLD) {
      options.setTileLoadFailed(true)
      options.setTileFailedProvider(
        failedProvider ?? options.getTileConfig(options.getCurrentTileSourceId())?.provider ?? null,
      )
      if (options.map.getLayer(TILE_LAYER_ID)) {
        options.map.setLayoutProperty(TILE_LAYER_ID, 'visibility', 'none')
      }
    }
  }

  function handleMapErrorEvent(event: unknown) {
    const mapError = event as {
      sourceId?: string
      error?: {
        status?: number
        url?: string
      }
    }

    if (mapError.sourceId !== TILE_SOURCE_ID && mapError.sourceId !== undefined) return

    const status = mapError.error?.status
    if (status !== undefined && status !== 0 && status !== 403 && status !== 404 && status !== 503) {
      return
    }

    const url = mapError.error?.url ?? ''
    const match = url.match(/\/tiles\/([^/]+)\//)
    const provider = match ? match[1] : null
    handleTileError(provider)
  }

  function retryTileLoad() {
    resetTileErrorState()
    if (!options.map.getSource(TILE_SOURCE_ID)) return

    const source = options.map.getSource(TILE_SOURCE_ID) as RasterTileSource | undefined
    const currentTileConfig = options.getTileConfig(options.getCurrentTileSourceId())
    if (source && source.type === 'raster' && currentTileConfig) {
      source.setTiles([currentTileConfig.urlTemplate])
      options.map.triggerRepaint()
    }
    if (options.map.getLayer(TILE_LAYER_ID) && options.getCurrentTileSourceId() !== 'none') {
      options.map.setLayoutProperty(TILE_LAYER_ID, 'visibility', 'visible')
    }
  }

  function dispose() {
    if (sourceTransitionTimer !== null) {
      clearTimeoutImpl(sourceTransitionTimer)
      sourceTransitionTimer = null
    }
    if (tileSourceDebounceHandle !== null) {
      clearTimeoutImpl(tileSourceDebounceHandle)
      tileSourceDebounceHandle = null
    }
  }

  return {
    ensureInitialLayer: ensureTileLayer,
    switchTileSource,
    scheduleTileSourceSwitch,
    handleTileError,
    handleMapErrorEvent,
    retryTileLoad,
    dispose,
  }
}
