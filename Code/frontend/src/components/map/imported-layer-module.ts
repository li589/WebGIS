import type { ImportedGeometryType } from '../../stores/layers/imported-vector'
import {
  Popup,
  type ExpressionSpecification,
  type GeoJSONSourceSpecification,
  type LayerSpecification,
  type MapLayerMouseEvent,
} from 'maplibre-gl'
import {
  dataWorkspaceHighlight,
  dataWorkspaceLayerId,
  dataWorkspaceOpen,
  dataWorkspaceTab,
} from '../../data-manager/core/workspace-store'
import { lngSpanFromList } from '../../services/geo-math'

type MapInstance = import('maplibre-gl').Map
type MapLayerEventType = 'click' | 'mouseenter' | 'mouseleave'

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
  bounds: [number, number, number, number] | null
  displayName: string
  /** 最近一次写入 source 的 geojson 引用，用于检测数据变更 */
  dataRef: GeoJSON.FeatureCollection
  /** 注册的事件监听器引用，用于 removeLayer 时精确移除 */
  eventHandlers: Array<{
    type: MapLayerEventType
    layerId: string
    handler: (e: MapLayerMouseEvent) => void
  }>
}

/**
 * MapLibre WebGL 渲染器不支持 CSS var(--xxx)，paint 属性必须传字面量颜色。
 * 从 :root 解析主题变量计算值，缺失时回退 tokens.css 暗色默认。
 */
function resolveThemeColor(varName: string, fallback: string): string {
  if (typeof document === 'undefined') return fallback
  const value = getComputedStyle(document.documentElement).getPropertyValue(varName).trim()
  return value || fallback
}

function normalizeFeatureCollection(geojson: GeoJSON.FeatureCollection): GeoJSON.FeatureCollection {
  if (geojson && Array.isArray(geojson.features)) return geojson
  return { type: 'FeatureCollection', features: [] }
}

/** 与导入矢量 display accent（--success）对齐；回退 tokens.css 暗色值 */
const FALLBACK_SUCCESS = '#9ff8cf'
const FALLBACK_TEXT_PRIMARY = '#d8e6f5'

function _safeId(id: string): string {
  return id.replace(/[^a-zA-Z0-9_-]/g, '-')
}

