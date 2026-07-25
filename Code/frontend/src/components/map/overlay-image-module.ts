import { ref } from 'vue'
import { showToast } from '../../data-manager/core/workspace-store'
import { overlaySafeWgs84Bounds } from '../../services/geo-math'

type MapInstance = import('maplibre-gl').Map

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
  ) => Promise<void>
  /** 切换时间序列图层的时间标签。若 linkTimeEnabled 为 true，联动其他时间序列图层。 */
  setOverlayTime: (layerId: string, time: string) => Promise<void>
  /** 设置已加载 overlay 的栅格透明度。 */
  setOverlayOpacity: (layerId: string, opacity: number) => void
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
  category: string
  currentTime: string | null
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
  const linkTimeEnabled = ref(false)
  // bounds 内存缓存：避免显示/隐藏切换时重复请求 /overlay-bounds
  const boundsCache = new Map<string, { bounds: [number, number, number, number]; meta: any }>()

  function _ids(layerId: string) {
    const safe = layerId.replace(/[^a-zA-Z0-9_-]/g, '-')
    return {
      sourceId: `overlay-src-${safe}`,
      rasterLayerId: `overlay-raster-${safe}`,
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
    const { sourceId, rasterLayerId } = loaded
    if (options.map.getLayer(rasterLayerId)) {
      options.map.removeLayer(rasterLayerId)
    }
    if (options.map.getSource(sourceId)) {
      options.map.removeSource(sourceId)
    }
    loadedOverlays.delete(layerId)
    desiredVisibility.delete(layerId)
    // 移除时间状态
    overlayTimeStates.value = overlayTimeStates.value.filter((s) => s.layerId !== layerId)
  }

  function _fitBoundsIfOutside(bounds: [number, number, number, number]) {
    try {
      const center = options.map.getCenter()
      const [west, south, east, north] = bounds
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
  ): Promise<void> {
    desiredVisibility.set(layerId, initiallyVisible)
    if (loadedOverlays.has(layerId)) {
      setOverlayVisibility(layerId, desiredVisibility.get(layerId) ?? initiallyVisible)
      return
    }
    if (loadingOverlays.has(layerId)) {
      // 已有加载在飞：只更新 desiredVisibility，完成后应用
      return
    }
    const { sourceId, rasterLayerId } = _ids(layerId)
    if (options.map.getSource(sourceId)) return
    loadingOverlays.add(layerId)

    try {
      let boundsData: { bounds: [number, number, number, number]; meta: any }
      const cached = boundsCache.get(layerId)
      if (cached) {
        boundsData = cached
      } else {
        const boundsResp = await fetch(`/overlay-bounds/${layerId}`)
        if (!boundsResp.ok) {
          console.warn(`[Overlay] bounds fetch failed for ${layerId}: ${boundsResp.status}`)
          return
        }
        boundsData = await boundsResp.json()
        boundsCache.set(layerId, { bounds: boundsData.bounds, meta: boundsData.meta ?? {} })
      }
      const boundsValidation = validateOverlayBounds(boundsData.bounds)
      if (!boundsValidation.ok) {
        console.warn(`[Overlay] Invalid bounds for ${layerId}: ${boundsValidation.reason}`)
        showToast(`栅格无法显示：${boundsValidation.reason}。请确认坐标系或重新导入。`, true, 6500)
        return
      }
      const bounds: [number, number, number, number] = boundsValidation.bounds
      const meta = boundsData.meta ?? {}
      // 写回共享 symbology store（含 bounds 内存缓存命中路径）
      try {
        const { useOverlaySymbologyStore } = await import('../../stores/overlay-symbology')
        useOverlaySymbologyStore().putMeta(layerId, {
          palette: meta.palette,
          vmin: meta.vmin ?? null,
          vmax: meta.vmax ?? null,
          unit: meta.unit,
          opacity: typeof initialOpacity === 'number' ? initialOpacity : meta.opacity,
        })
      } catch {
        // Pinia 未就绪时忽略
      }
      const currentTime: string | null = meta.current_time ?? meta.default_time ?? null
      const timeList: string[] = meta.time_list ?? []
      const category: string = meta.category ?? 'static'
      const opacity =
        typeof initialOpacity === 'number'
          ? Math.max(0, Math.min(1, initialOpacity))
          : (meta.opacity ?? 0.7)

      const url =
        category === 'time-series' && currentTime
          ? `/overlay-preview/${layerId}?time=${currentTime}`
          : `/overlay-preview/${layerId}`

      options.map.addSource(sourceId, {
        type: 'image',
        url,
        coordinates: [
          [bounds[0], bounds[3]], // 左上 (west, north)
          [bounds[2], bounds[3]], // 右上 (east, north)
          [bounds[2], bounds[1]], // 右下 (east, south)
          [bounds[0], bounds[1]], // 左下 (west, south)
        ],
      } as any)

      const visibleNow = desiredVisibility.get(layerId) ?? initiallyVisible
      options.map.addLayer(
        {
          id: rasterLayerId,
          type: 'raster',
          source: sourceId,
          // 隐藏的图层以 visibility='none' 加入，避免显示时再触发 addLayer 流程
          layout: { visibility: visibleNow ? 'visible' : 'none' },
          paint: {
            'raster-opacity': opacity,
            // 降低 fade duration 让显隐切换更跟手（原 300ms 显得迟钝）
            'raster-fade-duration': 100,
          },
        },
        options.map.getLayer('admin-fill') ? 'admin-fill' : undefined,
      )

      loadedOverlays.set(layerId, {
        layerId,
        sourceId,
        rasterLayerId,
        category,
        currentTime,
      })

      // 更新时间状态
      const state: OverlayTimeState = {
        layerId,
        category: category as 'static' | 'time-series',
        timeList,
        currentTime,
        palette: meta.palette ?? 'viridis',
        unit: meta.unit ?? '',
        vmin: meta.vmin ?? null,
        vmax: meta.vmax ?? null,
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
  ): Promise<void> {
    if (!options.getMapReady()) return

    const visibleSet = new Set(visibleOverlayLayerIds)

    // 1) 移除真正从 activeLayers 列表消失的图层（用户删除图层）
    for (const layerId of Array.from(loadedOverlays.keys())) {
      if (!activeOverlayLayerIds.includes(layerId)) {
        _removeOverlay(layerId)
      }
    }

    // 2) 添加新 active 的图层（首次加载）；对已加载的仅切换 visibility，避免重复 fetch PNG
    //    并行加载多个新图层，缩短多图层同时显示时的等待
    const newLayerIds: string[] = []
    for (const layerId of activeOverlayLayerIds) {
      if (!loadedOverlays.has(layerId)) {
        newLayerIds.push(layerId)
      } else {
        // 已加载：仅切 visibility + opacity，不重新 fetch
        setOverlayVisibility(layerId, visibleSet.has(layerId))
        if (typeof opacityByLayerId?.[layerId] === 'number') {
          setOverlayOpacity(layerId, opacityByLayerId[layerId])
        }
      }
    }
    if (newLayerIds.length > 0) {
      await Promise.all(
        newLayerIds.map((layerId) =>
          _addOverlay(layerId, opacityByLayerId?.[layerId], visibleSet.has(layerId)),
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

    const source = options.map.getSource(loaded.sourceId) as any
    if (!source) return

    const newUrl = `/overlay-preview/${layerId}?time=${time}`
    // MapLibre image source 支持 setUrl
    source.setUrl(newUrl)

    loaded.currentTime = time
    // 更新时间状态
    overlayTimeStates.value = overlayTimeStates.value.map((s) =>
      s.layerId === layerId ? { ...s, currentTime: time } : s,
    )

    // 联动其他时间序列图层
    if (linkTimeEnabled.value) {
      const others = overlayTimeStates.value.filter(
        (s) => s.layerId !== layerId && s.category === 'time-series' && s.currentTime !== time,
      )
      for (const other of others) {
        const nearest = _findNearestTime(other.timeList, time)
        if (nearest && nearest !== other.currentTime) {
          // 递归调用但禁止再次联动（避免循环）
          const otherLoaded = loadedOverlays.get(other.layerId)
          if (!otherLoaded) continue
          const otherSource = options.map.getSource(otherLoaded.sourceId) as any
          if (!otherSource) continue
          const otherUrl = `/overlay-preview/${other.layerId}?time=${nearest}`
          otherSource.setUrl(otherUrl)
          otherLoaded.currentTime = nearest
        }
      }
      // 统一更新时间状态
      overlayTimeStates.value = overlayTimeStates.value.map((s) => {
        if (s.layerId === layerId || s.category !== 'time-series') return s
        const nearest = _findNearestTime(s.timeList, time)
        return nearest && nearest !== s.currentTime ? { ...s, currentTime: nearest } : s
      })
    }
  }

  function rememberOverlayId(layerId: string) {
    if (!knownOverlayIds.value.includes(layerId)) {
      knownOverlayIds.value = [...knownOverlayIds.value, layerId]
    }
  }

  function setOverlayOpacity(layerId: string, opacity: number) {
    const loaded = loadedOverlays.get(layerId)
    if (!loaded) return
    if (!options.map.getLayer(loaded.rasterLayerId)) return
    const clamped = Math.max(0, Math.min(1, opacity))
    options.map.setPaintProperty(loaded.rasterLayerId, 'raster-opacity', clamped)
    overlayTimeStates.value = overlayTimeStates.value.map((s) =>
      s.layerId === layerId ? { ...s, opacity: clamped } : s,
    )
  }

  function setOverlayVisibility(layerId: string, visible: boolean) {
    desiredVisibility.set(layerId, visible)
    const loaded = loadedOverlays.get(layerId)
    if (!loaded) return
    if (!options.map.getLayer(loaded.rasterLayerId)) return
    options.map.setLayoutProperty(loaded.rasterLayerId, 'visibility', visible ? 'visible' : 'none')
  }

  function getRasterLayerId(layerId: string): string | null {
    const loaded = loadedOverlays.get(layerId)
    if (!loaded) return null
    return options.map.getLayer(loaded.rasterLayerId) ? loaded.rasterLayerId : null
  }

  function dispose() {
    for (const layerId of Array.from(loadedOverlays.keys())) {
      _removeOverlay(layerId)
    }
    loadingOverlays.clear()
    desiredVisibility.clear()
    boundsCache.clear()
    knownOverlayIds.value = []
    overlayTimeStates.value = []
    linkTimeEnabled.value = false
  }

  return {
    syncOverlays,
    setOverlayTime,
    setOverlayOpacity,
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
