<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { TimeGranularity, TimelineAvailabilitySegment } from '../utils/layer-timeline'
import {
  computeVisibleTickIndices,
  formatTimelineDateLabel,
  granularityUnitLabel,
  shiftTimelineDate,
} from '../utils/layer-timeline'
import { DEFAULT_PLAY_INTERVAL_MS, TIMELINE_PLAY_INTERVAL_OPTIONS } from '../utils/timeline-play'

const props = withDefaults(
  defineProps<{
    currentHour: number
    currentDate: Date
    hourLabel: string
    accentColor: string
    availabilityLabel: string
    observationTimeLabel: string
    timelineSegments: TimelineAvailabilitySegment[]
    coverageSourceLabel?: string
    unifiedTimeLock?: boolean
    isPlaying?: boolean
    playIntervalMs?: number
    granularity?: TimeGranularity
    activeLayerName?: string
    /** 当前段是否正在在线获取中 */
    onlineFetchInProgress?: boolean
    /** 图层平台子系统 P0：图层生命周期状态（fresh/stale/updating/missing/failed） */
    lifecycleState?: 'fresh' | 'stale' | 'updating' | 'missing' | 'failed' | 'unknown'
    /** lifecycle 状态提示文案（后端 message 或本地推导） */
    lifecycleMessage?: string | null
  }>(),
  {
    granularity: 'hour',
    unifiedTimeLock: true,
    isPlaying: false,
    playIntervalMs: DEFAULT_PLAY_INTERVAL_MS,
    activeLayerName: '',
    onlineFetchInProgress: false,
    lifecycleState: 'unknown',
    lifecycleMessage: null,
  },
)

const emit = defineEmits<{
  step: [delta: number]
  changeHour: [hour: number]
  changeDate: [date: Date]
  togglePlay: []
  toggleUnifiedTime: []
  changePlayInterval: [ms: number]
  /** 用户点击可在线获取段时触发 */
  fetchSegment: [segment: TimelineAvailabilitySegment]
}>()

// ── 日期与粒度格式化 ──────────────────────────────────────────
const isStatic = computed(() => props.granularity === 'static')

const formattedTimeHeader = computed(() => {
  return formatTimelineDateLabel(props.currentDate, props.granularity, props.currentHour)
})

const dateString = computed(() => {
  const d = props.currentDate
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
})

const monthString = computed(() => {
  const d = props.currentDate
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  return `${y}-${m}`
})

const daysInMonth = computed(() =>
  new Date(props.currentDate.getFullYear(), props.currentDate.getMonth() + 1, 0).getDate(),
)

const yearWindowStart = computed(() => props.currentDate.getFullYear() - 5)
const yearWindowEnd = computed(() => yearWindowStart.value + 9)

const weekdayLabel = computed(() => {
  if (isStatic.value) return '静态'
  const weekdays = ['周日', '周一', '周二', '周三', '周四', '周五', '周六']
  return weekdays[props.currentDate.getDay()]
})

const isToday = computed(() => {
  if (isStatic.value) return false
  const today = new Date()
  return (
    props.currentDate.getFullYear() === today.getFullYear() &&
    props.currentDate.getMonth() === today.getMonth() &&
    props.currentDate.getDate() === today.getDate()
  )
})

function segmentIndex(segment: TimelineAvailabilitySegment): number {
  return segment.timestamp ?? segment.index
}

function currentSliceValue(): number {
  if (props.granularity === 'month') return props.currentDate.getMonth()
  if (props.granularity === 'day') return props.currentDate.getDate()
  if (props.granularity === 'year') return props.currentDate.getFullYear()
  return props.currentHour
}

