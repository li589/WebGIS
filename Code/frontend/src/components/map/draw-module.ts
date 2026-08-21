/**
 * 绘制矢量要素交互模块 — MapLibre 事件绑定 + GeoJSON 渲染。
 *
 * 职责：
 *   1. 绑定 MapLibre 事件：click（添加顶点）、dblclick（闭合多边形/完成线）、
 *      contextmenu（撤销）、mousemove（预览）、mousedown/mouseup（矩形拖拽）
 *   2. 管理 4 个 MapLibre GeoJSON Source + Layer：
 *      - draw-features-fill → draw-features-fill-layer（面要素填充，半透明）
 *      - draw-features-line → draw-features-line-layer（面边界 + 线要素）
 *      - draw-vertices → draw-vertices-layer（顶点圆点）
 *      - draw-preview → draw-preview-layer（预览虚线 + 矩形预览）
 *   3. 协调 DrawCanvas 标注层（show/hide/updateState）
 *   4. 模式切换时禁用 doubleClickZoom / boxZoom
 *
 * 状态经依赖注入获取（与 measure-module 一致），不在工厂内直接 useStore，
 * 以兼容无 Pinia 上下文的模块组合测试。
 */
import type { GeoJSONSource, Map as MaplibreMap, MapMouseEvent } from 'maplibre-gl'

import { DrawCanvas } from './draw-canvas'
import type { DrawMode, DrawVertex, DrawFeature } from '../../stores/draw-store'
import type { InteractionMode } from '../../stores/ui'

const POINT_RADIUS = 5
const POINT_RADIUS_FIRST = 7
const POINT_STROKE_WIDTH = 2
const LINE_WIDTH = 2
const PREVIEW_LINE_WIDTH = 3
const PREVIEW_LINE_OPACITY = 0.9
const PREVIEW_LINE_DASHARRAY = [4, 3] as [number, number]
const FILL_COLOR = 'rgba(43, 127, 255, 0.15)'
const FILL_OUTLINE_COLOR = '#2b7fff'
const LINE_COLOR = '#2b7fff'
const POINT_COLOR_FIRST = '#f59e0b'
const POINT_COLOR_ACTIVE = '#2b7fff'
const POINT_STROKE_COLOR = '#fff'

const SOURCE_FEATURES_FILL = 'draw-features-fill'
const SOURCE_FEATURES_LINE = 'draw-features-line'
const SOURCE_VERTICES = 'draw-vertices'
const SOURCE_PREVIEW = 'draw-preview'
const LAYER_FEATURES_FILL = 'draw-features-fill-layer'
const LAYER_FEATURES_LINE = 'draw-features-line-layer'
const LAYER_VERTICES = 'draw-vertices-layer'
const LAYER_PREVIEW_PATH = 'draw-preview-path-layer'
const LAYER_PREVIEW = 'draw-preview-layer'

/** 多边形自动闭合的像素阈值 */
const SNAP_PIXEL_THRESHOLD = 20

export interface DrawStateSnapshot {
  drawMode: DrawMode
  features: DrawFeature[]
  activeVertices: DrawVertex[]
  isDrawing: boolean
  hoverPoint: DrawVertex | null
  selectedFeatureIndex: number | null
}

export interface CreateDrawModuleOptions {
  map: MaplibreMap
  getInteractionMode: () => InteractionMode
  getDrawState: () => DrawStateSnapshot
  addVertex: (v: DrawVertex) => void
  undoLastVertex: () => void
  setHoverPoint: (p: DrawVertex | null) => void
  addFeature: (f: DrawFeature) => void
  clearActiveVertices: () => void
  setDrawingFlag: (v: boolean) => void
  scheduleDraftPersist: () => void
}

export interface DrawModule {
  bindEvents: () => void
  applyDrawMode: () => void
  syncFromStore: () => void
  dispose: () => void
}

