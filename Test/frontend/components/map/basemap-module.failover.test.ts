import { describe, expect, it, vi } from 'vitest'

import { createBasemapModule } from '@/components/map/basemap-module'
import type { TileSourceId } from '@/services/api-config'

interface TestHarness {
  module: ReturnType<typeof createBasemapModule>
  flushTimers: () => void
  scheduled: Map<number, () => void>
  sources: Map<string, any>
  map: any
}

function createHarness(config: {
  currentSourceId?: TileSourceId
  candidates?: TileSourceId[]
  onProviderFailover?: (next: TileSourceId, failed: string) => void
  candidateSpy?: (currentSourceId: TileSourceId, excludeProviders: ReadonlySet<string>) => TileSourceId[]
}): TestHarness {
  const sources = new Map<string, any>()
  const layerOrder: string[] = []
  const layerSpecs = new Map<string, any>()
  const scheduled = new Map<number, () => void>()
  let timerId = 0
  let now = 0
  let currentSourceId: TileSourceId = config.currentSourceId ?? 'esri-street'

  const tileConfig = (id: string) =>
    ({
      'esri-street': {
        id: 'esri-street',
        label: 'Esri Street',
        provider: 'Esri',
        style: 'street',
        urlTemplate: 'https://esri.example/{z}/{x}/{y}.png',
      },
      'bing-road': {
        id: 'bing-road',
        label: 'Bing Road',
        provider: 'Bing',
        style: 'street',
        urlTemplate: 'https://bing.example/{z}/{x}/{y}.png',
      },
      'gaode-street': {
        id: 'gaode-street',
        label: '高德街道',
        provider: '高德',
        style: 'street',
        urlTemplate: 'https://gaode.example/{z}/{x}/{y}.png',
      },
    } as Record<string, any>)[id]

  const map = {
    getSource: (id: string) => sources.get(id),
    addSource: (id: string, source: any) => {
      sources.set(id, source)
    },
    removeSource: (id: string) => {
      sources.delete(id)
    },
    getStyle: () => ({ layers: layerOrder.map((id) => layerSpecs.get(id) ?? { id, type: 'other' }) }),
    getLayer: (id: string) => (layerOrder.includes(id) ? { id } : undefined),
    addLayer: (layer: { id: string; type?: string }, beforeId?: string) => {
      layerSpecs.set(layer.id, layer)
      const idx = beforeId ? layerOrder.indexOf(beforeId) : -1
      if (idx >= 0) layerOrder.splice(idx, 0, layer.id)
      else layerOrder.push(layer.id)
    },
    moveLayer: vi.fn(),
    removeLayer: (id: string) => {
      const idx = layerOrder.indexOf(id)
      if (idx >= 0) layerOrder.splice(idx, 1)
    },
    setLayoutProperty: vi.fn(),
    setPaintProperty: vi.fn(),
    triggerRepaint: vi.fn(),
  } as any

  sources.set('tile-base', {
    type: 'raster',
    setTiles: vi.fn(),
  })
  layerOrder.push('tile-base-raster')
  layerSpecs.set('tile-base-raster', { id: 'tile-base-raster', type: 'raster' })

  const module = createBasemapModule({
    map,
    getTileConfig: (sourceId) => tileConfig(sourceId),
    getCurrentTileSourceId: () => currentSourceId,
    setTileLoadFailed: vi.fn(),
    setTileFailedProvider: vi.fn(),
    setSourceTransitioning: vi.fn(),
    onProviderFailover:
      config.onProviderFailover ??
      ((next) => {
        // 模拟真实接线：store 同步更新当前源
        currentSourceId = next
      }),
    getFailoverCandidates: config.candidateSpy ?? (() => config.candidates ?? ['bing-road']),
    dependencies: {
      setTimeout: ((callback: () => void) => {
        timerId += 1
        scheduled.set(timerId, callback)
        return timerId as unknown as ReturnType<typeof setTimeout>
      }) as typeof setTimeout,
      clearTimeout: ((id: ReturnType<typeof setTimeout>) => {
        scheduled.delete(id as unknown as number)
      }) as typeof clearTimeout,
      now: () => {
        now += 100
        return now
      },
    },
  })

  return {
    module,
    scheduled,
    sources,
    map,
    flushTimers: () => {
      for (const callback of [...scheduled.values()]) callback()
      scheduled.clear()
    },
  }
}