// ── 进度计算 ────────────────────────────────────────────────
const progressPercent = computed(() => {
  if (isStatic.value) return '100%'
  if (props.granularity === 'month') {
    return `${((props.currentDate.getMonth() / 11) * 100).toFixed(1)}%`
  }
  if (props.granularity === 'day') {
    const span = Math.max(1, daysInMonth.value - 1)
    return `${(((props.currentDate.getDate() - 1) / span) * 100).toFixed(1)}%`
  }
  if (props.granularity === 'year') {
    const offset = props.currentDate.getFullYear() - yearWindowStart.value
    return `${((Math.max(0, Math.min(9, offset)) / 9) * 100).toFixed(1)}%`
  }
  // hour：按实际切片跨度定位（天气 8 段或 24 小时）
  const segs = props.timelineSegments
  if (segs.length >= 2) {
    const values = segs.map((s) => segmentIndex(s)).sort((a, b) => a - b)
    const min = values[0]!
    const max = values[values.length - 1]!
    const span = Math.max(1e-6, max - min)
    const t = Math.max(0, Math.min(1, (props.currentHour - min) / span))
    return `${(t * 100).toFixed(1)}%`
  }
  return `${((props.currentHour / 23) * 100).toFixed(1)}%`
})

const liveLabel = computed(() => `${props.availabilityLabel}`)
const coverageCaption = computed(() => props.coverageSourceLabel?.trim() || '数据覆盖')

// ── 图层平台子系统 P0：生命周期徽标（叠加显示，不替换旧渲染） ────────────────
const LIFECYSTATE_LABELS: Record<string, string> = {
  fresh: '资产就绪',
  stale: '资产陈旧',
  updating: '更新中',
  missing: '资产缺失',
  failed: '更新失败',
  unknown: '',
}
const lifecycleBadgeLabel = computed(
  () => LIFECYSTATE_LABELS[props.lifecycleState] ?? '',
)
const lifecycleBadgeClass = computed(() => `lifecycle-badge-${props.lifecycleState}`)
/** unknown 不显示徽标（保持旧行为） */
const showLifecycleBadge = computed(() => props.lifecycleState !== 'unknown')

/** 过长图层名中间省略，保留前缀与后缀便于辨认 */
const displayLayerName = computed(() => truncateMiddle(props.activeLayerName?.trim() || '', 28))

function truncateMiddle(text: string, maxChars: number): string {
  if (!text || text.length <= maxChars) return text
  const keep = maxChars - 1
  const head = Math.ceil(keep * 0.55)
  const tail = keep - head
  return `${text.slice(0, head)}…${text.slice(-tail)}`
}

const nearestSegment = computed(() => {
  if (isStatic.value) {
    return {
      index: 0,
      label: '静态',
      state: 'static' as const,
      availabilityLabel: '无时间维度 · 全面就绪',
    }
  }
  const target = currentSliceValue()
  return props.timelineSegments.reduce(
    (closest, segment) => {
      const segVal = segmentIndex(segment)
      return Math.abs(segVal - target) < Math.abs(segmentIndex(closest) - target)
        ? segment
        : closest
    },
    props.timelineSegments[0] ?? {
      index: 0,
      label: '无数据',
      state: 'empty' as const,
      availabilityLabel: '无数据',
    },
  )
})

const trackStyle = computed(() => ({
  '--track-progress': progressPercent.value,
  '--accent-color': props.accentColor,
}))

function isTickActive(tick: TimelineAvailabilitySegment): boolean {
  // 事件时间轴（2026-08-25）：static 多段时按观测年份高亮，单段保持全选
  if (isStatic.value) {
    return props.timelineSegments.length > 1
      ? segmentIndex(tick) === props.currentDate.getFullYear()
      : true
  }
  const idx = segmentIndex(tick)
  if (props.granularity === 'month') return idx === props.currentDate.getMonth()
  if (props.granularity === 'day') return idx === props.currentDate.getDate()
  if (props.granularity === 'year') return idx === props.currentDate.getFullYear()
  // hour：刻度可能是 0..23 或天气 8 段 (0,3,…,21)
  return Math.abs(props.currentHour - idx) < 1.5
}

