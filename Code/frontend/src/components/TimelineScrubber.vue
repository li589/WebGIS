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
    isLayerLocked?: boolean
  }>(),
  {
    granularity: 'hour',
    unifiedTimeLock: true,
    isPlaying: false,
    playIntervalMs: DEFAULT_PLAY_INTERVAL_MS,
    isLayerLocked: false,
    activeLayerName: '',
  },
)

const emit = defineEmits<{
  step: [delta: number]
  changeHour: [hour: number]
  changeDate: [date: Date]
  togglePlay: []
  toggleUnifiedTime: []
  toggleLayerLock: []
  changePlayInterval: [ms: number]
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
  if (isStatic.value) return true
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
      .filter((s) => s.state === 'ready' || s.state === 'partial')
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
          @click="triggerDatePicker"
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

        <!-- 图层时间独立锁定开关 -->
        <button
          class="action-btn lock-btn"
          type="button"
          :class="{ 'lock-btn--locked': isLayerLocked }"
          :title="
            isLayerLocked
              ? '已锁定本图层时间记忆：切回时恢复锁定时刻；播放/拖动仍用全局时刻驱动地图（点击解除）'
              : '未锁定记忆：切层时按图层记忆模式读写时刻（点击锁定当前时刻）'
          "
          @click="emit('toggleLayerLock')"
        >
          <svg v-if="isLayerLocked" viewBox="0 0 16 16" aria-hidden="true">
            <path
              fill="currentColor"
              d="M8 1a3.5 3.5 0 0 0-3.5 3.5V6H4a1 1 0 0 0-1 1v7a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1V7a1 1 0 0 0-1-1h-.5V4.5A3.5 3.5 0 0 0 8 1zm2 5H6V4.5a2 2 0 1 1 4 0V6z"
            />
          </svg>
          <svg v-else viewBox="0 0 16 16" aria-hidden="true">
            <path
              fill="currentColor"
              d="M11 6V4.5a3.5 3.5 0 1 0-7 0v.5h1.5v-.5a2 2 0 1 1 4 0V6H4a1 1 0 0 0-1 1v7a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1V7a1 1 0 0 0-1-1h-1z"
            />
          </svg>
        </button>

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
      </div>

      <!-- 可用性切片条：包含空数据灰色条指示 -->
      <div class="availability-strip" aria-hidden="true">
        <span
          v-for="segment in timelineSegments"
          :key="segment.index"
          class="availability-segment"
          :class="`availability-${segment.state}`"
          :title="`${segment.label} · ${segment.availabilityLabel}`"
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
        维度进度: <strong>{{ progressPercent }}</strong>
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

<style scoped>
.timeline {
  display: flex;
  flex-direction: column;
  background: rgba(18, 30, 52, 0.72);
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
  border: 1px solid var(--border-default);
  border-radius: 0.85rem;
  padding: 0.48rem 0.75rem;
  box-shadow: 0 10px 32px rgba(0, 0, 0, 0.45);
  color: #e2e8f0;
  user-select: none;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
  transition: all 0.2s ease;
}

.timeline-top {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
  margin-bottom: 0.25rem;
  min-height: 2rem;
}

.date-nav {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  justify-self: start;
  flex-shrink: 0;
  min-width: max-content;
  z-index: 2;
}

.calendar-icon {
  width: 0.85rem;
  height: 0.85rem;
  color: #38bdf8;
  flex-shrink: 0;
}

.date-display {
  position: relative;
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  padding: 0.25rem 0.55rem;
  background: rgba(15, 23, 42, 0.7);
  border: 1px solid rgba(56, 189, 248, 0.22);
  border-radius: 0.45rem;
  font-size: 0.8rem;
  font-weight: 500;
  color: #f1f5f9;
  cursor: pointer;
  flex-shrink: 0;
  max-width: none;
  transition:
    border-color 0.15s ease,
    background 0.15s ease;
}

.date-display:hover {
  border-color: rgba(56, 189, 248, 0.45);
  background: rgba(15, 23, 42, 0.85);
}

.date-text {
  font-family: 'JetBrains Mono', ui-monospace, SFMono-Regular, Roboto, monospace;
  font-size: var(--font-size-caption);
  color: #38bdf8;
  letter-spacing: 0.02em;
  white-space: nowrap;
  flex-shrink: 0;
}

.date-picker-hidden {
  position: absolute;
  inset: 0;
  opacity: 0;
  width: 100%;
  height: 100%;
  pointer-events: none;
}

.date-weekday {
  font-size: var(--font-size-caption);
  color: #94a3b8;
  flex-shrink: 0;
  white-space: nowrap;
}

.date-today-badge {
  font-size: var(--font-size-caption);
  background: rgba(56, 189, 248, 0.2);
  color: #38bdf8;
  border: 1px solid rgba(56, 189, 248, 0.3);
  padding: 0 0.25rem;
  border-radius: 0.2rem;
  font-weight: 600;
  flex-shrink: 0;
}

.nav-btn--now {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0.18rem 0.38rem;
  border-radius: 0.35rem;
  border: 1px solid rgba(255, 255, 255, 0.1);
  background: rgba(255, 255, 255, 0.04);
  color: #94a3b8;
  cursor: pointer;
  flex-shrink: 0;
  transition: all 0.15s ease;
}

.nav-btn--now:hover {
  background: rgba(56, 189, 248, 0.12);
  color: #e0f2fe;
  border-color: rgba(56, 189, 248, 0.35);
}

.now-label {
  font-family:
    'JetBrains Mono', ui-monospace, 'Cascadia Code', 'SF Mono', Menlo, Consolas, monospace;
  font-style: normal;
  font-weight: 600;
  font-size: var(--font-size-caption);
  letter-spacing: 0.08em;
  line-height: 1;
  text-transform: uppercase;
}

.time-heading {
  position: absolute;
  left: 50%;
  top: 50%;
  transform: translate(-50%, -50%);
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.35rem;
  min-width: 0;
  max-width: min(42%, 280px);
  z-index: 1;
  pointer-events: none;
  text-align: center;
}

.time-heading .active-layer-tag,
.time-heading .granularity-badge {
  pointer-events: auto;
}

.top-actions {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  justify-content: flex-end;
  flex-shrink: 0;
  z-index: 2;
  margin-left: auto;
}

.active-layer-tag {
  font-size: var(--font-size-caption);
  font-weight: 600;
  color: #f8fafc;
  background: rgba(30, 41, 59, 0.7);
  border: 1px solid rgba(255, 255, 255, 0.08);
  padding: 0.15rem 0.5rem;
  border-radius: 0.35rem;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  min-width: 0;
  max-width: min(100%, 220px);
  flex: 1 1 auto;
  cursor: default;
}

.granularity-badge {
  font-size: var(--font-size-caption);
  padding: 0.12rem 0.4rem;
  border-radius: 0.3rem;
  border: 1px solid rgba(56, 189, 248, 0.3);
  background: rgba(56, 189, 248, 0.1);
  color: #38bdf8;
  font-weight: 500;
  flex: none;
}

.granularity-static {
  border-color: rgba(148, 163, 184, 0.25);
  background: rgba(148, 163, 184, 0.08);
  color: #94a3b8;
}

.granularity-month {
  border-color: rgba(16, 185, 129, 0.3);
  background: rgba(16, 185, 129, 0.1);
  color: #10b981;
}

.divider {
  width: 1px;
  height: 1rem;
  background: rgba(255, 255, 255, 0.1);
  margin: 0 0.1rem;
}

.step-group {
  display: flex;
  align-items: center;
  background: rgba(15, 23, 42, 0.6);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 0.45rem;
  padding: 0.1rem;
  gap: 0.1rem;
}

.action-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  height: 1.45rem;
  padding: 0 0.4rem;
  border-radius: 0.35rem;
  border: 1px solid transparent;
  background: transparent;
  color: #94a3b8;
  cursor: pointer;
  font-size: var(--font-size-caption);
  transition: all 0.15s ease;
}

