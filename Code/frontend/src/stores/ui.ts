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

/** 地图交互模式：移动（拖动视角）/ 选择（点击查询点气象）/ 测量（路径规划与测距）/ 绘制（矢量要素绘制） */
export type InteractionMode = 'move' | 'select' | 'measure' | 'draw'

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

/**
 * 「时刻钉子」：一次程序化 / 助手显式指定的时刻，在短窗口内**优先于**
 * `meta.default_time`、图层记忆和「新加图层跳最新帧」三套自动落点机制。
 *
 * 2026-11-07：组合指令「切到 SMAP 动态 + 切到 12-16 + 统计」里，切层是新增图层，
 * 它的 timeList 要等 overlay meta 回来才补到；`set_layer_visibility` 只等时间轴稳定
 * 约 120ms 就返回，于是 `set_timeline(12-16)` 先落下，随后 timeList 到位触发
 * 「新加图层 → 跳最新帧」，把 12-16 覆盖成该层默认帧（20250701_20250731，界面显示
 * 7 月 31 日）。后端只能保证意图顺序与日期正确，挡不住这次晚到的自动跳帧。
 *
 * 钉子不落 localStorage：它是「这一次操作」的保护窗，刷新后不该继续生效。
 */
export type TimelinePin = {
  catalogId: string
  dateKey: string
  hour: number
  /** Date.now()，用于判断是否还在保护窗内 */
  at: number
}

/** 保护窗：覆盖 timeList 晚到的常见延迟（overlay meta 通常在 1s 内回来） */
const TIMELINE_PIN_TTL_MS = 20_000

const TIME_MODE_STORAGE_KEY = 'cgda.timeline.unified'
const LAYER_TIME_STORAGE_KEY = 'cgda.timeline.layer-memory'
const UNIFIED_TIME_STORAGE_KEY = 'cgda.timeline.unified-time'

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

