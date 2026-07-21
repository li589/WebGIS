import { ref } from 'vue'

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
 * 顺序错乱等异常 bounds。直接 addSource 会让 MapLibre 渲染出错误覆盖
 * （或北极/太平洋上的鬼影），并在 console 留下晦涩错误。这里集中拦截，
 * 返回带原因的失败结果，便于上层日志定位。
 *
 * 导出为顶级函数以便单元测试覆盖各异常分支。
 *
 * 注意：image source 的 4 个角点不支持真正"跨子午线"渲染（如 `[170,..,-170,..]`），
 * 但这种情况会被下面的 `w >= e` 检查拦截。`[-180,..,180,..]`（全球）和
 * `[-100,..,100,..]`（宽 200°）都能正常渲染为单张拉伸图片，故不限制东西跨度。
 */
export function validateOverlayBounds(raw: unknown):
  | { ok: true; bounds: [number, number, number, number] }
  | { ok: false; reason: string } {
  if (!Array.isArray(raw) || raw.length !== 4) {
    return { ok: false, reason: `bounds 不是 4 元素数组（实际: ${JSON.stringify(raw)}）` }
  }
  const [w, s, e, n] = raw as number[]
  if (![w, s, e, n].every(Number.isFinite)) {
    return { ok: false, reason: `bounds 含非有限值: [${w}, ${s}, ${e}, ${n}]` }
  }
  // WGS84 经纬度范围（overlay 渲染坐标空间）
  if (w < -180 || e > 180 || s < -90 || n > 90) {
    return { ok: false, reason: `bounds 超出 WGS84 范围: [${w}, ${s}, ${e}, ${n}]` }
  }
  if (w >= e) {
    return { ok: false, reason: `bounds west >= east: [${w}, ${s}, ${e}, ${n}]` }
  }
  if (s >= n) {
    return { ok: false, reason: `bounds south >= north: [${w}, ${s}, ${e}, ${n}]` }
  }
  return { ok: true, bounds: [w, s, e, n] }
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
    // 移除时间状态
    overlayTimeStates.value = overlayTimeStates.value.filter(
      (s) => s.layerId !== layerId,
    )
  }

  function _fitBoundsIfOutside(bounds: [number, number, number, number]) {
    try {
      const center = options.map.getCenter()
      const [west, south, east, north] = bounds
      const inside =
        center.lng >= west && center.lng <= east &&
        center.lat >= south && center.lat <= north
      if (inside) return
      options.map.fitBounds(
        [[west, south], [east, north]],
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
    if (loadedOverlays.has(layerId)) return
    if (loadingOverlays.has(layerId)) return
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
      const opacity = typeof initialOpacity === 'number'
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

      options.map.addLayer({
        id: rasterLayerId,
        type: 'raster',
        source: sourceId,
        // 隐藏的图层以 visibility='none' 加入，避免显示时再触发 addLayer 流程
        layout: { visibility: initiallyVisible ? 'visible' : 'none' },
        paint: {
          'raster-opacity': opacity,
          // 降低 fade duration 让显隐切换更跟手（原 300ms 显得迟钝）
          'raster-fade-duration': 100,
        },
      }, options.map.getLayer('admin-fill') ? 'admin-fill' : undefined)

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
      _fitBoundsIfOutside(bounds)
    } catch (e) {
      console.warn(`[Overlay] Failed to load overlay for ${layerId}`, e)
    } finally {
      loadingOverlays.delete(layerId)
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
          _addOverlay(
            layerId,
            opacityByLayerId?.[layerId],
            visibleSet.has(layerId),
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
