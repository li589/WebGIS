import { describe, expect, it, vi } from 'vitest'

import { createBasemapModule } from '@/components/map/basemap-module'

function createMapMock() {
  const sources = new Map<string, any>()
  const layers = new Set<string>()

  return {
    sources,
    layers,
    map: {
      getSource: (id: string) => sources.get(id),
      addSource: (id: string, source: any) => {
        sources.set(id, source)
      },
      removeSource: (id: string) => {
        sources.delete(id)
      },
      getLayer: (id: string) => (layers.has(id) ? { id } : undefined),
      addLayer: (layer: { id: string }) => {
        layers.add(layer.id)
      },
      removeLayer: (id: string) => {
        layers.delete(id)
      },
      setLayoutProperty: vi.fn(),
      setPaintProperty: vi.fn(),
      triggerRepaint: vi.fn(),
    } as any,
  }
}

describe('basemap-module', () => {
  it('debounces tile source switching and notifies after switch', () => {
    let timerId = 0
    const scheduled = new Map<number, () => void>()
    const { map, layers, sources } = createMapMock()
    const setTileLoadFailed = vi.fn()
    const setTileFailedProvider = vi.fn()
    const setSourceTransitioning = vi.fn()
    const onAfterSourceSwitch = vi.fn()

    const module = createBasemapModule({
      map,
      getTileConfig: (sourceId) =>
        sourceId === 'esri-street'
          ? {
              id: 'esri-street',
              label: 'Esri Street',
              provider: 'Esri',
              style: 'street',
              urlTemplate: 'https://example.com/{z}/{x}/{y}.png',
              saturation: 0,
              brightness: 0,
              contrast: 0,
              isStandard: true,
              needsBackendTransform: false,
              authMode: 'none',
            }
          : undefined,
      getCurrentTileSourceId: () => 'esri-street',
      setTileLoadFailed,
      setTileFailedProvider,
      setSourceTransitioning,
      onAfterSourceSwitch,
      dependencies: {
        setTimeout: ((callback: () => void) => {
          timerId += 1
          scheduled.set(timerId, callback)
          return timerId as unknown as ReturnType<typeof setTimeout>
        }) as typeof setTimeout,
        clearTimeout: ((id: ReturnType<typeof setTimeout>) => {
          scheduled.delete(id as unknown as number)
        }) as typeof clearTimeout,
      },
    })

    module.scheduleTileSourceSwitch('esri-street')
    module.scheduleTileSourceSwitch('esri-street')

    expect(scheduled.size).toBe(1)
    scheduled.get(2)?.()

    expect(sources.has('tile-base')).toBe(true)
    expect(layers.has('tile-base-raster')).toBe(true)
    expect(setTileLoadFailed).toHaveBeenCalledWith(false)
    expect(setTileFailedProvider).toHaveBeenCalledWith(null)
    expect(setSourceTransitioning).toHaveBeenCalledWith(true)
    expect(onAfterSourceSwitch).toHaveBeenCalledTimes(1)
  })

  it('marks repeated tile failures and can retry current source', () => {
    const { map, sources } = createMapMock()
    const source = {
      type: 'raster',
      setTiles: vi.fn(),
    }
    sources.set('tile-base', source)
    map.getLayer = () => ({ id: 'tile-base-raster' })

    const setTileLoadFailed = vi.fn()
    const setTileFailedProvider = vi.fn()
    let now = 0

    const module = createBasemapModule({
      map,
      getTileConfig: (sourceId) =>
        sourceId === 'esri-street'
          ? {
              id: 'esri-street',
              label: 'Esri Street',
              provider: 'Esri',
              style: 'street',
              urlTemplate: 'https://example.com/{z}/{x}/{y}.png',
              saturation: 0,
              brightness: 0,
              contrast: 0,
              isStandard: true,
              needsBackendTransform: false,
              authMode: 'none',
            }
          : undefined,
      getCurrentTileSourceId: () => 'esri-street',
      setTileLoadFailed,
      setTileFailedProvider,
      setSourceTransitioning: vi.fn(),
      dependencies: {
        now: () => {
          now += 100
          return now
        },
      },
    })

    for (let index = 0; index < 16; index += 1) {
      module.handleTileError('Esri')
    }

    expect(setTileLoadFailed).toHaveBeenLastCalledWith(true)
    expect(setTileFailedProvider).toHaveBeenLastCalledWith('Esri')

    module.retryTileLoad()

    expect(setTileLoadFailed).toHaveBeenLastCalledWith(false)
    expect(setTileFailedProvider).toHaveBeenLastCalledWith(null)
    expect(source.setTiles).toHaveBeenCalledWith(['https://example.com/{z}/{x}/{y}.png'])
    expect(map.triggerRepaint).toHaveBeenCalled()
    expect(map.setLayoutProperty).toHaveBeenCalledWith('tile-base-raster', 'visibility', 'visible')
  })

  it('parses map error events for the managed tile source only', () => {
    const { map } = createMapMock()
    const setTileLoadFailed = vi.fn()
    const setTileFailedProvider = vi.fn()
    let now = 0

    const module = createBasemapModule({
      map,
      getTileConfig: (sourceId) =>
        sourceId === 'esri-street'
          ? {
              id: 'esri-street',
              label: 'Esri Street',
              provider: 'Esri',
              style: 'street',
              urlTemplate: 'https://example.com/{z}/{x}/{y}.png',
              saturation: 0,
              brightness: 0,
              contrast: 0,
              isStandard: true,
              needsBackendTransform: false,
              authMode: 'none',
            }
          : undefined,
      getCurrentTileSourceId: () => 'esri-street',
      setTileLoadFailed,
      setTileFailedProvider,
      setSourceTransitioning: vi.fn(),
      dependencies: {
        now: () => {
          now += 100
          return now
        },
      },
    })

    // 迟到失败指向其它底图：忽略，不进入失败态
    for (let index = 0; index < 16; index += 1) {
      module.handleMapErrorEvent({
        sourceId: 'tile-base',
        error: {
          status: 403,
          url: 'https://example.com/tiles/Gaode/1/2/3.png',
        },
      })
    }
    expect(setTileLoadFailed).not.toHaveBeenCalledWith(true)

    module.handleMapErrorEvent({
      sourceId: 'other-source',
      error: {
        status: 403,
        url: 'https://example.com/tiles/Esri/1/2/3.png',
      },
    })

    module.handleMapErrorEvent({
      sourceId: 'tile-base',
      error: {
        status: 500,
        url: 'https://example.com/tiles/Esri/1/2/3.png',
      },
    })

    // 当前底图连续失败：计入阈值
    for (let index = 0; index < 16; index += 1) {
      module.handleMapErrorEvent({
        sourceId: 'tile-base',
        error: {
          status: 403,
          url: 'https://example.com/tiles/Esri/1/2/3.png',
        },
      })
    }

    expect(setTileLoadFailed).toHaveBeenLastCalledWith(true)
    expect(setTileFailedProvider).toHaveBeenLastCalledWith('Esri')
  })

  it('adds annotation overlay when tile source provides overlayUrlTemplate', () => {
    const { map, layers, sources } = createMapMock()
    const module = createBasemapModule({
      map,
      getTileConfig: (sourceId) =>
        sourceId === 'tianditu-vec'
          ? {
              id: 'tianditu-vec',
              label: '天地图街道',
              provider: 'Tianditu',
              style: 'street',
              urlTemplate: '/unified-tiles/tianditu-vec/{z}/{x}/{y}',
              overlayUrlTemplate: '/unified-tiles/tianditu-cva/{z}/{x}/{y}',
              saturation: 0,
              brightness: 0,
              contrast: 0,
              isStandard: true,
              needsBackendTransform: false,
              authMode: 'api-key',
            }
          : undefined,
      getCurrentTileSourceId: () => 'tianditu-vec',
      setTileLoadFailed: vi.fn(),
      setTileFailedProvider: vi.fn(),
      setSourceTransitioning: vi.fn(),
    })

    module.switchTileSource('tianditu-vec')

    expect(sources.has('tile-base')).toBe(true)
    expect(sources.has('tile-base-overlay')).toBe(true)
    expect(layers.has('tile-base-raster')).toBe(true)
    expect(layers.has('tile-base-overlay-raster')).toBe(true)
    expect(sources.get('tile-base-overlay').tiles).toEqual([
      '/unified-tiles/tianditu-cva/{z}/{x}/{y}',
    ])
  })

  it('hides and clears basemap tiles when switching to blank (none)', () => {
    const { map, layers, sources } = createMapMock()
    const source = {
      type: 'raster',
      tiles: ['https://example.com/gaode/{z}/{x}/{y}.png'],
      setTiles: vi.fn(function (this: { tiles: string[] }, next: string[]) {
        this.tiles = next
      }),
    }
    sources.set('tile-base', source)
    layers.add('tile-base-raster')
    layers.add('tile-base-overlay-raster')
    sources.set('tile-base-overlay', {
      type: 'raster',
      tiles: ['https://example.com/cva/{z}/{x}/{y}.png'],
    })

    const module = createBasemapModule({
      map,
      getTileConfig: () => undefined,
      getCurrentTileSourceId: () => 'none',
      setTileLoadFailed: vi.fn(),
      setTileFailedProvider: vi.fn(),
      setSourceTransitioning: vi.fn(),
    })

    module.switchTileSource('none')

    expect(map.setLayoutProperty).toHaveBeenCalledWith('tile-base-raster', 'visibility', 'none')
    expect(map.setPaintProperty).toHaveBeenCalledWith('tile-base-raster', 'raster-opacity', 0)
    expect(source.setTiles).toHaveBeenCalledWith([])
    expect(map.triggerRepaint).toHaveBeenCalled()
    expect(map.setLayoutProperty).toHaveBeenCalledWith(
      'tile-base-overlay-raster',
      'visibility',
      'none',
    )
    // overlay 源在空白模式下卸掉
    expect(sources.has('tile-base-overlay')).toBe(false)
    expect(layers.has('tile-base-overlay-raster')).toBe(false)
  })
})