function escapeHtml(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

function _hasGeometryType(fc: GeoJSON.FeatureCollection, types: string[]): boolean {
  return fc.features.some((f: GeoJSON.Feature) => f.geometry && types.includes(f.geometry.type))
}

function _collectBounds(fc: GeoJSON.FeatureCollection): [number, number, number, number] | null {
  let minLat = Infinity
  let maxLat = -Infinity
  const lngs: number[] = []
  const visitCoords = (coords: unknown): void => {
    if (!Array.isArray(coords) || coords.length === 0) return
    if (typeof coords[0] === 'number' && typeof coords[1] === 'number') {
      const lng = coords[0] as number
      const lat = coords[1] as number
      if (!Number.isFinite(lng) || !Number.isFinite(lat)) return
      lngs.push(lng)
      minLat = Math.min(minLat, lat)
      maxLat = Math.max(maxLat, lat)
      return
    }
    for (const child of coords) visitCoords(child)
  }
  const visitGeometry = (geometry: GeoJSON.Geometry | null | undefined): void => {
    if (!geometry) return
    if (geometry.type === 'GeometryCollection') {
      for (const child of geometry.geometries) visitGeometry(child)
      return
    }
    visitCoords(geometry.coordinates)
  }
  for (const feature of fc.features) {
    visitGeometry(feature.geometry)
  }
  if (!lngs.length || !Number.isFinite(minLat)) return null
  const span = lngSpanFromList(lngs)
  if (!span) return null
  const [minLng, maxLng] = span
  // 零面积包围盒：扩一点避免 fitBounds 异常
  const pad = 1e-6
  let west = minLng
  let east = maxLng
  let south = minLat
  let north = maxLat
  if (east - west < pad) {
    west -= pad
    east += pad
  }
  if (north - south < pad) {
    south -= pad
    north += pad
  }
  return [west, south, east, north]
}

export function createImportedLayerModule(options: CreateImportedLayerModuleOptions) {
  const loaded = new Map<string, LoadedImportedLayer>()

  function _ensureMap() {
    if (!options.getMapReady()) return false
    return true
  }

  /**
   * 注册/更新导入矢量图层。
   * - 已加载：geojson 引用变化时仅 setData（不重建渲染层）
   * - 未加载：addSource + 渲染层；fill/line/circle 无条件创建（类型 filter
   *   保证空几何不渲染），使空数据图层在后续 setData 后直接显示
   * - 任一步失败：清理半成品并返回 false，交由下次 sync 重试
   */
  function addVectorLayer(id: string, geojson: GeoJSON.FeatureCollection, name: string): boolean {
    if (!_ensureMap()) return false

    const existing = loaded.get(id)
    if (existing) {
      if (existing.dataRef !== geojson) {
        updateLayerData(id, geojson)
      }
      return true
    }

    const fc = normalizeFeatureCollection(geojson)
    const safe = _safeId(id)
    const sourceId = `imported-src-${safe}`
    const layerIds: string[] = []
    const fillColor = resolveThemeColor('--success', FALLBACK_SUCCESS)
    const labelColor = resolveThemeColor('--text-primary', FALLBACK_TEXT_PRIMARY)

    try {
      options.map.addSource(sourceId, {
        type: 'geojson',
        data: fc,
        // 供点选时用 feature.id 作为要素绝对索引，联动属性表行
        generateId: true,
      } as GeoJSONSourceSpecification)

      const beforeAdmin = options.map.getLayer('admin-fill') ? 'admin-fill' : undefined

      // 面图层（Polygon / MultiPolygon）
      const fillId = `imported-fill-${safe}`
      options.map.addLayer(
        {
          id: fillId,
          type: 'fill',
          source: sourceId,
          filter: ['==', '$type', 'Polygon'],
          paint: {
            'fill-color': fillColor,
            'fill-opacity': 0.25,
          },
          layout: { visibility: 'visible' },
        },
        beforeAdmin,
      )
      layerIds.push(fillId)

      // 线图层（含 Polygon 边线）
      const lineId = `imported-line-${safe}`
      options.map.addLayer(
        {
          id: lineId,
          type: 'line',
          source: sourceId,
          paint: {
            'line-color': fillColor,
            'line-width': 2,
            'line-opacity': 0.9,
          },
          layout: { visibility: 'visible' },
        },
        beforeAdmin,
      )
      layerIds.push(lineId)

      // 点图层（Point / MultiPoint）
      const circleId = `imported-circle-${safe}`
      options.map.addLayer(
        {
          id: circleId,
          type: 'circle',
          source: sourceId,
          filter: ['==', '$type', 'Point'],
          paint: {
            'circle-radius': 4,
            'circle-color': fillColor,
            'circle-stroke-width': 1,
            'circle-stroke-color': '#0a233a',
            'circle-opacity': 0.9,
          },
          layout: { visibility: 'visible' },
        },
        beforeAdmin,
      )
      layerIds.push(circleId)

      // 点标签（仅在当前数据含点要素时创建，避免无字形样式下 addLayer 失败）
      if (_hasGeometryType(fc, ['Point', 'MultiPoint'])) {
        const labelId = `imported-label-${safe}`
        options.map.addLayer(
          {
            id: labelId,
            type: 'symbol',
            source: sourceId,
            filter: ['==', '$type', 'Point'],
            layout: {
              'text-field': ['get', 'name'] as ExpressionSpecification,
              'text-size': 10,
              'text-offset': [0, 1.2],
              'text-allow-overlap': false,
              visibility: 'visible',
            },
            paint: {
              'text-color': labelColor,
              'text-halo-color': '#0a1a2a',
              'text-halo-width': 1.5,
            },
          },
          beforeAdmin,
        )
        layerIds.push(labelId)
      }

      // 推断主几何类型
      const primaryType =
        (fc.features.find((f: GeoJSON.Feature) => f.geometry)?.geometry
          ?.type as ImportedGeometryType) ?? 'Unknown'

      // 注册事件监听器并保存引用，以便 removeLayer 时精确移除
      const eventHandlers: LoadedImportedLayer['eventHandlers'] = []

      for (const layerId of layerIds) {
        const clickHandler = (e: MapLayerMouseEvent) => {
          if (!e.features || e.features.length === 0) return
          const feature = e.features[0]
          const props = feature.properties ?? {}
          const propLines = Object.entries(props)
            .map(
              ([k, v]) =>
                `<tr><td class="pk">${escapeHtml(k)}</td><td class="pv">${escapeHtml(String(v ?? ''))}</td></tr>`,
            )
            .join('')
          const title = loaded.get(id)?.displayName ?? name
          const html = `<div class="imported-popup"><strong>${escapeHtml(title)}</strong><table>${propLines}</table></div>`
          new Popup().setLngLat(e.lngLat).setHTML(html).addTo(options.map)
          // 地图点选 → 属性表跟踪（不自动打开工作台；若已打开则切到属性表）
          const geoFeature = {
            type: 'Feature' as const,
            geometry: feature.geometry as GeoJSON.Geometry,
            properties: { ...props },
          }
          const featureIndex =
            typeof feature.id === 'number' && Number.isFinite(feature.id) ? feature.id : undefined
          dataWorkspaceLayerId.value = id
          dataWorkspaceHighlight.value = {
            instanceId: id,
            feature: geoFeature,
            featureIndex,
          }
          if (dataWorkspaceOpen.value) {
            dataWorkspaceTab.value = 'attributes'
          }
        }
        const enterHandler = (_e: MapLayerMouseEvent) => {
          options.map.getCanvas().style.cursor = 'pointer'
        }
        const leaveHandler = (_e: MapLayerMouseEvent) => {
          options.map.getCanvas().style.cursor = ''
        }

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
        bounds: _collectBounds(fc),
        displayName: name,
        dataRef: fc,
        eventHandlers,
      })
      return true
    } catch (err) {
      console.error(`[imported-layer] 添加图层 ${id} 失败:`, err)
      // 清理半成品（事件注册在全部 addLayer 之后，此刻必然尚未注册）
      for (const layerId of layerIds) {
        if (options.map.getLayer(layerId)) options.map.removeLayer(layerId)
      }
      if (options.map.getSource(sourceId)) options.map.removeSource(sourceId)
      return false
    }
  }

  function updateLayerDisplayName(id: string, name: string): void {
    const info = loaded.get(id)
    if (!info) return
    const trimmed = name.trim()
    if (!trimmed) return
    info.displayName = trimmed
  }

  function removeLayer(id: string): void {
    const info = loaded.get(id)
    if (!info) return
    setFeatureHighlight(id, null)
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
      const layer = options.map.getLayer(layerId) as LayerSpecification | undefined
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

  function applyLayerStyle(id: string, style: ImportedLayerStyle, baseOpacity = 1): void {
    const info = loaded.get(id)
    if (!info) return
    const color = style.color || resolveThemeColor('--success', FALLBACK_SUCCESS)
    const width = style.width ?? 2
    const radius = style.radius ?? 4
    const fillOpacity = (style.fillOpacity ?? 0.25) * baseOpacity
    for (const layerId of info.layerIds) {
      const layer = options.map.getLayer(layerId) as LayerSpecification | undefined
      if (!layer) continue
      if (layer.type === 'fill') {
        options.map.setPaintProperty(layerId, 'fill-color', color)
        options.map.setPaintProperty(layerId, 'fill-opacity', fillOpacity)
      } else if (layer.type === 'line') {
        options.map.setPaintProperty(layerId, 'line-color', color)
        options.map.setPaintProperty(layerId, 'line-width', width)
        options.map.setPaintProperty(layerId, 'line-opacity', 0.9 * baseOpacity)
      } else if (layer.type === 'circle') {
        options.map.setPaintProperty(layerId, 'circle-color', color)
        options.map.setPaintProperty(layerId, 'circle-radius', radius)
        options.map.setPaintProperty(layerId, 'circle-opacity', 0.9 * baseOpacity)
      }
    }
  }

  function updateLayerData(id: string, geojson: GeoJSON.FeatureCollection): void {
    const info = loaded.get(id)
    if (!info) return
    const src = options.map.getSource(info.sourceId) as
      { setData?: (d: unknown) => void } | undefined
    if (src?.setData) {
      const fc = normalizeFeatureCollection(geojson)
      src.setData(fc)
      info.bounds = _collectBounds(fc)
      info.dataRef = fc
    }
  }

  function setFeatureHighlight(id: string, feature: GeoJSON.Feature | null): void {
    if (!_ensureMap()) return
    const safe = _safeId(id)
    const hlSource = `imported-hl-src-${safe}`
    const hlLine = `imported-hl-line-${safe}`
    const hlCircle = `imported-hl-circle-${safe}`

    const clearHl = () => {
      if (options.map.getLayer(hlLine)) options.map.removeLayer(hlLine)
      if (options.map.getLayer(hlCircle)) options.map.removeLayer(hlCircle)
      if (options.map.getSource(hlSource)) options.map.removeSource(hlSource)
    }

    if (!feature) {
      clearHl()
      return
    }

    clearHl()
    const fc: GeoJSON.FeatureCollection = { type: 'FeatureCollection', features: [feature] }
    const hlColor = resolveThemeColor('--warning', '#ffb070')
    options.map.addSource(hlSource, {
      type: 'geojson',
      data: fc,
    } as GeoJSONSourceSpecification)
    options.map.addLayer({
      id: hlLine,
      type: 'line',
      source: hlSource,
      paint: {
        'line-color': hlColor,
        'line-width': 3.5,
        'line-opacity': 0.95,
      },
    })
    options.map.addLayer({
      id: hlCircle,
      type: 'circle',
      source: hlSource,
      filter: ['==', '$type', 'Point'],
      paint: {
        'circle-radius': 8,
        'circle-color': hlColor,
        'circle-stroke-width': 2,
        'circle-stroke-color': '#0a233a',
        'circle-opacity': 0.95,
      },
    })

    const b = _collectBounds(fc)
    if (b) {
      options.map.fitBounds(
        [
          [b[0], b[1]],
          [b[2], b[3]],
        ],
        { padding: 80, maxZoom: 14, duration: 450 },
      )
    }
  }

  function getLoadedIds(): string[] {
    return Array.from(loaded.keys())
  }

  /** 返回某导入层当前在地图上的 MapLibre layer id（自下而上） */
  function getLayerIds(id: string): string[] {
    return (
      loaded.get(id)?.layerIds.filter((layerId) => Boolean(options.map.getLayer(layerId))) ?? []
    )
  }

  function fitLayers(ids: string[]): void {
    if (!options.getMapReady()) return
    let minLng = Infinity
    let minLat = Infinity
    let maxLng = -Infinity
    let maxLat = -Infinity
    for (const id of ids) {
      const bounds = loaded.get(id)?.bounds
      if (!bounds) continue
      minLng = Math.min(minLng, bounds[0])
      minLat = Math.min(minLat, bounds[1])
      maxLng = Math.max(maxLng, bounds[2])
      maxLat = Math.max(maxLat, bounds[3])
    }
    if (!Number.isFinite(minLng) || !Number.isFinite(minLat)) return
    // 避免零面积包围盒导致 fitBounds 异常
    const pad = 0.0001
    if (maxLng - minLng < pad) {
      minLng -= pad
      maxLng += pad
    }
    if (maxLat - minLat < pad) {
      minLat -= pad
      maxLat += pad
    }
    options.map.fitBounds(
      [
        [minLng, minLat],
        [maxLng, maxLat],
      ],
      { padding: 48, maxZoom: 14, duration: 600 },
    )
  }

  function dispose(): void {
    for (const id of Array.from(loaded.keys())) {
      removeLayer(id)
    }
  }

  return {
    addVectorLayer,
    updateLayerDisplayName,
    removeLayer,
    setLayerVisibility,
    setLayerOpacity,
    applyLayerStyle,
    updateLayerData,
    setFeatureHighlight,
    getLoadedIds,
    getLayerIds,
    fitLayers,
    dispose,
  }
}

export type ImportedLayerModule = ReturnType<typeof createImportedLayerModule>