.action-btn:hover:not(:disabled) {
  background: rgba(255, 255, 255, 0.1);
  color: #f8fafc;
}

.action-btn:disabled {
  opacity: 0.35;
  cursor: not-allowed;
}

.action-btn svg {
  width: 0.8rem;
  height: 0.8rem;
}

.play-btn {
  color: #38bdf8;
}

.play-btn--playing {
  color: #f59e0b;
  background: rgba(245, 158, 11, 0.15);
}

.play-btn--menu-open {
  border-color: rgba(56, 189, 248, 0.45);
  color: #38bdf8;
}

.lock-btn {
  width: 1.45rem;
  padding: 0;
  border: 1px solid rgba(255, 255, 255, 0.1);
  background: rgba(15, 23, 42, 0.5);
}

.lock-btn--locked {
  border-color: rgba(245, 158, 11, 0.45);
  background: rgba(245, 158, 11, 0.18);
  color: #fbbf24;
}

.sync-btn {
  width: 1.45rem;
  padding: 0;
  border: 1px solid rgba(255, 255, 255, 0.1);
  background: rgba(15, 23, 42, 0.5);
}

.sync-btn--on {
  border-color: rgba(56, 189, 248, 0.4);
  background: rgba(56, 189, 248, 0.15);
  color: #38bdf8;
}

.timeline-track {
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
}

.availability-caption {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr);
  align-items: center;
  column-gap: 0.4rem;
  font-size: var(--font-size-caption);
  color: #94a3b8;
  min-height: 1rem;
}

