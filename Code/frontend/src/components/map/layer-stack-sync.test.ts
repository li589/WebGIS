import { describe, expect, it } from 'vitest'

import { applyActiveLayerStackOrder } from './layer-stack-sync'
import type { ActiveLayer } from '../../stores/layers/types'

describe('applyActiveLayerStackOrder', () => {
  it('moves higher-order content closer to admin-fill', () => {
    const present = new Set([
      'admin-fill',
      'admin-line',
      'overlay-raster-low',
      'overlay-raster-high',
      'imported-fill-a',
    ])
    const moved: Array<[string, string | undefined]> = []
    const map = {
      getLayer: (id: string) => (present.has(id) ? { id } : undefined),
      moveLayer: (id: string, beforeId?: string) => {
        moved.push([id, beforeId])
      },
    } as any

    const layers: ActiveLayer[] = [
      {
        instanceId: '1',
        catalogId: 'low',
        visible: true,
        opacity: 0.7,
        order: 0,
        isAdminBoundary: false,
        importedRaster: { overlayLayerId: 'low' },
        dataState: 'imported',
      },
      {
        instanceId: '2',
        catalogId: 'high',
        visible: true,
        opacity: 0.7,
        order: 1,
        isAdminBoundary: false,
        importedRaster: { overlayLayerId: 'high' },
        dataState: 'imported',
      },
      {
        instanceId: '3',
        catalogId: 'admin',
        visible: true,
        opacity: 1,
        order: 2,
        isAdminBoundary: true,
        dataState: 'catalog',
      },
    ]

    applyActiveLayerStackOrder(map, layers, {
      getImportedVectorLayerIds: () => [],
      getOverlayRasterLayerId: (id) => (id === 'low' ? 'overlay-raster-low' : id === 'high' ? 'overlay-raster-high' : null),
    })

    // high order first under admin, then low under high
    expect(moved[0]).toEqual(['overlay-raster-high', 'admin-fill'])
    expect(moved[1]).toEqual(['overlay-raster-low', 'overlay-raster-high'])
    // admin restacked on top
    expect(moved.some(([id]) => id === 'admin-fill')).toBe(true)
  })
})
