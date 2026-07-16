<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'

type TimelineAvailabilitySegment = {
  hour: number
  label: string
  state: 'empty' | 'partial' | 'ready'
  availabilityLabel: string
}

const props = defineProps<{
  currentHour: number
  currentDate: Date
  hourLabel: string
  accentColor: string
  availabilityLabel: string
  observationTimeLabel: string
  timelineSegments: TimelineAvailabilitySegment[]
  isPlaying?: boolean
}>()

const emit = defineEmits<{
  step: [delta: number]
  changeHour: [hour: number]
  changeDate: [date: Date]
  togglePlay: []
}>()

// ── 日期格式化 ────────────────────────────────────────────────
const dateString = computed(() => {
  const d = props.currentDate
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
})

const weekdayLabel = computed(() => {
  const weekdays = ['周日', '周一', '周二', '周三', '周四', '周五', '周六']
  return weekdays[props.currentDate.getDay()]
})

const dateInputValue = computed(() => dateString.value)

const isToday = computed(() => {
  const today = new Date()
  return (
    props.currentDate.getFullYear() === today.getFullYear() &&
    props.currentDate.getMonth() === today.getMonth() &&
    props.currentDate.getDate() === today.getDate()
  )
})

// ── 时间/进度 ─────────────────────────────────────────────────
const progressPercent = computed(() => `${((props.currentHour / 23) * 100).toFixed(1)}%`)
const liveLabel = computed(() => `${props.availabilityLabel}`)
const phaseLabel = computed(() => {
  if (props.currentHour < 6) return '夜间'
  if (props.currentHour < 11) return '上午'
  if (props.currentHour < 17) return '午后'
  if (props.currentHour < 20) return '傍晚'
  return '夜间'
})
const phaseIcon = computed(() => {
  if (props.currentHour < 6) return '🌙'
  if (props.currentHour < 11) return '🌅'
  if (props.currentHour < 17) return '☀️'
  if (props.currentHour < 20) return '🌇'
  return '🌙'
})

const nearestSegment = computed(() => {
  return props.timelineSegments.reduce((closest, segment) => {
    return Math.abs(segment.hour - props.currentHour) < Math.abs(closest.hour - props.currentHour) ? segment : closest
  }, props.timelineSegments[0] ?? { hour: 0, label: '00:00', state: 'empty' as const, availabilityLabel: '空状态' })
})

const trackStyle = computed(() => ({
  '--track-progress': progressPercent.value,
  '--accent-color': props.accentColor,
}))

// ── 日期导航 ──────────────────────────────────────────────────
function shiftDate(days: number) {
  const d = new Date(props.currentDate)
  d.setDate(d.getDate() + days)
  emit('changeDate', d)
}

function onDateInput(event: Event) {
  const value = (event.target as HTMLInputElement).value
  if (!value) return
  const [y, m, d] = value.split('-').map(Number)
  if (!y || !m || !d) return
  const newDate = new Date(props.currentDate)
  newDate.setFullYear(y, m - 1, d)
  emit('changeDate', newDate)
}

// ── 播放控制 ──────────────────────────────────────────────────
const playing = computed(() => props.isPlaying ?? false)
const playInterval = ref<number | null>(null)

watch(playing, (isPlaying) => {
  if (isPlaying && playInterval.value === null) {
    playInterval.value = window.setInterval(() => {
      emit('step', 1)
    }, 2000)
  } else if (!isPlaying && playInterval.value !== null) {
    window.clearInterval(playInterval.value)
    playInterval.value = null
  }
})

onBeforeUnmount(() => {
  if (playInterval.value !== null) {
    window.clearInterval(playInterval.value)
    playInterval.value = null
  }
})

// ── 快捷跳转 ──────────────────────────────────────────────────
function jumpToNow() {
  const now = new Date()
  emit('changeDate', now)
  emit('changeHour', now.getHours())
}
</script>