// ── 日期/切片导航 ──────────────────────────────────────────────
/** 按当前粒度前进/后退一个切片（步进按钮与播放共用；优先跳到有数据的段） */
function advanceSlice(delta: number) {
  if (isStatic.value || !Number.isFinite(delta) || delta === 0) return

  if (props.granularity === 'hour') {
    const segs = props.timelineSegments
    const usable = segs
      .filter((s) => s.state === 'ready' || s.state === 'partial' || s.state === 'fetchable')
      .map((s) => ({ seg: s, value: segmentIndex(s) }))
      .sort((a, b) => a.value - b.value)

    if (usable.length > 0) {
      const cur = props.currentHour
      if (delta > 0) {
        const next = usable.find((u) => u.value > cur + 0.2)
        if (next) {
          emit('changeHour', next.value)
          return
        }
        // 跨日：先改日再落到首个有数据段
        const nextDate = shiftTimelineDate(props.currentDate, 1, 'day')
        emit('changeDate', nextDate)
        emit('changeHour', usable[0]!.value)
        return
      }
      const prev = [...usable].reverse().find((u) => u.value < cur - 0.2)
      if (prev) {
        emit('changeHour', prev.value)
        return
      }
      const prevDate = shiftTimelineDate(props.currentDate, -1, 'day')
      emit('changeDate', prevDate)
      emit('changeHour', usable[usable.length - 1]!.value)
      return
    }

    emit('step', delta)
    return
  }

  emit('changeDate', shiftTimelineDate(props.currentDate, delta, props.granularity))
}

function onDateInput(event: Event) {
  const value = (event.target as HTMLInputElement).value
  if (!value || isStatic.value) return

  if (props.granularity === 'month') {
    const [y, m] = value.split('-').map(Number)
    if (!y || !m) return
    const newDate = new Date(props.currentDate)
    newDate.setFullYear(y, m - 1, 1)
    emit('changeDate', newDate)
    return
  }

  const [y, m, d] = value.split('-').map(Number)
  if (!y || !m || !d) return
  const newDate = new Date(props.currentDate)
  newDate.setFullYear(y, m - 1, d)
  emit('changeDate', newDate)
}

function onYearInput(event: Event) {
  const yearVal = Number((event.target as HTMLInputElement).value)
  if (!Number.isFinite(yearVal) || yearVal < 1980 || yearVal > 2100) return
  const newDate = new Date(props.currentDate)
  newDate.setFullYear(yearVal)
  emit('changeDate', newDate)
}

function onSliderInput(event: Event) {
  const val = Number((event.target as HTMLInputElement).value)
  if (!Number.isFinite(val)) return
  if (props.granularity === 'month') {
    const newDate = new Date(props.currentDate)
    newDate.setMonth(val)
    emit('changeDate', newDate)
    return
  }
  if (props.granularity === 'day') {
    const day = Math.max(1, Math.min(daysInMonth.value, Math.round(val)))
    const newDate = new Date(props.currentDate)
    newDate.setDate(day)
    emit('changeDate', newDate)
    return
  }
  if (props.granularity === 'year') {
    const newDate = new Date(props.currentDate)
    newDate.setFullYear(Math.round(val))
    emit('changeDate', newDate)
    return
  }
  emit('changeHour', val)
}

function handleTickClick(tickIndex: number) {
  if (!Number.isFinite(tickIndex)) return
  if (props.granularity === 'month') {
    const newDate = new Date(props.currentDate)
    newDate.setMonth(tickIndex)
    emit('changeDate', newDate)
    return
  }
  if (props.granularity === 'day') {
    const day = Math.max(1, Math.min(daysInMonth.value, Math.round(tickIndex)))
    const newDate = new Date(props.currentDate)
    newDate.setDate(day)
    emit('changeDate', newDate)
    return
  }
  if (props.granularity === 'year') {
    const newDate = new Date(props.currentDate)
    newDate.setFullYear(Math.round(tickIndex))
    emit('changeDate', newDate)
    return
  }
  if (props.granularity === 'static') {
    // 事件时间轴（2026-08-25）：static 图层的事件年刻度，点击跳转观测年份
    const newDate = new Date(props.currentDate)
    newDate.setFullYear(Math.round(tickIndex))
    emit('changeDate', newDate)
    return
  }
  emit('changeHour', tickIndex)
}

