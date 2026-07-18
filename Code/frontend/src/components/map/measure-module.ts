/**
 * 测量路径交互模块 — MapLibre 事件绑定 + GeoJSON 路径渲染。
 *
 * 职责：
 *   1. 绑定 MapLibre 事件：click（添加点）、dblclick（完成）、contextmenu（撤销）、mousemove（预览）
 *   2. 管理 3 个 MapLibre GeoJSON Source + Layer：
 *      - measure-points → measure-points-layer（圆点，半径 5px，蓝色填充 + 白色边框）
 *      - measure-line → measure-line-layer（实线，2px，蓝色 #2b7fff）
 *      - measure-preview → measure-preview-layer（虚线，2px，半透明蓝色）
 *   3. 协调 MeasureCanvas 标注层（show/hide/updateState）
 *   4. 模式切换时禁用 doubleClickZoom / boxZoom（dragPan 由 mapInteractionModule 管理）
 *
 * 设计要点：
 *   - 路径线 + 圆点用 MapLibre GeoJSON Layer，与底图同步缩放/平移，无需手动重绘
 *   - 标注层（文字 + 预览虚线）由 MeasureCanvas 2D 渲染（文字描边效果 MapLibre 难以实现）
 *   - GeoJSON 在每次 store action 后整体重建（路径点数少，性能不是瓶颈）
 */
import type { Map as MaplibreMap, MapMouseEvent } from 'maplibre-gl'

import { MeasureCanvas } from './measure-canvas'
import type { InteractionMode, MeasurePoint, MeasureState } from '../../stores/ui'

/** 圆点半径（px） */
const POINT_RADIUS = 5

/** 圆点边框宽度（px） */
const POINT_STROKE_WIDTH = 2

/** 路径线宽度（px） */
const LINE_WIDTH = 2

/** 预览虚线宽度（px） */
const PREVIEW_LINE_WIDTH = 2

/** 预览虚线透明度 */
const PREVIEW_LINE_OPACITY = 0.6

/** 预览虚线 dasharray */
const PREVIEW_LINE_DASHARRAY = [4, 3] as [number, number]

/** 路径主色（蓝色） */
const LINE_COLOR = '#2b7fff'

/** Source/Layer IDs */
const SOURCE_POINTS = 'measure-points'
const SOURCE_LINE = 'measure-line'
const SOURCE_PREVIEW = 'measure-preview'
const LAYER_POINTS = 'measure-points-layer'
const LAYER_LINE = 'measure-line-layer'
const LAYER_PREVIEW = 'measure-preview-layer'

export interface MeasureModule {
  bindEvents: () => void
  applyMeasureMode: () => void
  dispose: () => void
}

export interface CreateMeasureModuleOptions {
  map: MaplibreMap
  getInteractionMode: () => InteractionMode
  getMeasureState: () => MeasureState
  addMeasurePoint: (p: MeasurePoint) => void
  undoLastMeasurePoint: () => void
  completeMeasure: () => void
  setHoverPoint: (p: MeasurePoint | null) => void
  clearMeasure: () => void
}

