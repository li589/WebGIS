import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('maplibre-gl', () => ({
  Popup: class {
    setLngLat() {
      return this
    }
    setHTML() {
      return this
    }
    addTo() {
      return this
    }
  },
}))

import { createImportedLayerModule } from '@/components/map/imported-layer-module'

interface LayerSpec {
  id: string
  type: string
  source: string
  paint?: Record<string, unknown>
}

interface MapMock {
  map: Record<string, unknown>
  layers: LayerSpec[]
  sources: Map<string, { setData: (fc: unknown) => void }>
  setDataCalls: Array<{ sourceId: string; fc: unknown }>
  onCalls: number
}

function makeMapMock(opts: { failOnLayerId?: string } = {}): MapMock {
  const layers: LayerSpec[] = []
  const sources = new Map<string, { setData: (fc: unknown) => void }>()
  const setDataCalls: Array<{ sourceId: string; fc: unknown }> = []
  let onCalls = 0
  const map = {
    getLayer: (id: string) => layers.find((l) => l.id === id),
    addLayer: (layer: LayerSpec) => {
      if (opts.failOnLayerId && layer.id === opts.failOnLayerId) {
        throw new Error(`mock addLayer failure: ${layer.id}`)
      }
      layers.push(layer)
    },
    removeLayer: (id: string) => {
      const idx = layers.findIndex((l) => l.id === id)
      if (idx >= 0) layers.splice(idx, 1)
    },
    getSource: (id: string) => sources.get(id),
    addSource: (id: string) => {
      sources.set(id, {
        setData: (fc: unknown) => setDataCalls.push({ sourceId: id, fc }),
      })
    },
    removeSource: (id: string) => {
      sources.delete(id)
    },
    on: () => {
      onCalls += 1
    },
    off: vi.fn(),
    getCanvas: () => ({ style: {} }),
    fitBounds: vi.fn(),
  }
  return { map, layers, sources, setDataCalls, onCalls }
}

function polygonFc(): GeoJSON.FeatureCollection {
  return {
    type: 'FeatureCollection',
    features: [
      {
        type: 'Feature',
        geometry: {
          type: 'Polygon',
          coordinates: [
            [
              [116.0, 39.0],
              [117.0, 39.0],
              [117.0, 40.0],
              [116.0, 40.0],
              [116.0, 39.0],
            ],
          ],
        },
        properties: { name: 'p1' },
      },
    ],
  }
}

describe('imported-layer-module', () => {
  let mock: MapMock
  let mapReady: { value: boolean }

  beforeEach(() => {
    mock = makeMapMock()
    mapReady = { value: true }
  })

  function makeModule() {
    return createImportedLayerModule({
      map: mock.map as never,
      getMapReady: () => mapReady.value,
    })
  }

  it('多边形数据创建 fill/line/circle 渲染层，paint 颜色为字面量（非 var()）', () => {
    const mod = makeModule()
    const ok = mod.addVectorLayer('inst-1', polygonFc(), '测试面')
    expect(ok).toBe(true)
    const ids = mock.layers.map((l) => l.id)
    expect(ids).toContain('imported-fill-inst-1')
    expect(ids).toContain('imported-line-inst-1')
    expect(ids).toContain('imported-circle-inst-1')
    expect(ids).not.toContain('imported-label-inst-1')
    const fill = mock.layers.find((l) => l.id === 'imported-fill-inst-1')!
    expect(fill.paint?.['fill-color']).not.toMatch(/var\(/)
    expect(String(fill.paint?.['fill-color'])).toMatch(/^#/)
  })

  it('空 FeatureCollection 也注册 source 与渲染层（修复侧栏有条目但地图无渲染）', () => {
    const mod = makeModule()
    const empty: GeoJSON.FeatureCollection = { type: 'FeatureCollection', features: [] }
    const ok = mod.addVectorLayer('inst-2', empty, '空层')
    expect(ok).toBe(true)
    expect(mock.sources.has('imported-src-inst-2')).toBe(true)
    expect(mock.layers.map((l) => l.id)).toContain('imported-fill-inst-2')
    expect(mod.getLoadedIds()).toContain('inst-2')
  })

  it('已加载图层传入新 geojson 引用时仅 setData，不重复 addSource', () => {
    const mod = makeModule()
    mod.addVectorLayer('inst-3', polygonFc(), 'A')
    expect(mock.sources.size).toBe(1)
    const fc2 = polygonFc()
    const ok = mod.addVectorLayer('inst-3', fc2, 'A')
    expect(ok).toBe(true)
    expect(mock.sources.size).toBe(1)
    expect(mock.setDataCalls).toHaveLength(1)
    expect(mock.setDataCalls[0]!.sourceId).toBe('imported-src-inst-3')
    // 同一引用再次调用不再 setData
    mod.addVectorLayer('inst-3', fc2, 'A')
    expect(mock.setDataCalls).toHaveLength(1)
  })

  it('map 未就绪时返回 false 且不产生副作用', () => {
    mapReady.value = false
    const mod = makeModule()
    const ok = mod.addVectorLayer('inst-4', polygonFc(), 'B')
    expect(ok).toBe(false)
    expect(mock.sources.size).toBe(0)
    expect(mock.layers).toHaveLength(0)
  })

  it('addLayer 抛错时清理半成品并返回 false（可重试）', () => {
    mock = makeMapMock({ failOnLayerId: 'imported-line-inst-5' })
    const mod = makeModule()
    const ok = mod.addVectorLayer('inst-5', polygonFc(), 'C')
    expect(ok).toBe(false)
    expect(mock.sources.size).toBe(0)
    expect(mock.layers.map((l) => l.id)).not.toContain('imported-fill-inst-5')
    expect(mod.getLoadedIds()).not.toContain('inst-5')
  })

  it('removeLayer 移除 source 与全部渲染层', () => {
    const mod = makeModule()
    mod.addVectorLayer('inst-6', polygonFc(), 'D')
    mod.removeLayer('inst-6')
    expect(mock.sources.size).toBe(0)
    expect(mock.layers).toHaveLength(0)
    expect(mod.getLoadedIds()).toHaveLength(0)
  })
})