<template>
  <section class="timeline" :style="trackStyle">
    <!-- 顶部：日期导航 + 时间标题 + 播放 -->
    <div class="timeline-top">
      <div class="date-nav">
        <button class="nav-btn" type="button" title="前一天" @click="shiftDate(-1)">
          <svg viewBox="0 0 16 16" aria-hidden="true"><path d="M10 3 5 8l5 5" /></svg>
        </button>
        <label class="date-display" :title="isToday ? '今天' : '点击选择日期'">
          <span class="date-text">{{ dateString }}</span>
          <span class="date-weekday">{{ weekdayLabel }}</span>
          <span v-if="isToday" class="date-today-badge">今</span>
          <input
            class="date-picker-hidden"
            type="date"
            :value="dateInputValue"
            @change="onDateInput"
          />
        </label>
        <button class="nav-btn" type="button" title="后一天" @click="shiftDate(1)">
          <svg viewBox="0 0 16 16" aria-hidden="true"><path d="M6 3l5 5-5 5" /></svg>
        </button>
        <button class="nav-btn nav-btn--now" type="button" title="跳转到当前时刻" @click="jumpToNow">
          <svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="5.5" /><path d="M8 5v3l2 1.5" /></svg>
        </button>
      </div>

      <div class="time-heading">
        <span class="time-kicker">时刻</span>
        <strong class="time-value">{{ hourLabel }}</strong>
        <span class="time-phase">{{ phaseIcon }} {{ phaseLabel }}</span>
      </div>

      <div class="top-actions">
        <button
          class="play-btn"
          :class="{ 'play-btn--playing': playing }"
          type="button"
          :title="playing ? '暂停' : '播放'"
          @click="emit('togglePlay')"
        >
          <svg v-if="!playing" viewBox="0 0 16 16" aria-hidden="true"><path d="M4 2.5v11l9-5.5z" /></svg>
          <svg v-else viewBox="0 0 16 16" aria-hidden="true"><rect x="3.5" y="3" width="3" height="10" rx="0.5" /><rect x="9.5" y="3" width="3" height="10" rx="0.5" /></svg>
        </button>
        <div class="step-group">
          <button class="step-btn" type="button" title="前 1 小时" @click="emit('step', -1)">
            <svg viewBox="0 0 16 16" aria-hidden="true"><path d="M10 3 5 8l5 5" /></svg>
          </button>
          <button class="step-btn" type="button" title="后 1 小时" @click="emit('step', 1)">
            <svg viewBox="0 0 16 16" aria-hidden="true"><path d="M6 3l5 5-5 5" /></svg>
          </button>
        </div>
      </div>
    </div>

    <!-- 中部：数据可用性 + 滑块 + 刻度 -->
    <div class="timeline-track">
      <div class="availability-caption">
        <span>数据可用性</span>
        <strong>{{ nearestSegment.label }} · {{ nearestSegment.availabilityLabel }}</strong>
        <span class="availability-live">{{ liveLabel }}</span>
      </div>
      <div class="availability-strip" aria-hidden="true">
        <span
          v-for="segment in timelineSegments"
          :key="segment.hour"
          class="availability-segment"
          :class="`availability-${segment.state}`"
        ></span>
      </div>
      <div class="track-interactive">
        <div class="track-shell">
          <div class="track-fill" aria-hidden="true"></div>
          <div class="track-buffer" aria-hidden="true"></div>
          <div class="track-thumb" aria-hidden="true"></div>
        </div>
        <input
          class="slider"
          type="range"
          min="0"
          max="23"
          step="0.25"
          :value="currentHour"
          @input="emit('changeHour', Number(($event.target as HTMLInputElement).value))"
        />
      </div>
      <div class="track-scale" aria-hidden="true">
        <span>00:00</span>
        <span>06:00</span>
        <span>12:00</span>
        <span>18:00</span>
        <span>23:00</span>
      </div>

      <div class="timeline-ticks">
        <button
          v-for="tick in timelineSegments"
          :key="tick.hour"
          class="tick-button"
          type="button"
          :class="[`tick-${tick.state}`, { active: Math.abs(currentHour - tick.hour) < 0.5 }]"
          :title="`${tick.label} · ${tick.availabilityLabel}`"
          @click="emit('changeHour', tick.hour)"
        >
          {{ tick.label }}
        </button>
      </div>
    </div>

    <!-- 底部：元信息 -->
    <div class="timeline-meta">
      <span class="meta-text meta-text--left">阶段 <strong>{{ phaseLabel }}</strong></span>
      <span class="meta-text meta-text--center">进度 <strong>{{ progressPercent }}</strong></span>
      <span class="meta-text meta-text--right">观测时次 <strong>{{ observationTimeLabel }}</strong></span>
    </div>
  </section>