export function createMeasureModule(
  options: CreateMeasureModuleOptions,
): MeasureModule {
  const { map } = options
  const canvas = new MeasureCanvas(map)

  let sourcesAdded = false
  let eventsBound = false
  /** 已注册的事件处理器引用，用于 dispose 时移除 */
  const registeredHandlers: Array<{ event: string; handler: (...args: any[]) => void }> = []

  /**
   * 添加 GeoJSON Source + Layer（仅一次，map.loaded 后调用）。
   *
   * 幂等：若 source 已存在则跳过。
   */
  function ensureSources(): void {
    if (sourcesAdded) return
    if (!map.loaded()) return
    // 防止重复添加（dispose 后 re-bind 场景）
    if (map.getSource(SOURCE_POINTS)) {
      sourcesAdded = true
      return
    }

    // ── Source：空 FeatureCollection ──
    map.addSource(SOURCE_POINTS, {
      type: 'geojson',
      data: { type: 'FeatureCollection', features: [] },
    })
    map.addSource(SOURCE_LINE, {
      type: 'geojson',
      data: { type: 'FeatureCollection', features: [] },
    })
    map.addSource(SOURCE_PREVIEW, {
      type: 'geojson',
      data: { type: 'FeatureCollection', features: [] },
    })

    // ── Layer：圆点 / 实线 / 虚线 ──
    // 渲染顺序：line（底层）→ preview（中层）→ points（顶层）
    map.addLayer({
      id: LAYER_LINE,
      type: 'line',
      source: SOURCE_LINE,
      layout: {
        'line-cap': 'round',
        'line-join': 'round',
      },
      paint: {
        'line-color': LINE_COLOR,
        'line-width': LINE_WIDTH,
      },
    })
    map.addLayer({
      id: LAYER_PREVIEW,
      type: 'line',
      source: SOURCE_PREVIEW,
      layout: {
        'line-cap': 'round',
        'line-join': 'round',
      },
      paint: {
        'line-color': LINE_COLOR,
        'line-width': PREVIEW_LINE_WIDTH,
        'line-opacity': PREVIEW_LINE_OPACITY,
        'line-dasharray': PREVIEW_LINE_DASHARRAY,
      },
    })
    map.addLayer({
      id: LAYER_POINTS,
      type: 'circle',
      source: SOURCE_POINTS,
      paint: {
        'circle-radius': POINT_RADIUS,
        'circle-color': LINE_COLOR,
        'circle-stroke-width': POINT_STROKE_WIDTH,
        'circle-stroke-color': '#ffffff',
      },
    })

    sourcesAdded = true
  }

  /**
   * 从 store state 重建 3 个 source 的 GeoJSON 数据。
   *
   * 路径点少（通常 < 100），整体重建比增量更新更简单且性能可接受。
   */
  function syncGeoJSON(): void {
    if (!sourcesAdded) return
    const { points, isDrawing, hoverPoint } = options.getMeasureState()

    // ── 圆点 FeatureCollection ──
    const pointFeatures: GeoJSON.Feature<GeoJSON.Point>[] = points.map((p) => ({
      type: 'Feature',
      geometry: { type: 'Point', coordinates: [p.lng, p.lat] },
      properties: {},
    }))
    const pointsSource = map.getSource(SOURCE_POINTS) as maplibregl.GeoJSONSource | undefined
    if (pointsSource) {
      pointsSource.setData({
        type: 'FeatureCollection',
        features: pointFeatures,
      } as GeoJSON.FeatureCollection)
    }

    // ── 实线路径（LineString 或空）──
    const lineSource = map.getSource(SOURCE_LINE) as maplibregl.GeoJSONSource | undefined
    if (lineSource) {
      if (points.length >= 2) {
        const coords = points.map((p) => [p.lng, p.lat])
        lineSource.setData({
          type: 'Feature',
          geometry: { type: 'LineString', coordinates: coords },
          properties: {},
        } as GeoJSON.Feature<GeoJSON.LineString>)
      } else {
        lineSource.setData({
          type: 'FeatureCollection',
          features: [],
        } as GeoJSON.FeatureCollection)
      }
    }

    // ── 预览虚线（最后一个点 → hoverPoint）──
    const previewSource = map.getSource(SOURCE_PREVIEW) as maplibregl.GeoJSONSource | undefined
    if (previewSource) {
      if (isDrawing && hoverPoint && points.length > 0) {
        const last = points[points.length - 1]
        previewSource.setData({
          type: 'Feature',
          geometry: {
            type: 'LineString',
            coordinates: [
              [last.lng, last.lat],
              [hoverPoint.lng, hoverPoint.lat],
            ],
          },
          properties: {},
        } as GeoJSON.Feature<GeoJSON.LineString>)
      } else {
        previewSource.setData({
          type: 'FeatureCollection',
          features: [],
        } as GeoJSON.FeatureCollection)
      }
    }
  }

  /**
   * 同步 Canvas 标注层状态并重绘。
   *
   * Canvas 标注包括：每段距离 + 角度、预览段距离 + 角度、总距离。
   */
  function syncCanvas(): void {
    const { points, isDrawing, hoverPoint } = options.getMeasureState()
    canvas.updateState(points, hoverPoint, isDrawing)
  }

  /** 一站式同步：GeoJSON + Canvas 标注 */
  function syncAll(): void {
    syncGeoJSON()
    syncCanvas()
  }

  // ── 事件处理器 ─────────────────────────────────────────

  function onClick(e: MapMouseEvent): void {
    if (options.getInteractionMode() !== 'measure') return
    options.addMeasurePoint({ lng: e.lngLat.lng, lat: e.lngLat.lat })
    syncAll()
  }

  function onDblClick(e: MapMouseEvent): void {
    if (options.getInteractionMode() !== 'measure') return
    e.preventDefault() // 阻止默认双击缩放
    options.completeMeasure()
    syncAll()
  }

  function onContextMenu(e: MapMouseEvent): void {
    if (options.getInteractionMode() !== 'measure') return
    e.preventDefault() // 阻止右键菜单
    options.undoLastMeasurePoint()
    syncAll()
  }

  function onMouseMove(e: MapMouseEvent): void {
    if (options.getInteractionMode() !== 'measure') return
    if (!options.getMeasureState().isDrawing) return
    options.setHoverPoint({ lng: e.lngLat.lng, lat: e.lngLat.lat })
    syncAll()
  }

  function bindEvents(): void {
    if (eventsBound) return
    eventsBound = true

    // 若 map 已 loaded，立即添加 source/layer；否则等 load 事件
    if (map.loaded()) {
      ensureSources()
    } else {
      const onLoad = () => ensureSources()
      map.once('load', onLoad)
      registeredHandlers.push({ event: 'load', handler: onLoad })
    }

    // 绑定交互事件
    map.on('click', onClick)
    map.on('dblclick', onDblClick)
    map.on('contextmenu', onContextMenu)
    map.on('mousemove', onMouseMove)

    registeredHandlers.push(
      { event: 'click', handler: onClick as (...args: any[]) => void },
      { event: 'dblclick', handler: onDblClick as (...args: any[]) => void },
      { event: 'contextmenu', handler: onContextMenu as (...args: any[]) => void },
      { event: 'mousemove', handler: onMouseMove as (...args: any[]) => void },
    )
  }

  function applyMeasureMode(): void {
    const isMeasure = options.getInteractionMode() === 'measure'
    if (isMeasure) {
      // 禁用会干扰测量的内置交互
      // 注意：dragPan 由 mapInteractionModule.applyInteractionMode() 管理（select/measure 都禁用）
      if (map.doubleClickZoom) map.doubleClickZoom.disable()
      if (map.boxZoom) map.boxZoom.disable()
      // 确保 source/layer 就绪（measure 模式可能首次激活时 map 已 loaded）
      ensureSources()
      canvas.show()
      syncAll() // 重绘已有路径
    } else {
      if (map.doubleClickZoom) map.doubleClickZoom.enable()
      if (map.boxZoom) map.boxZoom.enable()
      canvas.hide()
    }
  }

  function dispose(): void {
    // 移除事件监听
    for (const { event, handler } of registeredHandlers.splice(0)) {
      map.off(event as any, handler)
    }
    eventsBound = false

    // 移除 Layer + Source（顺序：先 Layer 后 Source）
    if (map.getLayer(LAYER_POINTS)) map.removeLayer(LAYER_POINTS)
    if (map.getLayer(LAYER_LINE)) map.removeLayer(LAYER_LINE)
    if (map.getLayer(LAYER_PREVIEW)) map.removeLayer(LAYER_PREVIEW)
    if (map.getSource(SOURCE_POINTS)) map.removeSource(SOURCE_POINTS)
    if (map.getSource(SOURCE_LINE)) map.removeSource(SOURCE_LINE)
    if (map.getSource(SOURCE_PREVIEW)) map.removeSource(SOURCE_PREVIEW)
    sourcesAdded = false

    // 销毁 Canvas 标注层
    canvas.dispose()
  }

  return {
    bindEvents,
    applyMeasureMode,
    dispose,
  }
}