.availability-caption-side {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.availability-caption-main {
  justify-self: start;
  text-align: left;
}

.availability-caption-status {
  justify-self: center;
  text-align: center;
  font-weight: 500;
  color: #cbd5e1;
  white-space: nowrap;
  padding: 0 0.15rem;
}

.availability-live {
  justify-self: end;
  text-align: right;
}

.availability-strip {
  display: flex;
  height: 4px;
  gap: 2px;
  border-radius: 2px;
  overflow: hidden;
  background: rgba(15, 23, 42, 0.4);
}

.availability-segment {
  flex: 1;
  border-radius: 1px;
  transition: opacity 0.15s ease;
}

.availability-ready {
  background: #10b981;
}

.availability-partial {
  background: #f59e0b;
}

/* 高质感无数据标灰切片 */
.availability-empty {
  background: rgba(148, 163, 184, 0.3);
}

.availability-error {
  background: #ef4444;
}

.availability-static {
  background: rgba(100, 116, 139, 0.2);
}

.track-interactive {
  position: relative;
  height: 1rem;
  display: flex;
  align-items: center;
}

.track-interactive.disabled {
  opacity: 0.45;
  pointer-events: none;
}

.track-shell {
  position: absolute;
  left: 0;
  right: 0;
  height: 0.35rem;
  background: rgba(255, 255, 255, 0.06);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 999px;
  overflow: hidden;
}

.track-fill {
  height: 100%;
  width: var(--track-progress);
  background: linear-gradient(90deg, rgba(56, 189, 248, 0.4), var(--accent-color, #38bdf8));
  border-radius: 999px;
}

.slider {
  position: absolute;
  left: 0;
  right: 0;
  width: 100%;
  opacity: 0;
  cursor: pointer;
  height: 100%;
  margin: 0;
}

.timeline-ticks {
  display: flex;
  align-items: flex-end;
  gap: 1px;
  overflow: hidden;
  position: relative;
}

.tick-button {
  flex: 1;
  min-width: 0;
  border: none;
  background: transparent;
  color: #64748b;
  font-family: 'JetBrains Mono', ui-monospace, SFMono-Regular, Roboto, monospace;
  font-size: var(--font-size-caption);
  padding: 0;
  border-radius: 0.2rem;
  cursor: pointer;
  transition: all 0.15s ease;
  display: flex;
  align-items: center;
  justify-content: center;
  height: 1.35rem;
}

.tick-label {
  display: block;
  line-height: 1;
  white-space: nowrap;
}

/* 次要刻度：不显示文字，仅显示细竖线 */
.tick-button.tick-minor {
  max-width: 6px;
  flex: 0.4;
}

.tick-bar {
  display: block;
  width: 1px;
  height: 0.5rem;
  background: rgba(148, 163, 184, 0.25);
  border-radius: 1px;
}

.tick-button.tick-minor:hover .tick-bar {
  background: rgba(148, 163, 184, 0.55);
  height: 0.65rem;
}

.tick-button.active,
.tick-button:hover {
  color: #f8fafc;
  background: rgba(255, 255, 255, 0.08);
}

.tick-button.active {
  color: #38bdf8;
  font-weight: 600;
  background: rgba(56, 189, 248, 0.12);
}

.tick-button.tick-minor.active .tick-bar,
.tick-button.tick-minor.active:hover .tick-bar {
  background: #38bdf8;
  width: 2px;
  height: 0.7rem;
}

/* 空数据刻度弱化 */
.tick-button.tick-empty {
  opacity: 0.4;
}

.tick-button.tick-error {
  color: #fca5a5;
}

/* 单位指示标签 */
.tick-unit-badge {
  flex: none;
  font-size: var(--font-size-caption);
  color: #64748b;
  background: rgba(30, 41, 59, 0.6);
  border: 1px solid rgba(100, 116, 139, 0.2);
  padding: 0.08rem 0.3rem;
  border-radius: 0.22rem;
  margin-left: 0.2rem;
  align-self: center;
  white-space: nowrap;
  letter-spacing: 0.04em;
}

.timeline-meta {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: var(--font-size-caption);
  color: #64748b;
  margin-top: 0.22rem;
  border-top: 1px solid rgba(255, 255, 255, 0.06);
  padding-top: 0.2rem;
}

.meta-text strong {
  color: #cbd5e1;
  font-weight: 500;
}
</style>

<style>
/* Teleport 到 body，需非 scoped */
.play-interval-menu {
  min-width: 9.2rem;
  padding: 0.35rem;
  border-radius: 0.55rem;
  border: 1px solid rgba(136, 192, 255, 0.28);
  background: linear-gradient(180deg, rgba(22, 34, 56, 0.96), rgba(12, 20, 36, 0.94));
  box-shadow: 0 12px 28px rgba(1, 8, 16, 0.45);
  backdrop-filter: blur(14px);
  color: #e2e8f0;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
}

.play-interval-menu-title {
  padding: 0.2rem 0.45rem 0.35rem;
  font-size: var(--font-size-caption);
  color: #94a3b8;
  letter-spacing: 0.04em;
}

.play-interval-option {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  width: 100%;
  border: none;
  border-radius: 0.35rem;
  background: transparent;
  color: #cbd5e1;
  font: inherit;
  font-size: var(--font-size-caption);
  padding: 0.32rem 0.45rem;
  cursor: pointer;
  text-align: left;
}

.play-interval-option:hover {
  background: rgba(56, 189, 248, 0.12);
  color: #f8fafc;
}

.play-interval-option.active {
  background: rgba(56, 189, 248, 0.18);
  color: #38bdf8;
}

.play-interval-check {
  width: 0.85rem;
  text-align: center;
  font-size: var(--font-size-caption);
  opacity: 0.9;
}
</style>
