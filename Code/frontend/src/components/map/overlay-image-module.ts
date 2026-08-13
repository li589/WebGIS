import { ref } from 'vue'
import { showToast } from '../../data-manager/core/workspace-store'
import { overlaySafeWgs84Bounds } from '../../services/geo-math'
import { buildOverlayStyleQuery } from './layer-symbology'
import type { ImageSourceSpecification } from 'maplibre-gl'

type MapInstance = import('maplibre-gl').Map

export interface OverlayStyleParams {
  palette?: string | null
  vmin?: number | null
  vmax?: number | null
  nodataMode?: 'transparent' | 'solid' | null
  nodataColor?: string | null
  /** 有用户覆盖或 supports_recolor 时强制带样式 query */
  forceStyle?: boolean
}

export interface OverlayTimeState {
  layerId: string
  category: 'static' | 'time-series'
  timeList: string[]
  currentTime: string | null
  palette: string
  unit: string
  vmin: number | null
  vmax: number | null
  opacity: number
  bounds: [number, number, number, number] | null
}

/**
 * 防御性 bounds 校验：后端 CRS 重投影/检测可能产生 NaN、跨 ±180° 包围盒、
 * 顺序错乱等异常 bounds。直接 addSource 会让 MapLibre 渲染出错误覆盖。
 *
 * 契约（与 backend ``overlay_safe_wgs84_bounds`` 对齐）：
 * - 近全球 → [-180, s, 180, n]
 * - 跨日界线：raw west>east 且展开跨度 ≤180° → east∈(180,360]；或后端已展开且 west<east
 * - 拒绝：非有限、纬度越界、经度越界（west∉[-180,180] 或 east∉[-180,360]）、
 *   south>=north、零宽度、误序（展开后跨度>180° 的「东西颠倒」）
 *
 * 注意：不做 lat 对调 / 零宽度 pad —— 那是数据错误，应拒绝而非静默“修好”。
 */
export function validateOverlayBounds(
  raw: unknown,
): { ok: true; bounds: [number, number, number, number] } | { ok: false; reason: string } {
  if (!Array.isArray(raw) || raw.length !== 4) {
    return { ok: false, reason: `bounds 不是 4 元素数组（实际: ${JSON.stringify(raw)}）` }
  }
  const [w0, s0, e0, n0] = raw as number[]
  if (![w0, s0, e0, n0].every(Number.isFinite)) {
    return { ok: false, reason: `bounds 含非有限值: [${w0}, ${s0}, ${e0}, ${n0}]` }
  }
  if (s0 < -90 || s0 > 90 || n0 < -90 || n0 > 90) {
    return { ok: false, reason: `bounds 超出 WGS84 范围: [${w0}, ${s0}, ${e0}, ${n0}]` }
  }
  if (s0 >= n0) {
    return { ok: false, reason: `bounds south >= north: [${w0}, ${s0}, ${e0}, ${n0}]` }
  }
  // west∈[-180,180]；east∈[-180,180]∪(180,360]（已展开日界线条带）
  if (w0 < -180 || w0 > 180 || e0 < -180 || e0 > 360) {
    return { ok: false, reason: `bounds 超出 WGS84 范围: [${w0}, ${s0}, ${e0}, ${n0}]` }
  }
  if (w0 === e0) {
    return { ok: false, reason: `bounds west >= east: [${w0}, ${s0}, ${e0}, ${n0}]` }
  }
  if (w0 > e0) {
    // 日界线条带：仅当展开跨度 ≤180° 才接受（避免把「东西颠倒」误当成跨日界线）
    const span = e0 + 360 - w0
    if (span <= 0 || span > 180) {
      return { ok: false, reason: `bounds west >= east: [${w0}, ${s0}, ${e0}, ${n0}]` }
    }
  }

  try {
    const [w, s, e, n] = overlaySafeWgs84Bounds(w0, s0, e0, n0)
    if (w < -180 || e > 360 || s < -90 || n > 90) {
      return { ok: false, reason: `bounds 超出允许范围: [${w}, ${s}, ${e}, ${n}]` }
    }
    if (w >= e) {
      return { ok: false, reason: `bounds west >= east: [${w}, ${s}, ${e}, ${n}]` }
    }
    if (s >= n) {
      return { ok: false, reason: `bounds south >= north: [${w}, ${s}, ${e}, ${n}]` }
    }
    return { ok: true, bounds: [w, s, e, n] }
  } catch (err) {
    return {
      ok: false,
      reason: err instanceof Error ? err.message : `bounds 规范化失败: ${String(err)}`,
    }
  }
}