</template>

<style scoped>
.timeline {
  padding: 0.22rem 0.28rem 0.18rem;
  border-radius: 0.9rem;
  background:
    radial-gradient(circle at 18% 0%, rgba(90,162,255,.12), transparent 34%),
    linear-gradient(180deg, rgba(255,255,255,.025), rgba(255,255,255,0));
  width: 100%;
  max-width: none;
  margin: 0;
  min-height: 0;
  box-sizing: border-box;
}

/* ── 顶部区域 ──────────────────────────────────────────────── */
.timeline-top {
  display: grid;
  grid-template-columns: 1fr auto 1fr;
  align-items: center;
  gap: 0.5rem;
  margin-bottom: 0.18rem;
}

/* 日期导航 */
.date-nav {
  display: inline-flex;
  align-items: center;
  gap: 0.18rem;
  padding: 0.16rem 0.2rem;
  border-radius: 0.72rem;
  border: 1px solid rgba(136, 192, 255, 0.12);
  background: linear-gradient(180deg, rgba(14, 28, 49, 0.5), rgba(8, 18, 33, 0.36));
  justify-self: start;
}
.nav-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 1.4rem;
  height: 1.4rem;
  border: 1px solid transparent;
  border-radius: 0.5rem;
  background: transparent;
  color: #b0c4d8;
  cursor: pointer;
  transition: color 0.18s ease, background-color 0.18s ease, border-color 0.18s ease;
}
.nav-btn:hover {
  color: #f4fbff;
  background: rgba(90, 162, 255, 0.12);
  border-color: rgba(136, 192, 255, 0.2);
}
.nav-btn--now {
  width: 1.55rem;
  margin-left: 0.1rem;
  border-left: 1px solid rgba(136, 192, 255, 0.1);
  border-radius: 0 0.5rem 0.5rem 0;
}
.nav-btn svg {
  width: 0.72rem;
  height: 0.72rem;
  fill: none;
  stroke: currentColor;
  stroke-width: 1.6;
  stroke-linecap: round;
  stroke-linejoin: round;
}
.nav-btn--now svg {
  fill: none;
  stroke: currentColor;
  stroke-width: 1.4;
}

.date-display {
  display: inline-flex;
  align-items: center;
  gap: 0.28rem;
  padding: 0.12rem 0.36rem;
  border-radius: 0.48rem;
  cursor: pointer;
  position: relative;
  transition: background-color 0.18s ease;
}
.date-display:hover {
  background: rgba(90, 162, 255, 0.08);
}
.date-text {
  color: #eef6ff;
  font-size: 0.66rem;
  font-weight: 600;
  letter-spacing: 0.02em;
  white-space: nowrap;
}
.date-weekday {
  color: #8095ab;
  font-size: 0.52rem;
}
.date-today-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 0.8rem;
  height: 0.8rem;
  border-radius: 999px;
  background: rgba(90, 162, 255, 0.22);
  color: #cfe0f2;
  font-size: 0.46rem;
  font-weight: 700;
}
.date-picker-hidden {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  opacity: 0;
  cursor: pointer;
  color-scheme: dark;
}

