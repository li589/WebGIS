import { computed, ref, watch } from 'vue'
import { defineStore } from 'pinia'

import type { TileSourceId } from '../services/api-config'
import { getDefaultTileSource, normalizeTileSourceId } from '../services/api-config'
import {
  CLOCK_DAY_MAX_HOUR,
  formatClockHourLabel,
  quantizeClockHour,
} from '../utils/weather-timeline'
import {
  DEFAULT_PLAY_INTERVAL_MS,
  loadPlayIntervalMs,
  persistPlayIntervalMs,
  isValidPlayIntervalMs,
} from '../utils/timeline-play'

export type { TileSourceId } from '../services/api-config'
export { DEFAULT_PLAY_INTERVAL_MS, TIMELINE_PLAY_INTERVAL_OPTIONS } from '../utils/timeline-play'

/** 地图交互模式：移动（拖动视角）/ 选择（点击查询点气象）/ 测量（路径规划与测距） */
export type InteractionMode = 'move' | 'select' | 'measure'

/** 视图模式：2D平面地图 / 3D地球（实验性，未完全实现） */
export type ViewMode = '2d' | '3d'

/** 测量路径点 */
export interface MeasurePoint {
  lng: number
  lat: number
}

/** 测量状态：路径点列表 + 绘制中标志 + 鼠标悬停点（用于动态预览） */
export interface MeasureState {
  points: MeasurePoint[]
  isDrawing: boolean
  hoverPoint: MeasurePoint | null
}

export type LayerTimeMemory = {
  /** YYYY-MM-DD */
  dateKey: string
  hour: number
}

const TIME_MODE_STORAGE_KEY = 'cgda.timeline.unified'
const LAYER_TIME_STORAGE_KEY = 'cgda.timeline.layer-memory'

function toDateKey(date: Date): string {
  const y = date.getFullYear()
  const m = String(date.getMonth() + 1).padStart(2, '0')
  const d = String(date.getDate()).padStart(2, '0')
  return `${y}-${m}-${d}`
}

function fromDateKey(key: string): Date | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(key)
  if (!m) return null
  const date = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]), 12, 0, 0, 0)
  return Number.isNaN(date.getTime()) ? null : date
}

function loadUnifiedFlag(): boolean {
  try {
    return window.localStorage?.getItem(TIME_MODE_STORAGE_KEY) === '1'
  } catch {
    return false
  }
}

function loadLayerMemory(): Record<string, LayerTimeMemory> {
  try {
    const raw = window.localStorage?.getItem(LAYER_TIME_STORAGE_KEY)
    if (!raw) return {}
    const parsed = JSON.parse(raw) as Record<string, unknown>
    const out: Record<string, LayerTimeMemory> = {}
    for (const [k, v] of Object.entries(parsed)) {
      if (!v || typeof v !== 'object') continue
      const row = v as Record<string, unknown>
      if (typeof row.dateKey === 'string' && typeof row.hour === 'number') {
        out[k] = {
          dateKey: row.dateKey,
          hour: quantizeClockHour(row.hour),
        }
      }
    }
    return out
  } catch {
    return {}
  }
}

