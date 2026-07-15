import type { ImportedGeometryType } from '../../stores/import'
import { Popup } from 'maplibre-gl'

type MapInstance = import('maplibre-gl').Map

export interface ImportedLayerStyle {
  color?: string
  width?: number
  radius?: number
  fillOpacity?: number
}

interface CreateImportedLayerModuleOptions {
  map: MapInstance
  getMapReady: () => boolean
}

interface LoadedImportedLayer {
  id: string
  sourceId: string
  layerIds: string[]
  geometryType: ImportedGeometryType
  /** 注册的事件监听器引用，用于 removeLayer 时精确移除 */
  eventHandlers: Array<{ type: string; layerId: string; handler: (...args: any[]) => void }>
}

const DEFAULT_POINT_COLOR = '#5ad5ff'
const DEFAULT_LINE_COLOR = '#5ad5ff'
const DEFAULT_FILL_COLOR = '#5ad5ff'

function _safeId(id: string): string {
  return id.replace(/[^a-zA-Z0-9_-]/g, '-')
}

function _hasGeometryType(fc: GeoJSON.FeatureCollection, types: string[]): boolean {
  return fc.features.some((f) => f.geometry && types.includes(f.geometry.type))
}

export function createImportedLayerModule(options: CreateImportedLayerModuleOptions) {
  const loaded = new Map<string, LoadedImportedLayer>()

  function _ensureMap() {
    if (!options.getMapReady()) return false
    return true
  }

  function addVectorLayer(id: string, geojson: GeoJSON.FeatureCollection, name: string): void {
    if (!_ensureMap()) return
    if (loaded.has(id)) return

    const safe = _safeId(id)
    const sourceId = `imported-src-${safe}`
    const layerIds: string[] = []

    // 如果 GeoJSON 为空，跳过
    if (!geojson.features || geojson.features.length === 0) return

    options.map.addSource(sourceId, {
      type: 'geojson',
      data: geojson,
    } as any)

    // 根据几何类型添加对应的渲染图层
    // 面图层（Polygon / MultiPolygon）
    if (_hasGeometryType(geojson, ['Polygon', 'MultiPolygon'])) {
      const fillId = `imported-fill-${safe}`
      options.map.addLayer({
        id: fillId,
        type: 'fill',
        source: sourceId,
        filter: ['==', '$type', 'Polygon'],
        paint: {
          'fill-color': DEFAULT_FILL_COLOR,
          'fill-opacity': 0.25,
        },
        layout: { visibility: 'visible' },
      })
      layerIds.push(fillId)
    }

    // 线图层（LineString / MultiLineString + Polygon 边线）
    if (_hasGeometryType(geojson, ['LineString', 'MultiLineString', 'Polygon', 'MultiPolygon'])) {
      const lineId = `imported-line-${safe}`
      options.map.addLayer({
        id: lineId,
        type: 'line',
        source: sourceId,
        paint: {
          'line-color': DEFAULT_LINE_COLOR,
          'line-width': 2,
          'line-opacity': 0.9,
        },
        layout: { visibility: 'visible' },
      })
      layerIds.push(lineId)
    }

    // 点图层（Point / MultiPoint）
    if (_hasGeometryType(geojson, ['Point', 'MultiPoint'])) {
      const circleId = `imported-circle-${safe}`
      options.map.addLayer({
        id: circleId,
        type: 'circle',
        source: sourceId,
        filter: ['==', '$type', 'Point'],
        paint: {
          'circle-radius': 4,
          'circle-color': DEFAULT_POINT_COLOR,
          'circle-stroke-width': 1,
          'circle-stroke-color': '#0a233a',
          'circle-opacity': 0.9,
        },
        layout: { visibility: 'visible' },
      })
      layerIds.push(circleId)

      // 点标签
      const labelId = `imported-label-${safe}`
      options.map.addLayer({
        id: labelId,
        type: 'symbol',
        source: sourceId,
        filter: ['==', '$type', 'Point'],
        layout: {
          'text-field': ['get', 'name'] as any,
          'text-size': 10,
          'text-offset': [0, 1.2],
          'text-allow-overlap': false,
          visibility: 'visible',
        },
        paint: {
          'text-color': '#d8e6f5',
          'text-halo-color': '#0a1a2a',
          'text-halo-width': 1.5,
        },
      })
      layerIds.push(labelId)
    }

    // 推断主几何类型
    const primaryType = geojson.features.find((f) => f.geometry)?.geometry?.type as ImportedGeometryType ?? 'Unknown'

    // 注册事件监听器并保存引用，以便 removeLayer 时精确移除
    const eventHandlers: LoadedImportedLayer['eventHandlers'] = []

    for (const layerId of layerIds) {
      const clickHandler = (e: any) => {
        if (!e.features || e.features.length === 0) return
        const feature = e.features[0]
        const props = feature.properties ?? {}
        const propLines = Object.entries(props)
          .map(([k, v]) => `<tr><td class="pk">${k}</td><td class="pv">${v}</td></tr>`)
          .join('')
        const html = `<div class="imported-popup"><strong>${name}</strong><table>${propLines}</table></div>`
        new Popup().setLngLat(e.lngLat).setHTML(html).addTo(options.map)
      }
      const enterHandler = () => { options.map.getCanvas().style.cursor = 'pointer' }
      const leaveHandler = () => { options.map.getCanvas().style.cursor = '' }

      options.map.on('click', layerId, clickHandler)
      options.map.on('mouseenter', layerId, enterHandler)
      options.map.on('mouseleave', layerId, leaveHandler)
      eventHandlers.push(
        { type: 'click', layerId, handler: clickHandler },
        { type: 'mouseenter', layerId, handler: enterHandler },
        { type: 'mouseleave', layerId, handler: leaveHandler },
      )
    }

    loaded.set(id, {
      id,
      sourceId,
      layerIds,
      geometryType: primaryType,
      eventHandlers,
    })
  }

  function removeLayer(id: string): void {
    const info = loaded.get(id)
    if (!info) return
    // 移除事件监听器（必须在 removeLayer 之前，否则 MapLibre 可能找不到图层）
    for (const { type, layerId, handler } of info.eventHandlers) {
      options.map.off(type, layerId, handler)
    }
    for (const layerId of info.layerIds) {
      if (options.map.getLayer(layerId)) {
        options.map.removeLayer(layerId)
      }
    }
    if (options.map.getSource(info.sourceId)) {
      options.map.removeSource(info.sourceId)
    }
    loaded.delete(id)
  }

  function setLayerVisibility(id: string, visible: boolean): void {
    const info = loaded.get(id)
    if (!info) return
    const vis = visible ? 'visible' : 'none'
    for (const layerId of info.layerIds) {
      if (options.map.getLayer(layerId)) {
        options.map.setLayoutProperty(layerId, 'visibility', vis)
      }
    }
  }

  function setLayerOpacity(id: string, opacity: number): void {
    const info = loaded.get(id)
    if (!info) return
    for (const layerId of info.layerIds) {
      const layer = options.map.getLayer(layerId) as any
      if (!layer) continue
      if (layer.type === 'fill') {
        options.map.setPaintProperty(layerId, 'fill-opacity', 0.25 * opacity)
      } else if (layer.type === 'line') {
        options.map.setPaintProperty(layerId, 'line-opacity', 0.9 * opacity)
      } else if (layer.type === 'circle') {
        options.map.setPaintProperty(layerId, 'circle-opacity', 0.9 * opacity)
      }
    }
  }

  function getLoadedIds(): string[] {
    return Array.from(loaded.keys())
  }

  function dispose(): void {
    for (const id of Array.from(loaded.keys())) {
      removeLayer(id)
    }
  }

  return {
    addVectorLayer,
    removeLayer,
    setLayerVisibility,
    setLayerOpacity,
    getLoadedIds,
    dispose,
  }
}

export type ImportedLayerModule = ReturnType<typeof createImportedLayerModule>
