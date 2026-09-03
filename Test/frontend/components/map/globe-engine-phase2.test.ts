import { describe, expect, it } from 'vitest'

import {
  boundsCenterAndHeight,
  resolveLayerExtentBounds,
} from '@/components/map/globe-engine/layer-extent'
import {
  heightMetersToZoom,
  setGlobeViewSnapshot,
  consumeGlobeViewSnapshot,
  getGlobeViewSnapshot,
  zoomToHeightMeters,
} from '@/components/map/globe-engine/view-bridge'
import { collectCesiumOverlayTileSpecs } from '@/components/map/globe-engine/cesium/overlay-tiles-adapter'
import type { ActiveLayerDisplay } from '@/stores/layers/types'

describe('layer-extent', () => {
  it('resolves imported bounds and pads tiny spans', () => {
    const bounds = resolveLayerExtentBounds({
      instanceId: 'a',
      importedBounds: [120, 30, 120.00001, 30.00001],
    })
    expect(bounds).not.toBeNull()
    expect(bounds![2] - bounds![0]).toBeGreaterThan(0.0001)
  })

  it('rejects invalid bounds', () => {
    expect(
      resolveLayerExtentBounds({
        instanceId: 'a',
        importedBounds: [1, 2, 3] as unknown as [number, number, number, number],
      }),
    ).toBeNull()
  })

  it('boundsCenterAndHeight returns finite height', () => {
    const c = boundsCenterAndHeight([100, 20, 110, 30])
    expect(c.lng).toBe(105)
    expect(c.lat).toBe(25)
    expect(c.heightMeters).toBeGreaterThan(1000)
  })
})

describe('view-bridge', () => {
  it('stores and consumes snapshot once', () => {
    setGlobeViewSnapshot({ lng: 1, lat: 2, heightMeters: 3e6, zoom: 4 })
    expect(getGlobeViewSnapshot()?.lng).toBe(1)
    expect(consumeGlobeViewSnapshot()?.zoom).toBe(4)
    expect(consumeGlobeViewSnapshot()).toBeNull()
  })

  it('zoom/height round-trip stays in band', () => {
    const h = zoomToHeightMeters(6, 30)
    const z = heightMetersToZoom(h, 30)
    expect(z).toBeGreaterThan(4)
    expect(z).toBeLessThan(8)
  })
})

describe('overlay-tiles-adapter', () => {
  const base = {
    instanceId: 'i1',
    catalogId: 'cat-1',
    name: 'L',
    category: 'data',
    accentColor: '#fff',
    order: 0,
    opacity: 0.8,
    visible: true,
    dataState: 'real' as const,
    isImported: false,
    isImportedRaster: true,
    isAdminBoundary: false,
    isWeather: false,
  }

  it('builds overlay-tiles URL for imported raster', () => {
    const layer = {
      ...base,
      importedRasterOverlayLayerId: 'ov-abc',
    } as ActiveLayerDisplay
    const specs = collectCesiumOverlayTileSpecs([layer], { timeKey: '2024-01-01T00:00:00Z' })
    expect(specs).toHaveLength(1)
    expect(specs[0].urlTemplate).toContain('/overlay-tiles/ov-abc/')
    expect(specs[0].urlTemplate).toContain('{z}')
    expect(specs[0].urlTemplate).toContain('time=')
    expect(specs[0].opacity).toBe(0.8)
  })

  it('skips weather engine layers', () => {
    const layer = {
      ...base,
      isImportedRaster: false,
      importedRasterOverlayLayerId: undefined,
      catalogId: 'wind-field',
      renderHint: { palette: 'wind' },
    } as ActiveLayerDisplay
    const specs = collectCesiumOverlayTileSpecs([layer], {
      isWeatherEngineLayer: (id) => id === 'wind-field',
    })
    expect(specs).toHaveLength(0)
  })

  it('skips hidden layers', () => {
    const layer = {
      ...base,
      visible: false,
      importedRasterOverlayLayerId: 'ov-x',
    } as ActiveLayerDisplay
    expect(collectCesiumOverlayTileSpecs([layer])).toHaveLength(0)
  })
})
