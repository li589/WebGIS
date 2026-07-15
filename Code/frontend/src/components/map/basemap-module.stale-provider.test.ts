import { describe, expect, it, vi } from 'vitest'

import { createBasemapModule } from './basemap-module'

describe('basemap-module stale provider errors', () => {
  it('ignores tile errors from a previous provider while switching', () => {
    const sources = new Map<string, any>()
    const map = {
      getSource: (id: string) => sources.get(id),
      addSource: vi.fn(),
      getLayer: () => ({ id: 'tile-base-raster' }),
      addLayer: vi.fn(),
      setLayoutProperty: vi.fn(),
      setPaintProperty: vi.fn(),
      triggerRepaint: vi.fn(),
    } as any

    const setTileLoadFailed = vi.fn()
    const setTileFailedProvider = vi.fn()
    let currentSourceId: 'esri-street' | 'esri-imagery' = 'esri-street'

    const configs = {
      'esri-street': {
        id: 'esri-street' as const,
        label: 'Street',
        provider: 'Esri',
        style: 'street' as const,
        urlTemplate: '/unified-tiles/esri-street/{z}/{x}/{y}',
        saturation: 0,
        brightness: 0,
        contrast: 0,
        isStandard: true,
        needsBackendTransform: false,
        authMode: 'none' as const,
      },
      'esri-imagery': {
        id: 'esri-imagery' as const,
        label: 'Imagery',
        provider: 'Esri Imagery',
        style: 'satellite' as const,
        urlTemplate: '/unified-tiles/esri-imagery/{z}/{x}/{y}',
        saturation: 0,
        brightness: 0,
        contrast: 0,
        isStandard: true,
        needsBackendTransform: false,
        authMode: 'none' as const,
      },
    }

    const module = createBasemapModule({
      map,
      getTileConfig: (id) => configs[id as keyof typeof configs],
      getCurrentTileSourceId: () => currentSourceId,
      setTileLoadFailed,
      setTileFailedProvider,
      setSourceTransitioning: vi.fn(),
    })

    currentSourceId = 'esri-imagery'
    for (let i = 0; i < 20; i += 1) {
      module.handleTileError('esri-street')
    }

    expect(setTileLoadFailed).not.toHaveBeenCalledWith(true)
  })

  it('ignores unattributed (null provider) tile errors', () => {
    const map = {
      getSource: () => undefined,
      addSource: vi.fn(),
      getLayer: () => ({ id: 'tile-base-raster' }),
      addLayer: vi.fn(),
      setLayoutProperty: vi.fn(),
      setPaintProperty: vi.fn(),
      triggerRepaint: vi.fn(),
    } as any
    const setTileLoadFailed = vi.fn()

    const module = createBasemapModule({
      map,
      getTileConfig: () => ({
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
      }),
      getCurrentTileSourceId: () => 'esri-street',
      setTileLoadFailed,
      setTileFailedProvider: vi.fn(),
      setSourceTransitioning: vi.fn(),
    })

    for (let i = 0; i < 20; i += 1) {
      module.handleTileError(null)
    }

    expect(setTileLoadFailed).not.toHaveBeenCalledWith(true)
  })
})