// ── 播放控制 ──────────────────────────────────────────────────
const playing = computed(() => props.isPlaying ?? false)
const playInterval = ref<number | null>(null)
const documentVisible = ref(
  typeof document === 'undefined' ? true : document.visibilityState !== 'hidden',
)
const playMenuOpen = ref(false)
const playBtnRef = ref<HTMLButtonElement | null>(null)
const playMenuStyle = ref<Record<string, string>>({})

const playIntervalOptions = TIMELINE_PLAY_INTERVAL_OPTIONS
const effectivePlayMs = computed(() => {
  const ms = props.playIntervalMs
  return playIntervalOptions.some((opt) => opt.ms === ms) ? ms : DEFAULT_PLAY_INTERVAL_MS
})
const playIntervalLabel = computed(
  () => playIntervalOptions.find((opt) => opt.ms === effectivePlayMs.value)?.label ?? '2 秒',
)

function clearPlayInterval() {
  if (playInterval.value !== null) {
    window.clearInterval(playInterval.value)
    playInterval.value = null
  }
}

function startPlayInterval() {
  if (playInterval.value !== null || isStatic.value) return
  playInterval.value = window.setInterval(() => {
    advanceSlice(1)
  }, effectivePlayMs.value)
}

function syncPlayInterval() {
  clearPlayInterval()
  if (playing.value && documentVisible.value && !isStatic.value) {
    startPlayInterval()
  }
}

function onVisibilityChange() {
  documentVisible.value = document.visibilityState !== 'hidden'
  syncPlayInterval()
}

function closePlayMenu() {
  playMenuOpen.value = false
}

function openPlayMenu() {
  if (isStatic.value) return
  playMenuOpen.value = true
  void nextTick(() => {
    const btn = playBtnRef.value
    if (!btn) return
    const rect = btn.getBoundingClientRect()
    const menuWidth = 148
    const left = Math.min(rect.left, window.innerWidth - menuWidth - 8)
    const top = Math.max(8, rect.top - 8)
    playMenuStyle.value = {
      position: 'fixed',
      left: `${Math.max(8, left)}px`,
      top: `${top}px`,
      transform: 'translateY(-100%)',
      zIndex: '80',
    }
  })
}

function onPlayContextMenu(event: MouseEvent) {
  event.preventDefault()
  event.stopPropagation()
  if (isStatic.value) return
  openPlayMenu()
}

function selectPlayInterval(ms: number) {
  emit('changePlayInterval', ms)
  closePlayMenu()
  // 若正在播放，立即用新间隔重启
  clearPlayInterval()
  if (playing.value && documentVisible.value && !isStatic.value) {
    playInterval.value = window.setInterval(() => {
      advanceSlice(1)
    }, ms)
  }
}

function onPlayMenuKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape') closePlayMenu()
}

watch([playing, isStatic, effectivePlayMs], () => {
  syncPlayInterval()
})

onMounted(() => {
  document.addEventListener('visibilitychange', onVisibilityChange)
  document.addEventListener('pointerdown', onDocPointerDown, true)
  document.addEventListener('keydown', onPlayMenuKeydown)
  syncPlayInterval()
})

onBeforeUnmount(() => {
  document.removeEventListener('visibilitychange', onVisibilityChange)
  document.removeEventListener('pointerdown', onDocPointerDown, true)
  document.removeEventListener('keydown', onPlayMenuKeydown)
  clearPlayInterval()
})

function onDocPointerDown(event: PointerEvent) {
  if (!playMenuOpen.value) return
  const target = event.target as Node | null
  if (playBtnRef.value?.contains(target)) return
  const menu = document.getElementById('timeline-play-interval-menu')
  if (menu?.contains(target)) return
  closePlayMenu()
}

function jumpToNow() {
  if (isStatic.value) return
  const now = new Date()
  emit('changeDate', now)
  emit('changeHour', now.getHours())
}

const datePickerInputRef = ref<HTMLInputElement | null>(null)

function triggerDatePicker() {
  if (isStatic.value) return
  if (datePickerInputRef.value) {
    try {
      if (typeof datePickerInputRef.value.showPicker === 'function') {
        datePickerInputRef.value.showPicker()
      } else {
        datePickerInputRef.value.click()
      }
    } catch {
      datePickerInputRef.value.click()
    }
  }
}