/* 时间标题 */
.time-heading {
  display: flex;
  align-items: baseline;
  gap: 0.36rem;
  justify-content: center;
  min-width: 0;
}
.time-kicker {
  color: #8095ab;
  font-size: 0.5rem;
  text-transform: uppercase;
  letter-spacing: 0.1em;
}
.time-value {
  font-size: 1.08rem;
  color: #f2f8ff;
  letter-spacing: 0.01em;
  line-height: 1;
  font-variant-numeric: tabular-nums;
}
.time-phase {
  color: #91aac0;
  font-size: 0.58rem;
  white-space: nowrap;
}

/* 顶部操作按钮 */
.top-actions {
  display: inline-flex;
  align-items: center;
  gap: 0.32rem;
  justify-self: end;
}
.play-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 1.7rem;
  height: 1.7rem;
  border: 1px solid rgba(136, 192, 255, 0.22);
  border-radius: 999px;
  background: linear-gradient(180deg, rgba(90, 162, 255, 0.18), rgba(45, 110, 212, 0.1));
  color: #cfe0f2;
  cursor: pointer;
  transition: all 0.2s ease;
  box-shadow: 0 4px 12px rgba(1, 8, 16, 0.1);
}
.play-btn:hover {
  border-color: rgba(136, 192, 255, 0.4);
  color: #f4fbff;
  transform: translateY(-1px);
  box-shadow: 0 6px 16px rgba(90, 162, 255, 0.18);
}
.play-btn--playing {
  background: linear-gradient(180deg, rgba(90, 162, 255, 0.3), rgba(45, 110, 212, 0.18));
  border-color: rgba(90, 162, 255, 0.5);
  color: #f4fbff;
  box-shadow: 0 0 0 3px rgba(90, 162, 255, 0.12), 0 4px 12px rgba(1, 8, 16, 0.1);
}
.play-btn svg {
  width: 0.76rem;
  height: 0.76rem;
  fill: currentColor;
}

.step-group {
  display: inline-flex;
  gap: 0.14rem;
  padding: 0.14rem;
  border-radius: 0.6rem;
  border: 1px solid rgba(136, 192, 255, 0.12);
  background: rgba(8, 18, 33, 0.42);
}
.step-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 1.32rem;
  height: 1.32rem;
  border: none;
  border-radius: 0.42rem;
  background: transparent;
  color: #b0c4d8;
  cursor: pointer;
  transition: all 0.18s ease;
}
.step-btn:hover {
  color: #f4fbff;
  background: rgba(90, 162, 255, 0.14);
}
.step-btn svg {
  width: 0.66rem;
  height: 0.66rem;
  fill: none;
  stroke: currentColor;
  stroke-width: 1.8;
  stroke-linecap: round;
  stroke-linejoin: round;
}

/* ── 轨道区域 ──────────────────────────────────────────────── */
.timeline-track {
  position: relative;
  margin-top: 0.22rem;
  padding: 0.48rem 0.56rem 0.52rem;
  border-radius: 0.82rem;
  border: 1px solid rgba(136, 192, 255, 0.08);
  background: linear-gradient(180deg, rgba(6, 14, 26, 0.18), rgba(255, 255, 255, 0.02));
}
.availability-caption {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 0.4rem;
  margin-bottom: 0.12rem;
  color: #8da3b8;
  font-size: 0.5rem;
  letter-spacing: 0.06em;
}
.availability-caption strong {
  font-size: 0.52rem;
  color: #cfe0f2;
}
.availability-live {
  color: #91aac0;
  font-size: 0.5rem;
}
.availability-strip {
  display: grid;
  grid-template-columns: repeat(8, minmax(0, 1fr));
  gap: 0.08rem;
  margin-bottom: 0.16rem;
}
.availability-segment {
  height: 0.16rem;
  border-radius: 999px;
  opacity: 0.9;
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.04);
}
.availability-ready { background: rgba(114, 255, 207, 0.92); }
.availability-partial { background: rgba(255, 196, 120, 0.9); }
.availability-empty { background: rgba(187, 137, 255, 0.82); }