export interface OverlayImageModule {
  /**
   * 同步当前 activeLayerIds 与已加载的 overlay 图层（增/删/显隐）。
   *
   * 重要：为避免隐藏/显示时重复 fetch PNG，hidden 图层保留在地图上但 layout.visibility='none'。
   * 仅当图层从 activeOverlayLayerIds 中消失（用户从图层列表移除）时才真正卸载。
   *
   * @param activeOverlayLayerIds 应保持加载的图层（含 hidden 的，即仍在 activeLayers 列表中）
   * @param visibleOverlayLayerIds 应可见的子集（active 中 visible=true 的）
   * @param opacityByLayerId 透明度映射
   */
  syncOverlays: (
    activeOverlayLayerIds: string[],
    visibleOverlayLayerIds: string[],
    opacityByLayerId?: Record<string, number>,
    styleByLayerId?: Record<string, OverlayStyleParams>,
  ) => Promise<void>
  /** 切换时间序列图层的时间标签。若 linkTimeEnabled 为 true，联动其他时间序列图层。 */
  setOverlayTime: (layerId: string, time: string) => Promise<void>
  /** 设置已加载 overlay 的栅格透明度。 */
  setOverlayOpacity: (layerId: string, opacity: number) => void
  /** 应用配色 / 值域 / NaN 样式并刷新 image 或 tiles。 */
  setOverlayStyle: (layerId: string, style: OverlayStyleParams) => void
  /** 设置已加载 overlay 的显隐。 */
  setOverlayVisibility: (layerId: string, visible: boolean) => void
  /** 返回已加载 overlay 的 MapLibre raster layer id（若存在）。 */
  getRasterLayerId: (layerId: string) => string | null
  /** 把动态注册的 overlay id 记入 known 列表（无需整表刷新）。 */
  rememberOverlayId: (layerId: string) => void
  /** 获取所有已加载 overlay 图层的时间状态（用于时间控制 UI）。 */
  overlayTimeStates: import('vue').Ref<OverlayTimeState[]>
  /** 已注册的 overlay 图层 ID 集合（从后端 /overlays 获取）。 */
  knownOverlayIds: import('vue').Ref<string[]>
  /** 初始化：拉取 /overlays 列表。 */
  init: () => Promise<void>
  /** 多图层时间联动开关。 */
  linkTimeEnabled: import('vue').Ref<boolean>
  /** 切换联动开关。 */
  setLinkTime: (enabled: boolean) => void
  /** 卸载时移除所有 overlay 源与图层。 */
  dispose: () => void
}

interface CreateOverlayImageModuleOptions {
  map: MapInstance
  getMapReady: () => boolean
  /** 返回当前 active 且 visible 的图层 catalogId 列表。 */
  getActiveVisibleLayerIds: () => string[]
}

interface LoadedOverlay {
  layerId: string
  sourceId: string
  rasterLayerId: string
  footprintLayerId: string
  footprintSourceId: string
  category: string
  currentTime: string | null
  /** image = overview PNG; raster-xyz = zoom-aware tiles */
  renderMode: 'image' | 'raster-xyz'
  supportsXyzTiles: boolean
  overviewMaxZoom: number
  maxZoom: number
  tileUrlTemplate: string | null
  bounds: [number, number, number, number] | null
  opacity: number
  style: OverlayStyleParams
  styleKey: string
}

/** 有 GeoTIFF 时优先瓦片；-1 表示任意缩放都用 XYZ（避免 overview PNG 放大糊/闪没） */
const DEFAULT_OVERVIEW_MAX_ZOOM = -1
const OVERVIEW_HYSTERESIS = 0.4
const DEFAULT_TILE_MAX_ZOOM = 18

export interface OverlayBoundsMeta {
  currentTime: string | null
  timeList: string[]
  category: 'static' | 'time-series'
  palette?: string
  vmin: number | null
  vmax: number | null
  unit: string
  opacity: number
  supports_recolor: boolean
  supports_xyz_tiles: boolean
  overview_max_zoom: number
  maxzoom: number
  tile_url_template: string | null
}

function _overlayMetaString(value: unknown): string | undefined {
  return typeof value === 'string' ? value : undefined
}

function _overlayMetaFiniteNumber(value: unknown): number | undefined {
  return typeof value === 'number' && Number.isFinite(value) ? value : undefined
}

export function parseOverlayBoundsMeta(raw: unknown): OverlayBoundsMeta {
  const meta = (raw && typeof raw === 'object' ? raw : {}) as Record<string, unknown>
  const currentTime =
    _overlayMetaString(meta.current_time) ?? _overlayMetaString(meta.default_time) ?? null
  const rawTimeList = meta.time_list
  const timeList =
    Array.isArray(rawTimeList) && rawTimeList.every((item) => typeof item === 'string')
      ? rawTimeList
      : []
  const category: 'static' | 'time-series' =
    meta.category === 'time-series' ? 'time-series' : 'static'
  const palette = _overlayMetaString(meta.palette)
  const vmin = _overlayMetaFiniteNumber(meta.vmin) ?? null
  const vmax = _overlayMetaFiniteNumber(meta.vmax) ?? null
  const unit = _overlayMetaString(meta.unit) ?? ''
  const opacity = _overlayMetaFiniteNumber(meta.opacity) ?? 0.7
  const supports_recolor = Boolean(meta.supports_recolor)
  const supports_xyz_tiles = Boolean(meta.supports_xyz_tiles)
  const overview_max_zoom =
    _overlayMetaFiniteNumber(meta.overview_max_zoom) ?? DEFAULT_OVERVIEW_MAX_ZOOM
  const maxzoom = _overlayMetaFiniteNumber(meta.maxzoom) ?? DEFAULT_TILE_MAX_ZOOM
  const rawTemplate = _overlayMetaString(meta.tile_url_template)
  const tile_url_template = rawTemplate && rawTemplate.length > 0 ? rawTemplate : null

  return {
    currentTime,
    timeList,
    category,
    palette,
    vmin,
    vmax,
    unit,
    opacity,
    supports_recolor,
    supports_xyz_tiles,
    overview_max_zoom,
    maxzoom,
    tile_url_template,
  }
}

