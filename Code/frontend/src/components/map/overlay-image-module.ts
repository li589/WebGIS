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

export interface OverlayImageModule {
  /** 同步当前 activeLayerIds 与已加载的 overlay 图层（增/删）。 */
  syncOverlays: (activeOverlayLayerIds: string[]) => Promise<void>
  /** 切换时间序列图层的时间标签。若 linkTimeEnabled 为 true，联动其他时间序列图层。 */
  setOverlayTime: (layerId: string, time: string) => Promise<void>
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

  async function _addOverlay(layerId: string): Promise<void> {
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
      const bounds: [number, number, number, number] = boundsData.bounds
      const meta = boundsData.meta ?? {}
      const currentTime: string | null = meta.current_time ?? meta.default_time ?? null
      const timeList: string[] = meta.time_list ?? []
      const category: string = meta.category ?? 'static'

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
        layout: { visibility: 'visible' },
        paint: {
          'raster-opacity': meta.opacity ?? 0.7,
          'raster-fade-duration': 300,
        },
      })

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
        opacity: meta.opacity ?? 0.7,
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

  async function syncOverlays(activeOverlayLayerIds: string[]): Promise<void> {
    if (!options.getMapReady()) return

    // 移除不再 active 的
    for (const layerId of Array.from(loadedOverlays.keys())) {
      if (!activeOverlayLayerIds.includes(layerId)) {
        _removeOverlay(layerId)
      }
    }
    // 添加新 active 的
    for (const layerId of activeOverlayLayerIds) {
      if (!loadedOverlays.has(layerId)) {
        await _addOverlay(layerId)
      }
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

  return {
    syncOverlays,
    setOverlayTime,
    overlayTimeStates,
    knownOverlayIds,
    init,
    linkTimeEnabled,
    setLinkTime,
  }
}