describe('basemap-module provider failover', () => {
  it('switches to a same-style candidate on circuit break and notifies the caller', () => {
    const onProviderFailover = vi.fn((next: TileSourceId) => {
      expect(next).toBe('bing-road')
    })
    const harness = createHarness({ onProviderFailover })

    for (let index = 0; index < 9; index += 1) {
      harness.module.handleTileError('Esri')
    }

    expect(onProviderFailover).toHaveBeenCalledTimes(1)
    expect(onProviderFailover).toHaveBeenCalledWith('bing-road', 'Esri')

    harness.flushTimers()

    const baseSource = harness.sources.get('tile-base')
    expect(baseSource.setTiles).toHaveBeenCalledWith(['https://bing.example/{z}/{x}/{y}.png'])
  })

  it('does not flip into the broken-banner state when a failover candidate exists', () => {
    const setTileLoadFailed = vi.fn()
    const harness = createHarness({})

    const module = createBasemapModule({
      map: harness.map,
      getTileConfig: () => undefined,
      getCurrentTileSourceId: () => 'esri-street',
      setTileLoadFailed,
      setTileFailedProvider: vi.fn(),
      setSourceTransitioning: vi.fn(),
      onProviderFailover: () => {},
      getFailoverCandidates: () => ['bing-road'],
      dependencies: { now: () => 1000 },
    })

    for (let index = 0; index < 9; index += 1) {
      module.handleTileError('Esri')
    }

    expect(setTileLoadFailed).not.toHaveBeenCalledWith(true)
  })

  it('excludes cooled-down providers from subsequent failover candidate sets', () => {
    const seenExcludeSets: Array<ReadonlySet<string>> = []
    let currentSourceId: TileSourceId = 'esri-street'
    const candidatesByRound: TileSourceId[][] = [['bing-road'], []]
    let round = 0

    const module = createBasemapModule({
      map: {
        getSource: () => ({ type: 'raster', setTiles: vi.fn() }),
        getLayer: () => ({ id: 'tile-base-raster' }),
        getStyle: () => ({ layers: [{ id: 'bg', type: 'background' }] }),
        addLayer: vi.fn(),
        moveLayer: vi.fn(),
        removeLayer: vi.fn(),
        setLayoutProperty: vi.fn(),
        setPaintProperty: vi.fn(),
        triggerRepaint: vi.fn(),
      } as any,
      getTileConfig: (id) =>
        id === 'esri-street'
          ? { id: 'esri-street', provider: 'Esri', style: 'street', urlTemplate: 'u' }
          : id === 'bing-road'
            ? { id: 'bing-road', provider: 'Bing', style: 'street', urlTemplate: 'u2' }
            : undefined,
      getCurrentTileSourceId: () => currentSourceId,
      setTileLoadFailed: vi.fn(),
      setTileFailedProvider: vi.fn(),
      setSourceTransitioning: vi.fn(),
      onProviderFailover: (next) => {
        currentSourceId = next
      },
      getFailoverCandidates: (_id, excludeProviders) => {
        seenExcludeSets.push(new Set(excludeProviders))
        return candidatesByRound[Math.min(round, candidatesByRound.length - 1)]
      },
      dependencies: { now: () => 1000 },
    })

    // 第一轮：Esri 熔断 → 转移到 bing-road
    for (let index = 0; index < 9; index += 1) module.handleTileError('Esri')
    expect(seenExcludeSets[0].has('Esri')).toBe(true)
    round += 1

    // 第二轮：Bing 也熔断 → Esri 已在冷却，被排除
    for (let index = 0; index < 9; index += 1) module.handleTileError('Bing')
    expect(seenExcludeSets[1].has('Esri')).toBe(true)
    expect(seenExcludeSets[1].has('Bing')).toBe(true)
  })

  it('falls back to the broken + auto-recovery path when no candidate is available', () => {
    const setTileLoadFailed = vi.fn()
    const setTileFailedProvider = vi.fn()
    const scheduled = new Map<number, () => void>()
    let timerId = 0

    const module = createBasemapModule({
      map: {
        getSource: (id: string) =>
          id === 'tile-base' ? { type: 'raster', setTiles: vi.fn() } : undefined,
        getLayer: (id: string) => (id === 'tile-base-raster' ? { id } : undefined),
        getStyle: () => ({ layers: [{ id: 'bg', type: 'background' }] }),
        addLayer: vi.fn(),
        moveLayer: vi.fn(),
        removeLayer: vi.fn(),
        removeSource: vi.fn(),
        setLayoutProperty: vi.fn(),
        setPaintProperty: vi.fn(),
        triggerRepaint: vi.fn(),
      } as any,
      getTileConfig: () => ({
        id: 'esri-street',
        provider: 'Esri',
        style: 'street',
        urlTemplate: 'https://esri.example/{z}/{x}/{y}.png',
      }),
      getCurrentTileSourceId: () => 'esri-street',
      setTileLoadFailed,
      setTileFailedProvider,
      setSourceTransitioning: vi.fn(),
      onProviderFailover: vi.fn(),
      getFailoverCandidates: () => [],
      dependencies: {
        setTimeout: ((callback: () => void) => {
          timerId += 1
          scheduled.set(timerId, callback)
          return timerId as unknown as ReturnType<typeof setTimeout>
        }) as typeof setTimeout,
        clearTimeout: ((id: ReturnType<typeof setTimeout>) => {
          scheduled.delete(id as unknown as number)
        }) as typeof clearTimeout,
        now: () => 1000,
      },
    })

    for (let index = 0; index < 9; index += 1) module.handleTileError('Esri')

    expect(setTileLoadFailed).toHaveBeenCalledWith(true)
    expect(setTileFailedProvider).toHaveBeenCalledWith('Esri')

    scheduled.get(timerId)?.()
    expect(setTileLoadFailed).toHaveBeenLastCalledWith(false)
    expect(setTileFailedProvider).toHaveBeenLastCalledWith(null)
  })

  it('does not re-trigger failover while a switch is still debouncing', () => {
    const onProviderFailover = vi.fn()
    const harness = createHarness({ onProviderFailover })

    // 第一批触发转移
    for (let index = 0; index < 9; index += 1) harness.module.handleTileError('Esri')
    expect(onProviderFailover).toHaveBeenCalledTimes(1)

    // 防抖执行前错误继续涌入：不重复回调
    for (let index = 0; index < 9; index += 1) harness.module.handleTileError('Esri')
    expect(onProviderFailover).toHaveBeenCalledTimes(1)

    harness.flushTimers()
    const baseSource = harness.sources.get('tile-base')
    expect(baseSource.setTiles).toHaveBeenCalledWith(['https://bing.example/{z}/{x}/{y}.png'])
  })
})
