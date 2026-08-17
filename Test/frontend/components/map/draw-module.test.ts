import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/components/map/draw-canvas', () => ({
  DrawCanvas: class {
    updateState = vi.fn()
    show = vi.fn()
    hide = vi.fn()
    dispose = vi.fn()
  },
}))

import { createDrawModule } from '@/components/map/draw-module'
import type { DrawStateSnapshot } from '@/components/map/draw-module'
import type { InteractionMode } from '@/stores/ui'

interface MapMock {
  map: Record<string, unknown>
  sourceData: Map<string, unknown>
  layers: string[]
  handlers: Map<string, Array<(ev: unknown) => void>>
  removedLayers: string[]
  removedSources: string[]
}

function makeMapMock(): MapMock {
  const sourceData = new Map<string, unknown>()
  const sources = new Map<string, { setData: (fc: unknown) => void }>()
  const layers: string[] = []
  const handlers = new Map<string, Array<(ev: unknown) => void>>()
  const removedLayers: string[] = []
  const removedSources: string[] = []
  const map = {
    loaded: () => true,
    getSource: (id: string) => sources.get(id),
    addSource: (id: string) => {
      sources.set(id, { setData: (fc: unknown) => sourceData.set(id, fc) })
    },
    getLayer: (id: string) => (layers.includes(id) ? { id } : undefined),
    addLayer: (layer: { id: string }) => {
      layers.push(layer.id)
    },
    removeLayer: (id: string) => {
      removedLayers.push(id)
    },
    removeSource: (id: string) => {
      removedSources.push(id)
    },
    project: (p: [number, number]) => ({ x: p[0] * 1000, y: p[1] * 1000 }),
    on: (event: string, handler: (ev: unknown) => void) => {
      const list = handlers.get(event) ?? []
      list.push(handler)
      handlers.set(event, list)
    },
    off: vi.fn(),
    once: vi.fn(),
    doubleClickZoom: { disable: vi.fn(), enable: vi.fn() },
    boxZoom: { disable: vi.fn(), enable: vi.fn() },
    getContainer: () => ({ appendChild: vi.fn(), getBoundingClientRect: () => ({ width: 0, height: 0 }) }),
  }
  return { map, sourceData, layers, handlers, removedLayers, removedSources }
}

function makeState(overrides: Partial<DrawStateSnapshot> = {}): DrawStateSnapshot {
  return {
    drawMode: 'polygon',
    features: [],
    activeVertices: [],
    isDrawing: false,
    hoverPoint: null,
    selectedFeatureIndex: null,
    ...overrides,
  }
}

function makeOptions(state: DrawStateSnapshot, mapMock: MapMock) {
  return {
    map: mapMock.map,
    getInteractionMode: (): InteractionMode => 'draw',
    getDrawState: () => state,
    addVertex: vi.fn((v: { lng: number; lat: number }) => {
      state.activeVertices.push(v)
      state.isDrawing = true
    }),
    undoLastVertex: vi.fn(() => {
      state.activeVertices.pop()
      if (state.activeVertices.length === 0) state.isDrawing = false
    }),
    setHoverPoint: vi.fn((p: { lng: number; lat: number } | null) => {
      state.hoverPoint = p
    }),
    addFeature: vi.fn((f: unknown) => {
      state.features.push(f as DrawStateSnapshot['features'][number])
    }),
    clearActiveVertices: vi.fn(() => {
      state.activeVertices = []
      state.isDrawing = false
      state.hoverPoint = null
    }),
    setDrawingFlag: vi.fn((v: boolean) => {
      state.isDrawing = v
    }),
    scheduleDraftPersist: vi.fn(),
  }
}

function fire(mapMock: MapMock, event: string, ev: unknown): void {
  for (const handler of mapMock.handlers.get(event) ?? []) handler(ev)
}