function styleKeyOf(style: OverlayStyleParams | undefined | null): string {
  if (!style) return ''
  return [
    style.palette ?? '',
    style.vmin ?? '',
    style.vmax ?? '',
    style.nodataMode ?? '',
    style.nodataColor ?? '',
    style.forceStyle ? '1' : '0',
  ].join('|')
}

function _styleQuery(style: OverlayStyleParams | undefined | null, time: string | null): string {
  return buildOverlayStyleQuery({
    time,
    palette: style?.palette,
    vmin: style?.vmin,
    vmax: style?.vmax,
    nodataMode: style?.nodataMode,
    nodataColor: style?.nodataColor,
    forceStyle: Boolean(
      style?.forceStyle || style?.palette || style?.vmin != null || style?.vmax != null,
    ),
  })
}

function _tileUrlFor(
  template: string,
  layerId: string,
  time: string | null,
  style?: OverlayStyleParams | null,
): string {
  const base = template.includes('{z}') ? template : `/overlay-tiles/${layerId}/{z}/{x}/{y}.png`
  const qs = _styleQuery(style, time)
  return `${base}${qs}`
}

function _previewUrl(
  layerId: string,
  time: string | null,
  style?: OverlayStyleParams | null,
): string {
  const qs = _styleQuery(style, time)
  const bust = `_=${Date.now()}`
  if (!qs) return `/overlay-preview/${layerId}?${bust}`
  return `/overlay-preview/${layerId}${qs}&${bust}`
}