export const useUiStore = defineStore('ui', () => {
  const tileSourceId = ref<TileSourceId>(getDefaultTileSource())
  const analysisFocusRequest = ref<{ ids: string[]; token: number } | null>(null)

  // 时间轴：日历日期 + 当日钟点 0–23
  const now = new Date()
  const currentHour = ref(now.getHours())
  const isPlaying = ref(false)
  const playIntervalMs = ref(loadPlayIntervalMs())
  const currentDate = ref(now)

  /**
   * 统一时间：开 → 所有图层共用当前时刻，切层不改时间；
   * 关 → 按 catalogId 记忆/恢复；新加图层对齐最新有效时次。
   */
  const unifiedTimeLock = ref(loadUnifiedFlag())
  const layerTimeMemory = ref<Record<string, LayerTimeMemory>>(loadLayerMemory())
  const lockedLayerIds = ref<Record<string, boolean>>({})
  const activeTimeGranularity = ref<'hour' | 'day' | 'month' | 'year' | 'static'>('hour')

  function toggleLayerTimeLock(catalogId: string) {
    lockedLayerIds.value = {
      ...lockedLayerIds.value,
      [catalogId]: !lockedLayerIds.value[catalogId],
    }
  }

  function isLayerTimeLocked(catalogId: string): boolean {
    return !!lockedLayerIds.value[catalogId]
  }

  function setTimelineGranularity(granularity: 'hour' | 'day' | 'month' | 'year' | 'static') {
    activeTimeGranularity.value = granularity
  }

  const interactionMode = ref<InteractionMode>('move')

  /** 视图模式：默认2D平面地图，3D为实验性占位 */
  const viewMode = ref<ViewMode>('2d')

  const measureState = ref<MeasureState>({
    points: [],
    isDrawing: false,
    hoverPoint: null,
  })

  const hourLabel = computed(() => formatClockHourLabel(currentHour.value))

  const fullTimeLabel = computed(() => {
    const date = currentDate.value
    const year = date.getFullYear()
    const month = String(date.getMonth() + 1).padStart(2, '0')
    const day = String(date.getDate()).padStart(2, '0')
    return `${year}-${month}-${day} ${hourLabel.value}`
  })

  watch(unifiedTimeLock, (on) => {
    try {
      window.localStorage?.setItem(TIME_MODE_STORAGE_KEY, on ? '1' : '0')
    } catch {
      /* ignore */
    }
  })

  watch(layerTimeMemory, (value) => {
    try {
      window.localStorage?.setItem(LAYER_TIME_STORAGE_KEY, JSON.stringify(value))
    } catch {
      /* ignore */
    }
  })

  function setTileSource(sourceId: TileSourceId) {
    tileSourceId.value = normalizeTileSourceId(sourceId)
  }

  function setHour(hour: number) {
    if (!Number.isFinite(hour)) return
    currentHour.value = quantizeClockHour(hour)
  }

  function stepHour(delta: number) {
    if (!Number.isFinite(delta) || delta === 0) return
    const nextValue = currentHour.value + delta

    if (nextValue < 0) {
      currentHour.value = CLOCK_DAY_MAX_HOUR
      const newDate = new Date(currentDate.value)
      newDate.setDate(newDate.getDate() - 1)
      currentDate.value = newDate
      return
    }

    if (nextValue > CLOCK_DAY_MAX_HOUR) {
      currentHour.value = 0
      const newDate = new Date(currentDate.value)
      newDate.setDate(newDate.getDate() + 1)
      currentDate.value = newDate
      return
    }

    currentHour.value = quantizeClockHour(nextValue)
  }

  function play() {
    isPlaying.value = true
  }

  function pause() {
    isPlaying.value = false
  }

  function togglePlay() {
    isPlaying.value = !isPlaying.value
  }

  function setPlayIntervalMs(ms: number) {
    const next = isValidPlayIntervalMs(ms) ? ms : DEFAULT_PLAY_INTERVAL_MS
    playIntervalMs.value = next
    persistPlayIntervalMs(next)
  }

  function setDate(date: Date) {
    currentDate.value = date
  }

  function setUnifiedTimeLock(on: boolean) {
    unifiedTimeLock.value = on
  }

  function toggleUnifiedTimeLock() {
    unifiedTimeLock.value = !unifiedTimeLock.value
  }

  /** 记住某图层最近使用的日期+钟点（仅非统一模式且未被单独锁定时有效） */
  function rememberLayerTime(catalogId: string | null | undefined, options?: { force?: boolean }) {
    if (!catalogId) return
    if (!options?.force && (unifiedTimeLock.value || isLayerTimeLocked(catalogId))) return
    layerTimeMemory.value = {
      ...layerTimeMemory.value,
      [catalogId]: {
        dateKey: toDateKey(currentDate.value),
        hour: currentHour.value,
      },
    }
  }

  /** 恢复某图层记忆；无记忆则返回 false */
  function restoreLayerTime(catalogId: string | null | undefined): boolean {
    if (!catalogId || unifiedTimeLock.value) return false
    const mem = layerTimeMemory.value[catalogId]
    if (!mem) return false
    const date = fromDateKey(mem.dateKey)
    if (!date) return false
    currentDate.value = date
    currentHour.value = mem.hour
    return true
  }

  function applyDateHour(date: Date, hour: number) {
    currentDate.value = date
    setHour(hour)
  }

  /** 按选中层原生步长切换时间轴粒度（hour/day/month/year） */
  function applyTimelineFromLayerGranularity(
    granularity: 'hour' | 'day' | 'month' | 'year' | 'static',
  ) {
    setTimelineGranularity(granularity)
  }

  function setInteractionMode(mode: InteractionMode) {
    interactionMode.value = mode
  }

  function setViewMode(mode: ViewMode) {
    viewMode.value = mode
  }

  function toggleViewMode() {
    viewMode.value = viewMode.value === '2d' ? '3d' : '2d'
  }

  function addMeasurePoint(p: MeasurePoint) {
    measureState.value.points.push(p)
    measureState.value.isDrawing = true
  }

  function undoLastMeasurePoint() {
    measureState.value.points.pop()
    if (measureState.value.points.length === 0) {
      measureState.value.isDrawing = false
    }
  }

  function completeMeasure() {
    measureState.value.isDrawing = false
    measureState.value.hoverPoint = null
  }

  function setHoverPoint(p: MeasurePoint | null) {
    measureState.value.hoverPoint = p
  }

  function clearMeasure() {
    measureState.value = { points: [], isDrawing: false, hoverPoint: null }
  }

  function requestAnalysisFocus(ids: string[]) {
    const normalizedIds = ids.map((id) => id.trim()).filter(Boolean)
    if (!normalizedIds.length) return
    analysisFocusRequest.value = {
      ids: normalizedIds,
      token: Date.now(),
    }
  }

  function clearAnalysisFocusRequest(token?: number) {
    if (!analysisFocusRequest.value) return
    if (typeof token === 'number' && analysisFocusRequest.value.token !== token) return
    analysisFocusRequest.value = null
  }

  return {
    tileSourceId,
    analysisFocusRequest,
    currentHour,
    hourLabel,
    fullTimeLabel,
    isPlaying,
    playIntervalMs,
    currentDate,
    unifiedTimeLock,
    layerTimeMemory,
    interactionMode,
    viewMode,
    measureState,
    lockedLayerIds,
    activeTimeGranularity,
    toggleLayerTimeLock,
    isLayerTimeLocked,
    setTimelineGranularity,
    setTileSource,
    setHour,
    stepHour,
    play,
    pause,
    togglePlay,
    setPlayIntervalMs,
    setDate,
    setUnifiedTimeLock,
    toggleUnifiedTimeLock,
    rememberLayerTime,
    restoreLayerTime,
    applyDateHour,
    applyTimelineFromLayerGranularity,
    setInteractionMode,
    setViewMode,
    toggleViewMode,
    addMeasurePoint,
    undoLastMeasurePoint,
    completeMeasure,
    setHoverPoint,
    clearMeasure,
    requestAnalysisFocus,
    clearAnalysisFocusRequest,
  }
})