/** 统一时间模式下持久化的选定时刻（刷新后恢复，避免回退到当前时间） */
function loadUnifiedTime(): LayerTimeMemory | null {
  try {
    const raw = window.localStorage?.getItem(UNIFIED_TIME_STORAGE_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as Record<string, unknown>
    if (
      typeof parsed.dateKey === 'string' &&
      typeof parsed.hour === 'number' &&
      parsed.hour >= 0 &&
      parsed.hour <= 23
    ) {
      return { dateKey: parsed.dateKey, hour: parsed.hour }
    }
    return null
  } catch {
    return null
  }
}

function persistUnifiedTime(value: LayerTimeMemory | null): void {
  try {
    if (value === null) {
      window.localStorage?.removeItem(UNIFIED_TIME_STORAGE_KEY)
    } else {
      window.localStorage?.setItem(UNIFIED_TIME_STORAGE_KEY, JSON.stringify(value))
    }
  } catch {
    /* ignore */
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
  /** 打开侧栏「图层分组管理」对话框；themeId 为编辑目标主题（管理员）。 */
  const layerGroupManagerOpen = ref(false)
  const layerGroupManagerThemeId = ref<number | null>(null)

  // 时间轴：日历日期 + 当日钟点 0–23
  const now = new Date()
  const currentHour = ref(now.getHours())
  const isPlaying = ref(false)
  const playIntervalMs = ref(loadPlayIntervalMs())
  const currentDate = ref(now)

  /**
   * 统一时间：开 → 所有图层共用当前时刻，切层不改时间；
   * 关 → 按 catalogId 记忆/恢复；新加图层对齐最新有效时次。
   * 开启时选定的日期+钟点持久化，刷新后恢复（非统一模式清除，
   * 回退逐层记忆机制）。
   */
  const unifiedTimeLock = ref(loadUnifiedFlag())
  if (unifiedTimeLock.value) {
    const saved = loadUnifiedTime()
    if (saved) {
      const date = fromDateKey(saved.dateKey)
      if (date) {
        currentDate.value = date
        currentHour.value = saved.hour
      }
    }
  }
  const layerTimeMemory = ref<Record<string, LayerTimeMemory>>(loadLayerMemory())
  /** 显式指定的时刻（见 TimelinePin 注释）；不持久化 */
  const timelinePin = ref<TimelinePin | null>(null)
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
    if (!on) {
      // 关闭统一模式：清除全局选定时刻（回退逐层记忆机制）
      persistUnifiedTime(null)
    }
  })

  // 统一模式下选定时刻持久化（刷新后恢复 currentDate/currentHour）
  watch(
    () => [currentDate.value, currentHour.value] as const,
    () => {
      if (!unifiedTimeLock.value) return
      persistUnifiedTime({
        dateKey: toDateKey(currentDate.value),
        hour: currentHour.value,
      })
    },
  )

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

  /**
   * 直接把某图层的记忆时刻写成指定日期（不读当前时间轴）。
   *
   * 用途（2026-11-05）：默认图层「勾选先看月平均」。物化链改了 `meta.default_time`
   * 之后，浏览器 localStorage 里可能还留着上个月份的旧记忆，切层时会被
   * `restoreLayerTime` 恢复回去把默认帧顶掉 ⇒ 打开页面时统一按默认帧重写一次。
   */
  function setLayerTimeMemoryAt(catalogId: string | null | undefined, date: Date, hour = 0): void {
    if (!catalogId) return
    if (Number.isNaN(date.getTime())) return
    layerTimeMemory.value = {
      ...layerTimeMemory.value,
      [catalogId]: { dateKey: toDateKey(date), hour },
    }
  }

  /**
   * 钉住某图层这一刻：保护窗内 `snapTimelineToLayerLatest` / `restoreLayerTime`
   * 都不会把它顶掉（见 TimelinePin 注释）。调用方应当是「刚刚显式指定了日期」的
   * 地方（助手 set_timeline 落点之后），不要用在自动落点里。
   */
  function pinTimelineAt(catalogId: string | null | undefined, date: Date, hour = 0): void {
    if (!catalogId) return
    if (Number.isNaN(date.getTime())) return
    timelinePin.value = {
      catalogId,
      dateKey: toDateKey(date),
      hour: quantizeClockHour(hour),
      at: Date.now(),
    }
  }

  function clearTimelinePin(): void {
    timelinePin.value = null
  }

  /** 取某图层在保护窗内的钉子；过期或不同层返回 null（顺带清掉过期值） */
  function pinnedTimeFor(catalogId: string | null | undefined): LayerTimeMemory | null {
    const pin = timelinePin.value
    if (!pin) return null
    if (Date.now() - pin.at > TIMELINE_PIN_TTL_MS) {
      timelinePin.value = null
      return null
    }
    if (!catalogId || pin.catalogId !== catalogId) return null
    return { dateKey: pin.dateKey, hour: pin.hour }
  }

  /**
   * 该层此刻是否被钉住（含不区分图层的宽松判断）。
   *
   * 不传 catalogId 用于「这次自动落点该不该跳过」的粗判；传了就精确到层。
   */
  function isTimelinePinned(catalogId?: string | null): boolean {
    if (catalogId) return pinnedTimeFor(catalogId) !== null
    const pin = timelinePin.value
    if (!pin) return false
    if (Date.now() - pin.at > TIMELINE_PIN_TTL_MS) {
      timelinePin.value = null
      return false
    }
    return true
  }

  /** 恢复某图层记忆；钉子优先于记忆。无记忆则返回 false */
  function restoreLayerTime(catalogId: string | null | undefined): boolean {
    if (!catalogId || unifiedTimeLock.value) return false
    const mem = pinnedTimeFor(catalogId) ?? layerTimeMemory.value[catalogId]
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

  function openLayerGroupManager(themeId?: number | null) {
    layerGroupManagerThemeId.value =
      themeId != null && Number.isFinite(themeId) && themeId > 0 ? Number(themeId) : null
    layerGroupManagerOpen.value = true
  }

  function closeLayerGroupManager() {
    layerGroupManagerOpen.value = false
    layerGroupManagerThemeId.value = null
  }

  return {
    tileSourceId,
    analysisFocusRequest,
    layerGroupManagerOpen,
    layerGroupManagerThemeId,
    currentHour,
    hourLabel,
    fullTimeLabel,
    isPlaying,
    playIntervalMs,
    currentDate,
    unifiedTimeLock,
    layerTimeMemory,
    timelinePin,
    pinTimelineAt,
    clearTimelinePin,
    isTimelinePinned,
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
    setLayerTimeMemoryAt,
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
    openLayerGroupManager,
    closeLayerGroupManager,
  }
})