export function createOverlayImageModule(
  options: CreateOverlayImageModuleOptions,
): OverlayImageModule {
  const knownOverlayIds = ref<string[]>([])
  const overlayTimeStates = ref<OverlayTimeState[]>([])
  const loadedOverlays = new Map<string, LoadedOverlay>()
  const loadingOverlays = new Set<string>()
  /** 加载过程中用户切换显隐时记住最新意图，避免 hide 被 in-flight load 覆盖 */
  const desiredVisibility = new Map<string, boolean>()
  /** 加载过程中记住最新样式，完成后应用 */
  const desiredStyle = new Map<string, OverlayStyleParams>()
  const linkTimeEnabled = ref(false)
  // bounds 内存缓存：避免显示/隐藏切换时重复请求 /overlay-bounds
  const boundsCache = new Map<
    string,
    { bounds: [number, number, number, number]; meta: OverlayBoundsMeta }
  >()
  /** bounds 404 负缓存：缺资产的注册层（如 aridity-cn）不要反复打 404 */
  const boundsMissCache = new Set<string>()

  function _ids(layerId: string) {
    const safe = layerId.replace(/[^a-zA-Z0-9_-]/g, '-')
    return {
      sourceId: `overlay-src-${safe}`,
      rasterLayerId: `overlay-raster-${safe}`,
      footprintSourceId: `overlay-footprint-src-${safe}`,
      footprintLayerId: `overlay-footprint-${safe}`,
    }
  }

  function _desiredMode(
    zoom: number,
    overviewMaxZoom: number,
    supportsXyz: boolean,
  ): 'image' | 'raster-xyz' {
    if (!supportsXyz) return 'image'
    // hysteresis applied by caller using current mode
    return zoom <= overviewMaxZoom ? 'image' : 'raster-xyz'
  }

  function _modeWithHysteresis(
    zoom: number,
    current: 'image' | 'raster-xyz',
    overviewMaxZoom: number,
    supportsXyz: boolean,
  ): 'image' | 'raster-xyz' {
    if (!supportsXyz) return 'image'
    if (current === 'image') {
      return zoom > overviewMaxZoom + OVERVIEW_HYSTERESIS ? 'raster-xyz' : 'image'
    }
    return zoom < overviewMaxZoom - OVERVIEW_HYSTERESIS ? 'image' : 'raster-xyz'
  }

  function _ensureFootprint(
    layerId: string,
    bounds: [number, number, number, number],
    visible: boolean,
  ) {
    const { footprintSourceId, footprintLayerId } = _ids(layerId)
    const [west, south, east, north] = bounds
    const feature = {
      type: 'Feature' as const,
      properties: {},
      geometry: {
        type: 'Polygon' as const,
        coordinates: [
          [
            [west, south],
            [east, south],
            [east, north],
            [west, north],
            [west, south],
          ],
        ],
      },
    }
    if (!options.map.getSource(footprintSourceId)) {
      options.map.addSource(footprintSourceId, {
        type: 'geojson',
        data: { type: 'FeatureCollection', features: [feature] },
      })
    } else {
      const src = options.map.getSource(footprintSourceId) as {
        setData?: (d: unknown) => void
      }
      src.setData?.({ type: 'FeatureCollection', features: [feature] })
    }
    if (!options.map.getLayer(footprintLayerId)) {
      options.map.addLayer(
        {
          id: footprintLayerId,
          type: 'line',
          source: footprintSourceId,
          layout: { visibility: visible ? 'visible' : 'none' },
          paint: {
            'line-color': 'var(--border-strong)',
            'line-width': 1.25,
            'line-opacity': 0.85,
          },
        },
        options.map.getLayer('admin-fill') ? 'admin-fill' : undefined,
      )
    } else {
      options.map.setLayoutProperty(footprintLayerId, 'visibility', visible ? 'visible' : 'none')
    }
  }

  function _removeOverlayLayers(sourceId: string, rasterLayerId: string) {
    if (options.map.getLayer(rasterLayerId)) {
      options.map.removeLayer(rasterLayerId)
    }
    if (options.map.getSource(sourceId)) {
      options.map.removeSource(sourceId)
    }
  }

  function _boundsToCoordinates(
    bounds: [number, number, number, number],
  ): [[number, number], [number, number], [number, number], [number, number]] {
    const [west, south, east, north] = bounds
    return [
      [west, north],
      [east, north],
      [east, south],
      [west, south],
    ]
  }

  async function _fetchTimedBounds(
    layerId: string,
    time: string | null,
  ): Promise<[number, number, number, number] | null> {
    const cacheKey = time ? `${layerId}@${time}` : layerId
    if (boundsMissCache.has(cacheKey) || boundsMissCache.has(layerId)) return null
    const cached = boundsCache.get(cacheKey)
    if (cached) return cached.bounds
    try {
      const qs = time ? `?time=${encodeURIComponent(time)}` : ''
      const resp = await fetch(`/overlay-bounds/${layerId}${qs}`)
      if (!resp.ok) {
        if (resp.status === 404) boundsMissCache.add(cacheKey)
        return null
      }
      const data = (await resp.json()) as {
        bounds?: [number, number, number, number]
        meta?: Record<string, unknown>
      }
      const validation = validateOverlayBounds(data.bounds)
      if (!validation.ok) {
        console.warn(`[Overlay] timed bounds invalid for ${layerId}@${time}: ${validation.reason}`)
        return null
      }
      boundsCache.set(cacheKey, {
        bounds: validation.bounds,
        meta: parseOverlayBoundsMeta(data.meta),
      })
      return validation.bounds
    } catch (err) {
      console.warn(`[Overlay] timed bounds fetch failed for ${layerId}@${time}`, err)
      return null
    }
  }

  function _applyImageSourceUpdate(
    source: {
      updateImage?: (o: {
        url: string
        coordinates?: [[number, number], [number, number], [number, number], [number, number]]
      }) => void
      setCoordinates?: (
        c: [[number, number], [number, number], [number, number], [number, number]],
      ) => void
      setUrl?: (u: string) => void
    },
    url: string,
    bounds: [number, number, number, number] | null,
  ) {
    const coordinates = bounds ? _boundsToCoordinates(bounds) : undefined
    // MapLibre ImageSource：必须同时更新 url + coordinates，否则换时刻 PNG 地理框不同会南北压缩/偏移
    if (typeof source.updateImage === 'function') {
      source.updateImage(coordinates ? { url, coordinates } : { url })
      return
    }
    if (coordinates && typeof source.setCoordinates === 'function') {
      source.setCoordinates(coordinates)
    }
    if (typeof source.setUrl === 'function') {
      source.setUrl(url)
    }
  }

  async function init() {
    if (knownOverlayIds.value.length > 0) return
    try {
      const resp = await fetch('/overlays')
      if (!resp.ok) return
      const data = await resp.json()
      knownOverlayIds.value = data.overlay_layer_ids ?? []
    } catch (e) {
      console.warn('[Overlay] Failed to fetch /overlays', e)
    }
  }

  function _removeOverlay(layerId: string) {
    const loaded = loadedOverlays.get(layerId)
    if (!loaded) return
    const { sourceId, rasterLayerId, footprintLayerId, footprintSourceId } = loaded
    _removeOverlayLayers(sourceId, rasterLayerId)
    if (options.map.getLayer(footprintLayerId)) {
      options.map.removeLayer(footprintLayerId)
    }
    if (options.map.getSource(footprintSourceId)) {
      options.map.removeSource(footprintSourceId)
    }
    loadedOverlays.delete(layerId)
    desiredVisibility.delete(layerId)
    overlayTimeStates.value = overlayTimeStates.value.filter((s) => s.layerId !== layerId)
  }

  function _addImageSource(
    sourceId: string,
    url: string,
    bounds: [number, number, number, number],
  ) {
    options.map.addSource(sourceId, {
      type: 'image',
      url,
      coordinates: [
        [bounds[0], bounds[3]],
        [bounds[2], bounds[3]],
        [bounds[2], bounds[1]],
        [bounds[0], bounds[1]],
      ],
    } as ImageSourceSpecification)
  }

  function _addXyzSource(sourceId: string, tileTemplate: string, maxZoom = DEFAULT_TILE_MAX_ZOOM) {
    options.map.addSource(sourceId, {
      type: 'raster',
      tiles: [tileTemplate],
      tileSize: 256,
      minzoom: 0,
      maxzoom: Math.max(0, Math.min(22, Math.floor(maxZoom))),
      // 允许 MapLibre 在 source maxzoom 之上继续显示（overzoom），避免「再放大就没了」
    })
  }

  function _addRasterLayer(
    rasterLayerId: string,
    sourceId: string,
    opacity: number,
    visible: boolean,
  ) {
    options.map.addLayer(
      {
        id: rasterLayerId,
        type: 'raster',
        source: sourceId,
        layout: { visibility: visible ? 'visible' : 'none' },
        paint: {
          'raster-opacity': opacity,
          'raster-fade-duration': 0,
          // 科学栅格放大时用最近邻，避免双线性糊成一片
          'raster-resampling': 'nearest',
        },
      },
      options.map.getLayer('admin-fill') ? 'admin-fill' : undefined,
    )
  }

  async function _switchRenderMode(loaded: LoadedOverlay, mode: 'image' | 'raster-xyz') {
    if (loaded.renderMode === mode) return
    const { layerId } = loaded
    const visible = desiredVisibility.get(layerId) ?? true
    const { sourceId, rasterLayerId } = _ids(layerId)
    // 清掉旧层与可能残留的 staging
    _removeOverlayLayers(`${sourceId}__stg`, `${rasterLayerId}__stg`)
    _removeOverlayLayers(loaded.sourceId, loaded.rasterLayerId)
    if (loaded.sourceId !== sourceId) {
      _removeOverlayLayers(sourceId, rasterLayerId)
    }

    if (mode === 'raster-xyz' && loaded.tileUrlTemplate) {
      _addXyzSource(
        sourceId,
        _tileUrlFor(loaded.tileUrlTemplate, layerId, loaded.currentTime, loaded.style),
        loaded.maxZoom,
      )
    } else if (loaded.bounds) {
      const url = _previewUrl(layerId, loaded.currentTime, loaded.style)
      _addImageSource(sourceId, url, loaded.bounds)
    } else {
      return
    }
    _addRasterLayer(rasterLayerId, sourceId, loaded.opacity, visible)
    loaded.sourceId = sourceId
    loaded.rasterLayerId = rasterLayerId
    loaded.renderMode = mode
    if (loaded.bounds) {
      _ensureFootprint(layerId, loaded.bounds, visible && mode === 'image')
    }
  }

  function _syncModesForZoom() {
    if (!options.getMapReady()) return
    const zoom = options.map.getZoom()
    for (const loaded of loadedOverlays.values()) {
      const next = _modeWithHysteresis(
        zoom,
        loaded.renderMode,
        loaded.overviewMaxZoom,
        loaded.supportsXyzTiles,
      )
      if (next !== loaded.renderMode) {
        void _switchRenderMode(loaded, next)
      }
    }
  }

  let globalOverviewFitScheduled = false

  function _fitBoundsIfOutside(bounds: [number, number, number, number]) {
    try {
      const center = options.map.getCenter()
      const zoom = options.map.getZoom()
      const [west, south, east, north] = bounds
      const lngSpan = east - west
      const isNearGlobal = lngSpan >= 300

      // 近全球稀疏结果（如 FY/SMAP 轨道条带）在区域级缩放下可能整个视口均为透明瓦片。
      // 即使当前中心位于全球 bounds 内，也应在首次加载时拉回全球概览，确保用户能看到数据。
      if (isNearGlobal && zoom > 3 && !globalOverviewFitScheduled) {
        globalOverviewFitScheduled = true
        options.map.fitBounds(
          [
            [west, south],
            [east, north],
          ],
          { padding: 60, duration: 800, essential: true },
        )
        return
      }

      if (center.lat >= south && center.lat <= north) {
        if (east <= 180) {
          if (center.lng >= west && center.lng <= east) return
        } else {
          // east∈(180,360]：把中心经度展开到与 bounds 同一连续轴再判断
          let lng = center.lng
          if (lng < west) lng += 360
          if (lng >= west && lng <= east) return
        }
      }
      options.map.fitBounds(
        [
          [west, south],
          [east, north],
        ],
        { padding: 60, duration: 800, essential: true },
      )
    } catch {
      // 地图状态不可用时静默忽略
    }
  }

  async function _addOverlay(
    layerId: string,
    initialOpacity?: number,
    initiallyVisible: boolean = true,
    initialStyle?: OverlayStyleParams,
  ): Promise<void> {
    desiredVisibility.set(layerId, initiallyVisible)
    if (initialStyle) desiredStyle.set(layerId, initialStyle)
    if (loadedOverlays.has(layerId)) {
      setOverlayVisibility(layerId, desiredVisibility.get(layerId) ?? initiallyVisible)
      const style = desiredStyle.get(layerId)
      if (style) setOverlayStyle(layerId, style)
      return
    }
    if (loadingOverlays.has(layerId)) {
      // 已有加载在飞：只更新 desiredVisibility / style，完成后应用
      return
    }
    if (boundsMissCache.has(layerId)) return
    const { sourceId } = _ids(layerId)
    if (options.map.getSource(sourceId)) return
    loadingOverlays.add(layerId)

    try {
      // 先取根 meta（time_list），时间序列再按 default_time 取与预览一致的地理框
      const rootResp = await fetch(`/overlay-bounds/${layerId}`)
      if (!rootResp.ok) {
        if (rootResp.status === 404) boundsMissCache.add(layerId)
        console.warn(`[Overlay] bounds fetch failed for ${layerId}: ${rootResp.status}`)
        return
      }
      const rootData = (await rootResp.json()) as {
        bounds: [number, number, number, number]
        meta?: Record<string, unknown>
      }
      const meta = parseOverlayBoundsMeta(rootData.meta)
      const currentTime = meta.currentTime
      const timeList = meta.timeList
      const category = meta.category

      let boundsData = rootData
      if (category === 'time-series' && currentTime) {
        const timed = await _fetchTimedBounds(layerId, currentTime)
        if (timed) {
          boundsData = { bounds: timed, meta: rootData.meta }
          boundsCache.set(`${layerId}@${currentTime}`, { bounds: timed, meta })
        }
      } else {
        boundsCache.set(layerId, { bounds: rootData.bounds, meta })
      }

      const boundsValidation = validateOverlayBounds(boundsData.bounds)
      if (!boundsValidation.ok) {
        console.warn(`[Overlay] Invalid bounds for ${layerId}: ${boundsValidation.reason}`)
        showToast(`栅格无法显示：${boundsValidation.reason}。请确认坐标系或重新导入。`, true, 6500)
        return
      }
      const bounds: [number, number, number, number] = boundsValidation.bounds
      // 写回共享 symbology store（含 bounds 内存缓存命中路径）
      try {
        const { useOverlaySymbologyStore } = await import('../../stores/overlay-symbology')
        useOverlaySymbologyStore().putMeta(layerId, {
          palette: meta.palette,
          vmin: meta.vmin,
          vmax: meta.vmax,
          unit: meta.unit,
          opacity: typeof initialOpacity === 'number' ? initialOpacity : meta.opacity,
          supports_recolor: meta.supports_recolor,
        })
      } catch {
        // Pinia 未就绪时忽略
      }
      const opacity =
        typeof initialOpacity === 'number' ? Math.max(0, Math.min(1, initialOpacity)) : meta.opacity

      const style: OverlayStyleParams = {
        ...(desiredStyle.get(layerId) ?? initialStyle ?? {}),
      }
      // 有源可重着色：默认带上注册 palette，便于服务端动态着色与后续覆盖一致
      if (meta.supports_recolor && !style.palette && meta.palette) {
        style.palette = meta.palette
        style.forceStyle = true
      }
      if (style.vmin == null && meta.vmin != null) style.vmin = meta.vmin
      if (style.vmax == null && meta.vmax != null) style.vmax = meta.vmax

      const url = _previewUrl(layerId, currentTime, style)

      const supportsXyzTiles = meta.supports_xyz_tiles
      const overviewMaxZoom = meta.overview_max_zoom
      const maxZoom = meta.maxzoom
      const tileUrlTemplate = meta.tile_url_template ?? `/overlay-tiles/${layerId}/{z}/{x}/{y}.png`

      const zoom = options.map.getZoom()
      const renderMode = _desiredMode(zoom, overviewMaxZoom, supportsXyzTiles)
      const { sourceId, rasterLayerId, footprintSourceId, footprintLayerId } = _ids(layerId)

      if (renderMode === 'raster-xyz' && supportsXyzTiles) {
        _addXyzSource(sourceId, _tileUrlFor(tileUrlTemplate, layerId, currentTime, style), maxZoom)
      } else {
        _addImageSource(sourceId, url, bounds)
      }

      const visibleNow = desiredVisibility.get(layerId) ?? initiallyVisible
      _addRasterLayer(rasterLayerId, sourceId, opacity, visibleNow)
      _ensureFootprint(layerId, bounds, visibleNow && renderMode === 'image')

      loadedOverlays.set(layerId, {
        layerId,
        sourceId,
        rasterLayerId,
        footprintLayerId,
        footprintSourceId,
        category,
        currentTime,
        renderMode,
        supportsXyzTiles,
        overviewMaxZoom,
        maxZoom,
        tileUrlTemplate: supportsXyzTiles ? tileUrlTemplate : null,
        bounds,
        opacity,
        style,
        styleKey: styleKeyOf(style),
      })

      // 更新时间状态
      const state: OverlayTimeState = {
        layerId,
        category,
        timeList,
        currentTime,
        palette: meta.palette ?? 'viridis',
        unit: meta.unit,
        vmin: meta.vmin,
        vmax: meta.vmax,
        opacity,
        bounds,
      }
      overlayTimeStates.value = [...overlayTimeStates.value, state]

      // 自动 fitBounds：若当前地图中心不在 overlay 范围内，则飞到该图层范围
      if (visibleNow) {
        _fitBoundsIfOutside(bounds)
      }
    } catch (e) {
      console.warn(`[Overlay] Failed to load overlay for ${layerId}`, e)
    } finally {
      loadingOverlays.delete(layerId)
      // 加载完成后再次对齐最新显隐意图（可能在加载期间被用户切换）
      const want = desiredVisibility.get(layerId)
      if (want !== undefined && loadedOverlays.has(layerId)) {
        setOverlayVisibility(layerId, want)
      }
    }
  }

  async function syncOverlays(
    activeOverlayLayerIds: string[],
    visibleOverlayLayerIds: string[],
    opacityByLayerId?: Record<string, number>,
    styleByLayerId?: Record<string, OverlayStyleParams>,
  ): Promise<void> {
    if (!options.getMapReady()) return

    const visibleSet = new Set(visibleOverlayLayerIds)

    // 1) 移除真正从 activeLayers 列表消失的图层（用户删除图层）
    for (const layerId of Array.from(loadedOverlays.keys())) {
      if (!activeOverlayLayerIds.includes(layerId)) {
        _removeOverlay(layerId)
      }
    }

    // 2) 添加新 active 的图层（首次加载）；对已加载的仅切换 visibility / opacity / style
    const newLayerIds: string[] = []
    for (const layerId of activeOverlayLayerIds) {
      if (styleByLayerId?.[layerId]) desiredStyle.set(layerId, styleByLayerId[layerId])
      if (!loadedOverlays.has(layerId)) {
        newLayerIds.push(layerId)
      } else {
        setOverlayVisibility(layerId, visibleSet.has(layerId))
        if (typeof opacityByLayerId?.[layerId] === 'number') {
          setOverlayOpacity(layerId, opacityByLayerId[layerId])
        }
        if (styleByLayerId?.[layerId]) {
          setOverlayStyle(layerId, styleByLayerId[layerId])
        }
      }
    }
    if (newLayerIds.length > 0) {
      await Promise.all(
        newLayerIds.map((layerId) =>
          _addOverlay(
            layerId,
            opacityByLayerId?.[layerId],
            visibleSet.has(layerId),
            styleByLayerId?.[layerId],
          ),
        ),
      )
    }
  }

  function setLinkTime(enabled: boolean) {
    linkTimeEnabled.value = enabled
  }

  function _findNearestTime(timeList: string[], target: string): string | null {
    if (timeList.length === 0) return null
    if (timeList.includes(target)) return target
    // 按字符串排序找最接近的（YYYYMMDD/YYYYMM 字典序与时间序一致）
    let nearest = timeList[0]
    let minDiff = Math.abs(timeList[0].localeCompare(target))
    for (const t of timeList) {
      const diff = Math.abs(t.localeCompare(target))
      if (diff < minDiff) {
        minDiff = diff
        nearest = t
      }
    }
    return nearest
  }

  async function setOverlayTime(layerId: string, time: string): Promise<void> {
    const loaded = loadedOverlays.get(layerId)
    if (!loaded) return
    if (loaded.category !== 'time-series') return

    const timedBounds = await _fetchTimedBounds(layerId, time)
    if (!timedBounds) {
      // 时间块被服务端过滤/重建后，旧标签可能不再可用。自动切回当前可用默认块，
      // 避免时间轴从6块收敛为5块后图层因 404 消失。
      const state = overlayTimeStates.value.find((s) => s.layerId === layerId)
      const fallback =
        state?.timeList?.find((t) => t === state.currentTime) ?? state?.timeList?.at(-1)
      if (fallback && fallback !== time) {
        await setOverlayTime(layerId, fallback)
      }
      return
    }
    loaded.bounds = timedBounds

    if (loaded.renderMode === 'raster-xyz' && loaded.tileUrlTemplate) {
      // Rebuild raster source so MapLibre refetches tiles for the new time
      const { sourceId, rasterLayerId } = loaded
      const visible = desiredVisibility.get(layerId) ?? true
      _removeOverlayLayers(sourceId, rasterLayerId)
      _addXyzSource(
        sourceId,
        _tileUrlFor(loaded.tileUrlTemplate, layerId, time, loaded.style),
        loaded.maxZoom,
      )
      _addRasterLayer(rasterLayerId, sourceId, loaded.opacity, visible)
    } else {
      const source = options.map.getSource(loaded.sourceId) as
        | {
            updateImage?: (o: {
              url: string
              coordinates?: [[number, number], [number, number], [number, number], [number, number]]
            }) => void
            setCoordinates?: (
              c: [[number, number], [number, number], [number, number], [number, number]],
            ) => void
            setUrl?: (u: string) => void
          }
        | undefined
      if (!source) return
      const newUrl = _previewUrl(layerId, time, loaded.style)
      _applyImageSourceUpdate(source, newUrl, timedBounds)
    }

    loaded.currentTime = time
    overlayTimeStates.value = overlayTimeStates.value.map((s) =>
      s.layerId === layerId ? { ...s, currentTime: time, bounds: timedBounds ?? s.bounds } : s,
    )
    if (loaded.bounds) {
      _ensureFootprint(
        layerId,
        loaded.bounds,
        (desiredVisibility.get(layerId) ?? true) && loaded.renderMode === 'image',
      )
    }

    // 联动其他时间序列图层（关闭本层联动标志避免递归）
    if (linkTimeEnabled.value) {
      const others = overlayTimeStates.value.filter(
        (s) => s.layerId !== layerId && s.category === 'time-series' && s.currentTime !== time,
      )
      if (others.length) {
        linkTimeEnabled.value = false
        try {
          for (const other of others) {
            const nearest = _findNearestTime(other.timeList, time)
            if (nearest && nearest !== other.currentTime) {
              await setOverlayTime(other.layerId, nearest)
            }
          }
        } finally {
          linkTimeEnabled.value = true
        }
      }
    }
  }

  function rememberOverlayId(layerId: string) {
    if (!knownOverlayIds.value.includes(layerId)) {
      knownOverlayIds.value = [...knownOverlayIds.value, layerId]
    }
  }

  function setOverlayStyle(layerId: string, style: OverlayStyleParams) {
    desiredStyle.set(layerId, style)
    const loaded = loadedOverlays.get(layerId)
    if (!loaded) return
    const nextKey = styleKeyOf(style)
    if (nextKey === loaded.styleKey) return
    loaded.style = { ...style }
    loaded.styleKey = nextKey

    if (loaded.renderMode === 'raster-xyz' && loaded.tileUrlTemplate) {
      const { sourceId, rasterLayerId } = loaded
      const visible = desiredVisibility.get(layerId) ?? true
      _removeOverlayLayers(sourceId, rasterLayerId)
      _addXyzSource(
        sourceId,
        _tileUrlFor(loaded.tileUrlTemplate, layerId, loaded.currentTime, loaded.style),
        loaded.maxZoom,
      )
      _addRasterLayer(rasterLayerId, sourceId, loaded.opacity, visible)
      return
    }

    const source = options.map.getSource(loaded.sourceId) as
      | {
          updateImage?: (o: {
            url: string
            coordinates?: [[number, number], [number, number], [number, number], [number, number]]
          }) => void
          setUrl?: (u: string) => void
        }
      | undefined
    if (!source || !loaded.bounds) return
    _applyImageSourceUpdate(
      source,
      _previewUrl(layerId, loaded.currentTime, loaded.style),
      loaded.bounds,
    )
  }

  function setOverlayOpacity(layerId: string, opacity: number) {
    const loaded = loadedOverlays.get(layerId)
    if (!loaded) return
    if (!options.map.getLayer(loaded.rasterLayerId)) return
    const clamped = Math.max(0, Math.min(1, opacity))
    loaded.opacity = clamped
    options.map.setPaintProperty(loaded.rasterLayerId, 'raster-opacity', clamped)
    overlayTimeStates.value = overlayTimeStates.value.map((s) =>
      s.layerId === layerId ? { ...s, opacity: clamped } : s,
    )
  }

  function setOverlayVisibility(layerId: string, visible: boolean) {
    desiredVisibility.set(layerId, visible)
    const loaded = loadedOverlays.get(layerId)
    if (!loaded) return
    if (options.map.getLayer(loaded.rasterLayerId)) {
      options.map.setLayoutProperty(
        loaded.rasterLayerId,
        'visibility',
        visible ? 'visible' : 'none',
      )
    }
    if (options.map.getLayer(loaded.footprintLayerId)) {
      options.map.setLayoutProperty(
        loaded.footprintLayerId,
        'visibility',
        visible && loaded.renderMode === 'image' ? 'visible' : 'none',
      )
    }
  }

  function getRasterLayerId(layerId: string): string | null {
    const loaded = loadedOverlays.get(layerId)
    if (!loaded) return null
    return options.map.getLayer(loaded.rasterLayerId) ? loaded.rasterLayerId : null
  }

  function dispose() {
    options.map.off('zoomend', _syncModesForZoom)
    options.map.off('moveend', _syncModesForZoom)
    options.map.off('zoom', _onZoomDuringGesture)
    if (zoomSyncTimer != null) {
      window.clearTimeout(zoomSyncTimer)
      zoomSyncTimer = null
    }
    for (const layerId of Array.from(loadedOverlays.keys())) {
      _removeOverlay(layerId)
    }
    loadingOverlays.clear()
    desiredVisibility.clear()
    desiredStyle.clear()
    boundsCache.clear()
    knownOverlayIds.value = []
    overlayTimeStates.value = []
    linkTimeEnabled.value = false
  }

  let zoomSyncTimer: ReturnType<typeof setTimeout> | null = null
  function _onZoomDuringGesture() {
    if (zoomSyncTimer != null) return
    zoomSyncTimer = setTimeout(() => {
      zoomSyncTimer = null
      _syncModesForZoom()
    }, 120)
  }

  options.map.on('zoomend', _syncModesForZoom)
  options.map.on('moveend', _syncModesForZoom)
  options.map.on('zoom', _onZoomDuringGesture)

  return {
    syncOverlays,
    setOverlayTime,
    setOverlayOpacity,
    setOverlayStyle,
    setOverlayVisibility,
    getRasterLayerId,
    rememberOverlayId,
    overlayTimeStates,
    knownOverlayIds,
    init,
    linkTimeEnabled,
    setLinkTime,
    dispose,
  }
}