export function createDrawModule(options: CreateDrawModuleOptions): DrawModule {
  const { map } = options
  const canvas = new DrawCanvas(map)

  let sourcesAdded = false
  let eventsBound = false
  const registeredHandlers: Array<{
    event: string
    handler: (ev: MapMouseEvent) => void
  }> = []

  // 矩形模式状态
  let rectStart: DrawVertex | null = null

  function ensureSources(): void {
    if (sourcesAdded) return
    if (!map.loaded()) return
    if (map.getSource(SOURCE_FEATURES_FILL)) {
      sourcesAdded = true
      return
    }

    map.addSource(SOURCE_FEATURES_FILL, {
      type: 'geojson',
      data: { type: 'FeatureCollection', features: [] },
    })
    map.addSource(SOURCE_FEATURES_LINE, {
      type: 'geojson',
      data: { type: 'FeatureCollection', features: [] },
    })
    map.addSource(SOURCE_VERTICES, {
      type: 'geojson',
      data: { type: 'FeatureCollection', features: [] },
    })
    map.addSource(SOURCE_PREVIEW, {
      type: 'geojson',
      data: { type: 'FeatureCollection', features: [] },
    })

    map.addLayer({
      id: LAYER_FEATURES_FILL,
      type: 'fill',
      source: SOURCE_FEATURES_FILL,
      paint: {
        'fill-color': FILL_COLOR,
        'fill-outline-color': FILL_OUTLINE_COLOR,
      },
    })
    map.addLayer({
      id: LAYER_FEATURES_LINE,
      type: 'line',
      source: SOURCE_FEATURES_LINE,
      layout: { 'line-cap': 'round', 'line-join': 'round' },
      paint: {
        'line-color': LINE_COLOR,
        'line-width': LINE_WIDTH,
      },
    })
    map.addLayer({
      id: LAYER_PREVIEW_PATH,
      type: 'line',
      source: SOURCE_PREVIEW,
      layout: { 'line-cap': 'round', 'line-join': 'round' },
      filter: ['==', ['get', 'kind'], 'path'],
      paint: {
        'line-color': LINE_COLOR,
        'line-width': PREVIEW_LINE_WIDTH,
        'line-opacity': PREVIEW_LINE_OPACITY,
      },
    })
    map.addLayer({
      id: LAYER_PREVIEW,
      type: 'line',
      source: SOURCE_PREVIEW,
      layout: { 'line-cap': 'round', 'line-join': 'round' },
      filter: ['==', ['get', 'kind'], 'cursor'],
      paint: {
        'line-color': LINE_COLOR,
        'line-width': PREVIEW_LINE_WIDTH,
        'line-opacity': PREVIEW_LINE_OPACITY,
        'line-dasharray': PREVIEW_LINE_DASHARRAY,
      },
    })
    map.addLayer({
      id: LAYER_VERTICES,
      type: 'circle',
      source: SOURCE_VERTICES,
      paint: {
        'circle-radius': [
          'case',
          ['==', ['get', 'isFirst'], true],
          POINT_RADIUS_FIRST,
          POINT_RADIUS,
        ],
        'circle-color': [
          'case',
          ['==', ['get', 'isFirst'], true],
          POINT_COLOR_FIRST,
          POINT_COLOR_ACTIVE,
        ],
        'circle-stroke-width': POINT_STROKE_WIDTH,
        'circle-stroke-color': POINT_STROKE_COLOR,
      },
    })

    sourcesAdded = true
  }

  function syncGeoJSON(): void {
    if (!sourcesAdded) return

    const { features, activeVertices, isDrawing, hoverPoint } = options.getDrawState()
    const currentMode = options.getDrawState().drawMode

    // 已完成的面要素填充
    const fillSource = map.getSource(SOURCE_FEATURES_FILL) as GeoJSONSource | undefined
    if (fillSource) {
      const polygonFeatures = features.filter((f) => f.geometry.type === 'Polygon')
      fillSource.setData({
        type: 'FeatureCollection',
        features: polygonFeatures.map((f) => ({
          type: 'Feature' as const,
          geometry: f.geometry,
          properties: f.properties,
        })),
      })
    }

    // 已完成的面边界 + 线要素
    const lineSource = map.getSource(SOURCE_FEATURES_LINE) as GeoJSONSource | undefined
    if (lineSource) {
      const lineFeatures = features.map((f) => {
        if (f.geometry.type === 'Polygon') {
          return {
            type: 'Feature' as const,
            geometry: {
              type: 'LineString' as const,
              coordinates: f.geometry.coordinates[0],
            },
            properties: f.properties,
          }
        }
        return { type: 'Feature' as const, geometry: f.geometry, properties: f.properties }
      })
      lineSource.setData({ type: 'FeatureCollection', features: lineFeatures })
    }

    // 顶点圆点
    const verticesSource = map.getSource(SOURCE_VERTICES) as GeoJSONSource | undefined
    if (verticesSource) {
      const vertexFeatures: GeoJSON.Feature<GeoJSON.Point>[] = activeVertices.map((v, i) => ({
        type: 'Feature',
        geometry: { type: 'Point', coordinates: [v.lng, v.lat] },
        properties: { isFirst: i === 0 },
      }))
      verticesSource.setData({ type: 'FeatureCollection', features: vertexFeatures })
    }

    // 预览：已放置折线整段（实线 path）+ 末点→光标段（虚线 cursor）；
    // 矩形：拖拽整框预览（虚线）
    const previewSource = map.getSource(SOURCE_PREVIEW) as GeoJSONSource | undefined
    if (previewSource) {
      const previewFeatures: GeoJSON.Feature<GeoJSON.LineString>[] = []

      if (currentMode === 'rectangle' && rectStart && hoverPoint && isDrawing) {
        previewFeatures.push({
          type: 'Feature',
          geometry: {
            type: 'LineString',
            coordinates: [
              [rectStart.lng, rectStart.lat],
              [hoverPoint.lng, rectStart.lat],
              [hoverPoint.lng, hoverPoint.lat],
              [rectStart.lng, hoverPoint.lat],
              [rectStart.lng, rectStart.lat],
            ],
          },
          properties: { kind: 'cursor' },
        })
      } else if (isDrawing && hoverPoint && activeVertices.length > 0) {
        if (activeVertices.length >= 2) {
          previewFeatures.push({
            type: 'Feature',
            geometry: {
              type: 'LineString',
              coordinates: activeVertices.map((v) => [v.lng, v.lat]),
            },
            properties: { kind: 'path' },
          })
        }
        const last = activeVertices[activeVertices.length - 1]
        const cursorCoords: number[][] = [[last.lng, last.lat]]
        if (currentMode === 'polygon' && isNearFirstVertex(hoverPoint, activeVertices)) {
          cursorCoords.push([activeVertices[0].lng, activeVertices[0].lat])
        } else {
          cursorCoords.push([hoverPoint.lng, hoverPoint.lat])
        }
        previewFeatures.push({
          type: 'Feature',
          geometry: { type: 'LineString', coordinates: cursorCoords },
          properties: { kind: 'cursor' },
        })
      }

      previewSource.setData({
        type: 'FeatureCollection',
        features: previewFeatures,
      } as GeoJSON.FeatureCollection)
    }
  }

  function syncCanvas(): void {
    const s = options.getDrawState()
    canvas.updateState(
      s.activeVertices,
      s.features,
      s.hoverPoint,
      s.isDrawing,
      s.drawMode,
      s.selectedFeatureIndex,
    )
  }

  function syncAll(): void {
    syncGeoJSON()
    syncCanvas()
  }

  function isNearFirstVertex(hover: DrawVertex, vertices: DrawVertex[]): boolean {
    if (vertices.length < 2) return false
    const first = vertices[0]
    const p1 = map.project([first.lng, first.lat])
    const p2 = map.project([hover.lng, hover.lat])
    const dx = p2.x - p1.x
    const dy = p2.y - p1.y
    return Math.sqrt(dx * dx + dy * dy) < SNAP_PIXEL_THRESHOLD
  }

  function buildPolygonFeature(vertices: DrawVertex[]): DrawFeature {
    const coords = vertices.map((v) => [v.lng, v.lat])
    coords.push(coords[0]) // 闭合环
    return {
      geometry: {
        type: 'Polygon',
        coordinates: [coords],
      },
      properties: {},
    }
  }

  function buildLineFeature(vertices: DrawVertex[]): DrawFeature {
    return {
      geometry: {
        type: 'LineString',
        coordinates: vertices.map((v) => [v.lng, v.lat]),
      },
      properties: {},
    }
  }

  function buildRectFeature(start: DrawVertex, end: DrawVertex): DrawFeature {
    const coords = [
      [start.lng, start.lat],
      [end.lng, start.lat],
      [end.lng, end.lat],
      [start.lng, end.lat],
      [start.lng, start.lat],
    ]
    return {
      geometry: { type: 'Polygon', coordinates: [coords] },
      properties: {},
    }
  }

  function completePolygon(): void {
    const vertices = options.getDrawState().activeVertices
    if (vertices.length < 3) return
    options.addFeature(buildPolygonFeature(vertices))
    options.clearActiveVertices()
    syncAll()
    options.scheduleDraftPersist()
  }

  function completeLine(): void {
    const vertices = options.getDrawState().activeVertices
    if (vertices.length < 2) return
    options.addFeature(buildLineFeature(vertices))
    options.clearActiveVertices()
    syncAll()
    options.scheduleDraftPersist()
  }

  // ── 事件处理器 ─────────────────────────────────────────

  function onClick(e: MapMouseEvent): void {
    if (options.getInteractionMode() !== 'draw') return
    const mode = options.getDrawState().drawMode
    if (mode === 'rectangle') return

    const point: DrawVertex = { lng: e.lngLat.lng, lat: e.lngLat.lat }

    if (mode === 'polygon' && isNearFirstVertex(point, options.getDrawState().activeVertices)) {
      completePolygon()
      return
    }

    options.addVertex(point)
    syncAll()
  }

  function onDblClick(e: MapMouseEvent): void {
    if (options.getInteractionMode() !== 'draw') return
    e.preventDefault()
    const mode = options.getDrawState().drawMode
    if (mode === 'rectangle') return

    // 双击会先触发两次 click，末尾顶点被重复添加 —— 先撤销
    if (options.getDrawState().activeVertices.length > 0) {
      options.undoLastVertex()
    }

    if (mode === 'polygon') {
      if (options.getDrawState().activeVertices.length >= 3) {
        completePolygon()
      }
    } else if (mode === 'line') {
      if (options.getDrawState().activeVertices.length >= 2) {
        completeLine()
      }
    }
    syncAll()
  }

  function onContextMenu(e: MapMouseEvent): void {
    if (options.getInteractionMode() !== 'draw') return
    e.preventDefault()
    if (options.getDrawState().drawMode === 'rectangle') return
    options.undoLastVertex()
    syncAll()
  }

  function onMouseMove(e: MapMouseEvent): void {
    if (options.getInteractionMode() !== 'draw') return
    const mode = options.getDrawState().drawMode

    if (mode === 'rectangle' && rectStart) {
      options.setHoverPoint({ lng: e.lngLat.lng, lat: e.lngLat.lat })
      syncAll()
      return
    }

    // 首点前（isDrawing=false）也反馈光标位置；不产生预览线（顶点为空）
    options.setHoverPoint({ lng: e.lngLat.lng, lat: e.lngLat.lat })
    syncAll()
  }

  function onMouseDown(e: MapMouseEvent): void {
    if (options.getInteractionMode() !== 'draw') return
    if (options.getDrawState().drawMode !== 'rectangle') return
    rectStart = { lng: e.lngLat.lng, lat: e.lngLat.lat }
    options.clearActiveVertices()
    options.setDrawingFlag(true)
    syncAll()
  }

  function onMouseUp(e: MapMouseEvent): void {
    if (options.getInteractionMode() !== 'draw') return
    if (options.getDrawState().drawMode !== 'rectangle') return
    if (!rectStart) return

    const end: DrawVertex = { lng: e.lngLat.lng, lat: e.lngLat.lat }
    const dx = Math.abs(end.lng - rectStart.lng)
    const dy = Math.abs(end.lat - rectStart.lat)
    // S4：忽略过小的矩形（可能是误点击，避免产生零面积要素）
    if (dx < 1e-4 && dy < 1e-4) {
      rectStart = null
      options.setDrawingFlag(false)
      options.setHoverPoint(null)
      syncAll()
      return
    }

    options.addFeature(buildRectFeature(rectStart, end))
    rectStart = null
    options.setDrawingFlag(false)
    options.setHoverPoint(null)
    syncAll()
    options.scheduleDraftPersist()
  }

  function bindEvents(): void {
    if (eventsBound) return
    eventsBound = true

    if (map.loaded()) {
      ensureSources()
    } else {
      const onLoad = () => ensureSources()
      map.once('load', onLoad)
      registeredHandlers.push({
        event: 'load',
        handler: onLoad as unknown as (ev: MapMouseEvent) => void,
      })
    }

    map.on('click', onClick)
    map.on('dblclick', onDblClick)
    map.on('contextmenu', onContextMenu)
    map.on('mousemove', onMouseMove)
    map.on('mousedown', onMouseDown)
    map.on('mouseup', onMouseUp)

    registeredHandlers.push(
      { event: 'click', handler: onClick },
      { event: 'dblclick', handler: onDblClick },
      { event: 'contextmenu', handler: onContextMenu },
      { event: 'mousemove', handler: onMouseMove },
      { event: 'mousedown', handler: onMouseDown },
      { event: 'mouseup', handler: onMouseUp },
    )
  }

  function applyDrawMode(): void {
    const isDraw = options.getInteractionMode() === 'draw'
    if (isDraw) {
      // S6：禁用双击缩放，避免与完成手势冲突
      if (map.doubleClickZoom) map.doubleClickZoom.disable()
      if (map.boxZoom) map.boxZoom.disable()
      ensureSources()
      canvas.show()
      syncAll()
    } else {
      if (map.doubleClickZoom) map.doubleClickZoom.enable()
      if (map.boxZoom) map.boxZoom.enable()
      canvas.hide()
      rectStart = null
    }
  }

  /** 绘制相关层整体置顶（数据层后添加会压过绘制层，报障 2026-08-22）。 */
  function bringToFront(): void {
    const order = [
      LAYER_FEATURES_FILL,
      LAYER_FEATURES_LINE,
      LAYER_PREVIEW_PATH,
      LAYER_PREVIEW,
      LAYER_VERTICES,
    ]
    for (const layerId of order) {
      try {
        if (map.getLayer(layerId)) map.moveLayer(layerId)
      } catch {
        // map 已销毁/层并发移除：忽略
      }
    }
  }

  function dispose(): void {
    for (const { event, handler } of registeredHandlers.splice(0)) {
      map.off(event, handler as (ev: MapMouseEvent & object) => void)
    }
    eventsBound = false

    if (map.getLayer(LAYER_VERTICES)) map.removeLayer(LAYER_VERTICES)
    if (map.getLayer(LAYER_PREVIEW)) map.removeLayer(LAYER_PREVIEW)
    if (map.getLayer(LAYER_PREVIEW_PATH)) map.removeLayer(LAYER_PREVIEW_PATH)
    if (map.getLayer(LAYER_FEATURES_LINE)) map.removeLayer(LAYER_FEATURES_LINE)
    if (map.getLayer(LAYER_FEATURES_FILL)) map.removeLayer(LAYER_FEATURES_FILL)
    if (map.getSource(SOURCE_VERTICES)) map.removeSource(SOURCE_VERTICES)
    if (map.getSource(SOURCE_PREVIEW)) map.removeSource(SOURCE_PREVIEW)
    if (map.getSource(SOURCE_FEATURES_LINE)) map.removeSource(SOURCE_FEATURES_LINE)
    if (map.getSource(SOURCE_FEATURES_FILL)) map.removeSource(SOURCE_FEATURES_FILL)
    sourcesAdded = false

    canvas.dispose()
  }

  return {
    bindEvents,
    applyDrawMode,
    syncFromStore: syncAll,
    bringToFront,
    dispose,
  }
}
