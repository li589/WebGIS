import { describe, expect, it, vi } from 'vitest'

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

import {
  IMPORTED_VECTOR_STYLE_DEFAULTS,
  buildImportedVectorPayload,
  resolveImportedVectorDefaultColor,
} from '@/stores/layers/imported-vector'
import { createImportedLayerModule } from '@/components/map/imported-layer-module'

const mixedFc: GeoJSON.FeatureCollection = {
  type: 'FeatureCollection',
  features: [
    {
      type: 'Feature',
      properties: null,
      geometry: { type: 'Point', coordinates: [116, 39] },
    },
    {
      type: 'Feature',
      properties: null,
      geometry: {
        type: 'Polygon',
        coordinates: [
          [
            [116.0, 39.0],
            [116.5, 39.0],
            [116.5, 39.5],
            [116.0, 39.5],
            [116.0, 39.0],
          ],
        ],
      },
    },
  ],
}

describe('导入矢量默认样式单一真源（面板初值 === 地图渲染）', () => {
  it('常量与地图渲染基准一致（width 2 / radius 4 / fillOpacity 0.25）', () => {
    expect(IMPORTED_VECTOR_STYLE_DEFAULTS.width).toBe(2)
    expect(IMPORTED_VECTOR_STYLE_DEFAULTS.radius).toBe(4)
    expect(IMPORTED_VECTOR_STYLE_DEFAULTS.fillOpacity).toBe(0.25)
    expect(IMPORTED_VECTOR_STYLE_DEFAULTS.color).toMatch(/^#[0-9a-f]{6}$/i)
  })

  it('buildImportedVectorPayload 创建图层即写实默认样式（不再留空）', () => {
    const payload = buildImportedVectorPayload(mixedFc, 'a.geojson')
    expect(payload.style).toBeDefined()
    expect(payload.style?.width).toBe(IMPORTED_VECTOR_STYLE_DEFAULTS.width)
    expect(payload.style?.radius).toBe(IMPORTED_VECTOR_STYLE_DEFAULTS.radius)
    expect(payload.style?.fillOpacity).toBe(IMPORTED_VECTOR_STYLE_DEFAULTS.fillOpacity)
    expect(payload.style?.color).toBe(resolveImportedVectorDefaultColor())
  })

  it('地图初始 paint 兜底值读同一常量（滑条初值与地图一致，拖动无跳变）', () => {
    const layers: Array<{ id: string; type: string; paint?: Record<string, unknown> }> = []
    const map = {
      getLayer: (id: string) => layers.find((l) => l.id === id),
      addLayer: (l: { id: string }) => layers.push(l as never),
      removeLayer: (id: string) => {
        const i = layers.findIndex((l) => l.id === id)
        if (i >= 0) layers.splice(i, 1)
      },
      getSource: () => undefined,
      addSource: () => {},
      removeSource: () => {},
      on: () => {},
      off: () => {},
      getCanvas: () => ({ style: {} }),
      fitBounds: () => {},
      setPaintProperty: (id: string, prop: string, value: unknown) => {
        const l = layers.find((x) => x.id === id)
        if (l) l.paint = { ...l.paint, [prop]: value }
      },
    }
    const mod = createImportedLayerModule({ map: map as never, getMapReady: () => true })
    expect(mod.addVectorLayer('inst-d1', mixedFc, '一致性问题')).toBe(true)
    const fill = layers.find((l) => l.type === 'fill')
    const line = layers.find((l) => l.type === 'line')
    const circle = layers.find((l) => l.type === 'circle')
    expect(fill?.paint?.['fill-opacity']).toBe(IMPORTED_VECTOR_STYLE_DEFAULTS.fillOpacity)
    expect(line?.paint?.['line-width']).toBe(IMPORTED_VECTOR_STYLE_DEFAULTS.width)
    expect(circle?.paint?.['circle-radius']).toBe(IMPORTED_VECTOR_STYLE_DEFAULTS.radius)

    // style 缺省时 applyLayerStyle 也回落到同一常量
    mod.applyLayerStyle('inst-d1', {}, 1)
    expect(fill?.paint?.['fill-opacity']).toBe(IMPORTED_VECTOR_STYLE_DEFAULTS.fillOpacity)
    expect(line?.paint?.['line-width']).toBe(IMPORTED_VECTOR_STYLE_DEFAULTS.width)
    expect(circle?.paint?.['circle-radius']).toBe(IMPORTED_VECTOR_STYLE_DEFAULTS.radius)
  })
})