describe('draw-module', () => {
  let mapMock: MapMock

  beforeEach(() => {
    mapMock = makeMapMock()
  })

  it('registers preview path (solid) and cursor (dashed) layers on bind', () => {
    const state = makeState()
    const module = createDrawModule(makeOptions(state, mapMock))
    module.bindEvents()
    module.applyDrawMode()

    expect(mapMock.layers).toContain('draw-preview-path-layer')
    expect(mapMock.layers).toContain('draw-preview-layer')
    expect(mapMock.layers).toContain('draw-features-fill-layer')
    expect(mapMock.layers).toContain('draw-features-line-layer')
    expect(mapMock.layers).toContain('draw-vertices-layer')
    module.dispose()
  })

  it('renders placed path segment and cursor segment while drawing a polygon', () => {
    const state = makeState({
      isDrawing: true,
      activeVertices: [
        { lng: 116.1, lat: 39.9 },
        { lng: 116.2, lat: 39.95 },
      ],
      hoverPoint: { lng: 116.3, lat: 39.99 },
    })
    const module = createDrawModule(makeOptions(state, mapMock))
    module.bindEvents()
    module.applyDrawMode()
    module.syncFromStore()

    const preview = mapMock.sourceData.get('draw-preview') as {
      features: Array<{ properties: { kind: string }; geometry: { coordinates: number[][] } }>
    }
    const kinds = preview.features.map((f) => f.properties.kind).sort()
    expect(kinds).toEqual(['cursor', 'path'])

    const path = preview.features.find((f) => f.properties.kind === 'path')!
    expect(path.geometry.coordinates).toEqual([
      [116.1, 39.9],
      [116.2, 39.95],
    ])

    const cursor = preview.features.find((f) => f.properties.kind === 'cursor')!
    expect(cursor.geometry.coordinates).toEqual([
      [116.2, 39.95],
      [116.3, 39.99],
    ])
    module.dispose()
  })

  it('snaps the cursor segment to the first vertex when hovering near it', () => {
    const state = makeState({
      isDrawing: true,
      activeVertices: [
        { lng: 116.1, lat: 39.9 },
        { lng: 116.2, lat: 39.95 },
      ],
      // 投影后距首顶点 ~20px 以内：116.102 => 2 * 1000 = 20px
      hoverPoint: { lng: 116.102, lat: 39.9 },
    })
    const module = createDrawModule(makeOptions(state, mapMock))
    module.bindEvents()
    module.applyDrawMode()
    module.syncFromStore()

    const preview = mapMock.sourceData.get('draw-preview') as {
      features: Array<{ properties: { kind: string }; geometry: { coordinates: number[][] } }>
    }
    const cursor = preview.features.find((f) => f.properties.kind === 'cursor')!
    expect(cursor.geometry.coordinates).toEqual([
      [116.2, 39.95],
      [116.1, 39.9],
    ])
    module.dispose()
  })

  it('produces no preview features before the first vertex is placed', () => {
    const state = makeState({ hoverPoint: { lng: 116.1, lat: 39.9 } })
    const module = createDrawModule(makeOptions(state, mapMock))
    module.bindEvents()
    module.applyDrawMode()
    module.syncFromStore()

    const preview = mapMock.sourceData.get('draw-preview') as {
      features: unknown[]
    }
    expect(preview.features).toHaveLength(0)
    module.dispose()
  })

  it('previews the full rectangle frame during drag and commits on mouseup', () => {
    const state = makeState({ drawMode: 'rectangle' })
    const options = makeOptions(state, mapMock)
    const module = createDrawModule(options)
    module.bindEvents()
    module.applyDrawMode()

    fire(mapMock, 'mousedown', { lngLat: { lng: 116.0, lat: 39.9 } })
    fire(mapMock, 'mousemove', { lngLat: { lng: 116.2, lat: 40.0 } })
    module.syncFromStore()

    const preview = mapMock.sourceData.get('draw-preview') as {
      features: Array<{ properties: { kind: string }; geometry: { coordinates: number[][] } }>
    }
    expect(preview.features).toHaveLength(1)
    expect(preview.features[0]!.properties.kind).toBe('cursor')
    expect(preview.features[0]!.geometry.coordinates).toEqual([
      [116.0, 39.9],
      [116.2, 39.9],
      [116.2, 40.0],
      [116.0, 40.0],
      [116.0, 39.9],
    ])

    fire(mapMock, 'mouseup', { lngLat: { lng: 116.2, lat: 40.0 } })
    expect(options.addFeature).toHaveBeenCalledTimes(1)
    expect(options.scheduleDraftPersist).toHaveBeenCalled()
    module.dispose()
  })

  it('clears rendered features from map sources when the store is emptied', () => {
    const feature = {
      geometry: {
        type: 'Polygon' as const,
        coordinates: [
          [
            [116.0, 39.9],
            [116.2, 39.9],
            [116.2, 40.0],
            [116.0, 39.9],
          ],
        ],
      },
      properties: {},
    }
    const state = makeState({ features: [feature] })
    const module = createDrawModule(makeOptions(state, mapMock))
    module.bindEvents()
    module.applyDrawMode()
    module.syncFromStore()

    let fill = mapMock.sourceData.get('draw-features-fill') as { features: unknown[] }
    expect(fill.features).toHaveLength(1)

    // 模拟移除图层后的 clearDraft / clearAll
    state.features = []
    module.syncFromStore()

    fill = mapMock.sourceData.get('draw-features-fill') as { features: unknown[] }
    expect(fill.features).toHaveLength(0)
    module.dispose()
  })

  it('removes its layers and sources on dispose', () => {
    const state = makeState()
    const module = createDrawModule(makeOptions(state, mapMock))
    module.bindEvents()
    module.applyDrawMode()
    module.dispose()

    expect(mapMock.removedLayers).toContain('draw-preview-path-layer')
    expect(mapMock.removedLayers).toContain('draw-features-fill-layer')
    expect(mapMock.removedSources).toContain('draw-preview')
    expect(mapMock.removedSources).toContain('draw-features-fill')
  })
})
