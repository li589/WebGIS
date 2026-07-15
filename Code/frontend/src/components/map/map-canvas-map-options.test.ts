import { describe, expect, it } from 'vitest'

import { createMapCanvasMapOptions } from './map-canvas-map-options'

describe('map-canvas-map-options', () => {
  it('builds stable maplibre options for the map canvas stage', () => {
    const container = {} as HTMLElement

    expect(createMapCanvasMapOptions({ container })).toMatchObject({
      container,
      center: [113.2644, 23.1291],
      zoom: 4.8,
      pitch: 0,
      bearing: 0,
      attributionControl: false,
      renderWorldCopies: true,
      cancelPendingTileRequestsWhileZooming: true,
      refreshExpiredTiles: false,
      canvasContextAttributes: {
        preserveDrawingBuffer: false,
      },
      style: {
        version: 8,
        sources: {},
        layers: [{ id: 'background', type: 'background' }],
      },
    })
  })
})