// ── 刻度智能抽稀 ─────────────────────────────────────────────
const unitLabel = computed(() => granularityUnitLabel(props.granularity))

const visibleTickSet = computed(() => computeVisibleTickIndices(props.timelineSegments.length, 12))
</script>

<template>
  <section class="timeline" :class="[`timeline--${granularity}`]" :style="trackStyle">
    <!-- 顶部：日期展示 + 图层与粒度 + 统一动作按钮组 -->
    <div class="timeline-top">
      <!-- 左侧：日期/时间点展示 + Picker + 快捷复位 -->
      <div class="date-nav">
        <div
          class="date-display"
          :title="isStatic ? '静态数据' : '点击弹出日期/时间选择器'"
          role="button"
          tabindex="0"
          @click="triggerDatePicker"
          @keydown.enter.prevent="triggerDatePicker"
          @keydown.space.prevent="triggerDatePicker"
        >
          <svg class="calendar-icon" viewBox="0 0 16 16" aria-hidden="true">
            <path
              fill="currentColor"
              d="M3.5 0a.5.5 0 0 1 .5.5V1h8V.5a.5.5 0 0 1 1 0V1h1a2 2 0 0 1 2 2v11a2 2 0 0 1-2 2H2a2 2 0 0 1-2-2V3a2 2 0 0 1 2-2h1V.5a.5.5 0 0 1 .5-.5zM1 4v10a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V4H1z"
            />
          </svg>
          <span class="date-text">{{ formattedTimeHeader }}</span>
          <span v-if="!isStatic" class="date-weekday">{{ weekdayLabel }}</span>
          <span v-if="isToday" class="date-today-badge">今</span>

          <input
            v-if="granularity === 'month'"
            ref="datePickerInputRef"
            class="date-picker-hidden"
            type="month"
            :value="monthString"
            @change="onDateInput"
          />
          <input
            v-else-if="granularity === 'year'"
            ref="datePickerInputRef"
            class="date-picker-hidden"
            type="number"
            min="1980"
            max="2100"
            :value="currentDate.getFullYear()"
            @change="onYearInput"
          />
          <input
            v-else-if="!isStatic"
            ref="datePickerInputRef"
            class="date-picker-hidden"
            type="date"
            :value="dateString"
            @change="onDateInput"
          />
        </div>

        <button
          v-if="!isStatic"
          class="nav-btn nav-btn--now"
          type="button"
          title="Jump to now"
          @click="jumpToNow"
        >
          <span class="now-label">Now</span>
        </button>
      </div>

      <!-- 中间：激活图层名称 + 粒度标记 (居中对齐) -->
      <div class="time-heading">
        <span v-if="activeLayerName" class="active-layer-tag" :title="activeLayerName">
          {{ displayLayerName }}
        </span>
        <span class="granularity-badge" :class="`granularity-${granularity}`">
          {{
            granularity === 'static'
              ? '静态'
              : granularity === 'month'
                ? '月度'
                : granularity === 'year'
                  ? '年度'
                  : granularity === 'day'
                    ? '日尺度'
                    : '小时'
          }}
        </span>
      </div>

      <!-- 右侧：统一动作组（前进/后退、播放、图层锁定、统一联动） -->
      <div class="top-actions">
        <!-- 统一的步进/切片控制组 -->
        <div class="step-group">
          <button
            class="action-btn step-btn"
            type="button"
            :disabled="isStatic"
            title="上一时间切片"
            @click="advanceSlice(-1)"
          >
            <svg viewBox="0 0 16 16" aria-hidden="true">
              <path fill="currentColor" d="M10 3 5 8l5 5" />
            </svg>
          </button>

          <button
            ref="playBtnRef"
            class="action-btn play-btn"
            :class="{ 'play-btn--playing': playing, 'play-btn--menu-open': playMenuOpen }"
            type="button"
            :disabled="isStatic"
            :title="
              isStatic
                ? '静态图层不可播放'
                : playing
                  ? `暂停（间隔 ${playIntervalLabel} · 右键改间隔）`
                  : `播放（间隔 ${playIntervalLabel} · 右键改间隔）`
            "
            @click="emit('togglePlay')"
            @contextmenu="onPlayContextMenu"
          >
            <svg v-if="!playing" viewBox="0 0 16 16" aria-hidden="true">
              <path fill="currentColor" d="M4.5 2.8v10.4l8.5-5.2z" />
            </svg>
            <svg v-else viewBox="0 0 16 16" aria-hidden="true">
              <rect fill="currentColor" x="3.5" y="3" width="3" height="10" rx="0.5" />
              <rect fill="currentColor" x="9.5" y="3" width="3" height="10" rx="0.5" />
            </svg>
          </button>

          <button
            class="action-btn step-btn"
            type="button"
            :disabled="isStatic"
            title="下一时间切片"
            @click="advanceSlice(1)"
          >
            <svg viewBox="0 0 16 16" aria-hidden="true">
              <path fill="currentColor" d="M6 3l5 5-5 5" />
            </svg>
          </button>
        </div>

        <div class="divider" aria-hidden="true"></div>

        <!-- 全局统一时间 Link 按钮 -->
        <button
          class="action-btn sync-btn"
          type="button"
          :class="{ 'sync-btn--on': unifiedTimeLock }"
          :title="
            unifiedTimeLock
              ? '全局统一时间已开启：切换图层保留同一时刻（点击切换为图层记忆）'
              : '图层独立记忆模式：按图层记住各自时刻（点击开启全局统一时间）'
          "
          @click="emit('toggleUnifiedTime')"
        >
          <svg v-if="unifiedTimeLock" viewBox="0 0 16 16" aria-hidden="true">
            <path
              fill="none"
              stroke="currentColor"
              stroke-width="1.4"
              stroke-linecap="round"
              d="M6.2 9.8 9.8 6.2M5.4 7.1a2.2 2.2 0 0 1 0-3.1l1.1-1.1a2.2 2.2 0 0 1 3.1 0M10.6 8.9a2.2 2.2 0 0 1 0 3.1l-1.1 1.1a2.2 2.2 0 0 1-3.1 0"
            />
          </svg>
          <svg v-else viewBox="0 0 16 16" aria-hidden="true">
            <path
              fill="none"
              stroke="currentColor"
              stroke-width="1.35"
              stroke-linejoin="round"
              d="M2.5 5.2 8 2.8l5.5 2.4L8 7.6 2.5 5.2zm0 3.2L8 6l5.5 2.4L8 10.8 2.5 8.4zm0 3.2L8 9.2l5.5 2.4L8 14 2.5 11.6z"
            />
          </svg>
        </button>
      </div>
    </div>

    <!-- 中部：数据可用性 + 滑块 + 刻度切片 -->
    <div class="timeline-track">
      <div
        class="availability-caption"
        :title="`${coverageCaption} · ${nearestSegment.availabilityLabel} · ${liveLabel}`"
      >
        <span class="availability-caption-side availability-caption-main">{{
          coverageCaption
        }}</span>
        <strong class="availability-caption-status">{{ nearestSegment.availabilityLabel }}</strong>
        <span class="availability-caption-side availability-live">{{ liveLabel }}</span>
        <!-- 图层平台子系统 P0：生命周期徽标（叠加，不改既有可用性显示） -->
        <span
          v-if="showLifecycleBadge"
          class="lifecycle-badge"
          :class="lifecycleBadgeClass"
          :title="props.lifecycleMessage || lifecycleBadgeLabel"
          >{{ lifecycleBadgeLabel }}</span
        >
      </div>

      <!-- 可用性切片条：fetchable 段可点击触发在线获取 -->
      <div class="availability-strip">
        <span
          v-for="segment in timelineSegments"
          :key="segment.index"
          class="availability-segment"
          :class="[
            `availability-${segment.state}`,
            { 'availability-fetchable-clickable': segment.state === 'fetchable' },
          ]"
          :title="`${segment.label} · ${segment.availabilityLabel}`"
          @click="segment.state === 'fetchable' ? emit('fetchSegment', segment) : undefined"
        ></span>
      </div>

      <!-- 交互滑块轨道 -->
      <div class="track-interactive" :class="{ disabled: isStatic }">
        <div class="track-shell">
          <div class="track-fill" aria-hidden="true"></div>
          <div class="track-buffer" aria-hidden="true"></div>
          <div class="track-thumb" aria-hidden="true"></div>
        </div>

        <input
          v-if="granularity === 'month'"
          class="slider"
          type="range"
          min="0"
          max="11"
          step="1"
          :value="currentDate.getMonth()"
          @input="onSliderInput"
        />
        <input
          v-else-if="granularity === 'day'"
          class="slider"
          type="range"
          min="1"
          :max="daysInMonth"
          step="1"
          :value="currentDate.getDate()"
          @input="onSliderInput"
        />
        <input
          v-else-if="granularity === 'year'"
          class="slider"
          type="range"
          :min="yearWindowStart"
          :max="yearWindowEnd"
          step="1"
          :value="currentDate.getFullYear()"
          @input="onSliderInput"
        />
        <input
          v-else-if="!isStatic"
          class="slider"
          type="range"
          min="0"
          max="23"
          step="0.25"
          :value="currentHour"
          @input="onSliderInput"
        />
      </div>

      <!-- 时间刻度按钮 (智能抽稀: 密集时仅主刻度显示标签) -->
      <div class="timeline-ticks">
        <button
          v-for="(tick, i) in timelineSegments"
          :key="tick.index"
          class="tick-button"
          type="button"
          :class="[
            `tick-${tick.state}`,
            {
              active: isTickActive(tick),
              'tick-minor': !visibleTickSet.has(i),
            },
          ]"
          :title="`${tick.label}${unitLabel} · ${tick.availabilityLabel}`"
          @click="handleTickClick(tick.index)"
        >
          <span v-if="visibleTickSet.has(i)" class="tick-label">{{ tick.label }}</span>
          <span v-else class="tick-bar" aria-hidden="true"></span>
        </button>
        <!-- 单位指示标签 -->
        <span v-if="unitLabel && timelineSegments.length > 1" class="tick-unit-badge">{{
          unitLabel
        }}</span>
      </div>
    </div>

    <!-- 底部：元信息面板 -->
    <div class="timeline-meta">
      <span class="meta-text meta-text--left">
        模式:
        <strong>{{
          granularity === 'static'
            ? '静态数据'
            : granularity === 'month'
              ? '月度分析'
              : granularity === 'year'
                ? '年度产品'
                : '实时/时序'
        }}</strong>
      </span>
      <span class="meta-text meta-text--center">
        进度: <strong>{{ progressPercent }}</strong>
      </span>
      <span class="meta-text meta-text--right">
        当前观测: <strong>{{ observationTimeLabel || formattedTimeHeader }}</strong>
      </span>
    </div>

    <!-- 播放间隔菜单：右键播放按钮打开 -->
    <Teleport to="body">
      <div
        v-if="playMenuOpen"
        id="timeline-play-interval-menu"
        class="play-interval-menu"
        role="menu"
        aria-label="播放间隔"
        :style="playMenuStyle"
      >
        <div class="play-interval-menu-title">播放间隔</div>
        <button
          v-for="opt in playIntervalOptions"
          :key="opt.ms"
          type="button"
          class="play-interval-option"
          role="menuitemradio"
          :aria-checked="opt.ms === effectivePlayMs"
          :class="{ active: opt.ms === effectivePlayMs }"
          @click="selectPlayInterval(opt.ms)"
        >
          <span class="play-interval-check" aria-hidden="true">{{
            opt.ms === effectivePlayMs ? '●' : '○'
          }}</span>
          <span>{{ opt.label }}</span>
        </button>
      </div>
    </Teleport>
  </section>
</template>

<style scoped src="./TimelineScrubber.styles.css" />

<style src="./TimelineScrubber.global.css" />