.track-interactive {
  position: relative;
  margin-top: 0.02rem;
  padding: 0.24rem 0;
}
.track-shell {
  position: relative;
  height: 0.42rem;
  border-radius: 999px;
  overflow: visible;
  background: rgba(255, 255, 255, 0.06);
  border: 1px solid rgba(136, 192, 255, 0.12);
}
.track-fill, .track-buffer, .track-thumb {
  position: absolute;
  top: 0;
  bottom: 0;
}
.track-fill {
  left: 0;
  width: var(--track-progress);
  background: linear-gradient(90deg, rgba(45, 110, 212, 0.22), var(--accent-color));
  border-radius: 999px;
}
.track-buffer {
  left: var(--track-progress);
  width: calc(100% - var(--track-progress));
  background: linear-gradient(90deg, rgba(255, 255, 255, 0.1), rgba(255, 255, 255, 0.03));
  border-radius: 0 999px 999px 0;
}
.track-thumb {
  left: var(--track-progress);
  width: 0.76rem;
  height: 0.76rem;
  top: 50%;
  border-radius: 999px;
  background: #f7fbff;
  border: 1.5px solid rgba(90, 162, 255, 0.64);
  box-shadow: 0 0 0 5px rgba(90, 162, 255, 0.14);
  transform: translate(-50%, -50%);
  z-index: 1;
  will-change: left;
}
.track-scale {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 0.12rem;
  color: #73889c;
  font-size: 0.48rem;
  letter-spacing: 0.04em;
}
.slider {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  margin: 0;
  opacity: 0;
  cursor: pointer;
  z-index: 2;
}
.timeline-ticks {
  display: grid;
  grid-template-columns: repeat(8, minmax(0, 1fr));
  gap: 0.22rem;
  margin-top: 0.22rem;
}
.tick-button {
  border: 1px solid transparent;
  padding: 0.24rem 0.1rem;
  border-radius: 0.58rem;
  background: rgba(255, 255, 255, 0.025);
  color: #7f97ad;
  cursor: pointer;
  font: inherit;
  font-size: 0.54rem;
  text-align: center;
  transition: color 0.2s ease, border-color 0.2s ease, background-color 0.2s ease, transform 0.2s ease;
}
.tick-button.active, .tick-button:hover {
  color: #f3fbff;
  transform: translateY(-1px);
}
.tick-button.active {
  border-color: rgba(136, 192, 255, 0.2);
  background: rgba(90, 162, 255, 0.12);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.05);
}
.tick-ready { color: #a6f4d1; }
.tick-partial { color: #ffd38a; }
.tick-empty { color: #d5c0ff; }

/* ── 底部元信息 ────────────────────────────────────────────── */
.timeline-meta {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr);
  align-items: center;
  gap: 0.5rem;
  margin-top: 0.12rem;
  color: #8ba1b7;
  font-size: 0.58rem;
}
.meta-text {
  display: inline-flex;
  align-items: center;
  gap: 0.24rem;
  min-width: 0;
  white-space: nowrap;
}
.meta-text strong {
  color: #eef6ff;
  font-size: 0.62rem;
  font-weight: 600;
  white-space: nowrap;
}
.meta-text--left { justify-self: start; }
.meta-text--center { justify-self: center; text-align: center; }
.meta-text--right { justify-self: end; }

/* ── 响应式 ────────────────────────────────────────────────── */
@media (max-width: 700px) {
  .timeline { padding: 0.16rem 0.16rem 0.2rem; }
  .timeline-top {
    grid-template-columns: 1fr;
    gap: 0.3rem;
  }
  .time-heading { justify-content: flex-start; }
  .top-actions { justify-self: flex-start; }
  .timeline-track { padding: 0.42rem 0.38rem 0.46rem; }
  .timeline-ticks { grid-template-columns: repeat(4, minmax(0, 1fr)); }
  .timeline-meta {
    grid-template-columns: 1fr;
    gap: 0.16rem;
  }
  .meta-text--left,
  .meta-text--center,
  .meta-text--right { justify-self: start; text-align: left; }
}
</style>
