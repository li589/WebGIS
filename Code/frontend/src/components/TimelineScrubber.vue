<script setup lang="ts">
import { computed } from 'vue'

type TimelineAvailabilitySegment = {
  hour: number
  label: string
  state: 'empty' | 'partial' | 'ready'
  availabilityLabel: string
}

const props = defineProps<{
  currentHour: number
  hourLabel: string
  accentColor: string
  availabilityLabel: string
  observationTimeLabel: string
  timelineSegments: TimelineAvailabilitySegment[]
}>()

const emit = defineEmits<{
  step: [delta: number]
  changeHour: [hour: number]
}>()

const progressPercent = computed(() => `${((props.currentHour / 23) * 100).toFixed(1)}%`)
const liveLabel = computed(() => `24h · ${props.availabilityLabel}`)
const phaseLabel = computed(() => {
  if (props.currentHour < 6) return '夜间'
  if (props.currentHour < 11) return '上午'
  if (props.currentHour < 17) return '午后'
  if (props.currentHour < 20) return '傍晚'
  return '夜间'
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
</script>

<template>
  <section class="timeline" :style="trackStyle">
    <div class="timeline-main">
      <div class="timeline-heading">
        <span class="timeline-kicker">时间推进</span>
        <strong>{{ hourLabel }}</strong>
        <div class="timeline-highlights">
          <span class="timeline-live">{{ liveLabel }}</span>
          <span class="inline-pill">{{ phaseLabel }}</span>
          <span class="inline-pill inline-pill--accent">{{ nearestSegment.availabilityLabel }}</span>
        </div>
      </div>

      <div class="timeline-actions" aria-label="时间轴快捷控制">
        <button class="ghost-button ghost-button--step" type="button" title="前 1 小时" @click="emit('step', -1)">
          <span class="ghost-icon" aria-hidden="true">←</span>
          <span>前 1h</span>
        </button>
        <button class="ghost-button ghost-button--step" type="button" title="后 1 小时" @click="emit('step', 1)">
          <span>后 1h</span>
          <span class="ghost-icon" aria-hidden="true">→</span>
        </button>
      </div>
    </div>

    <div class="timeline-track">
      <div class="availability-caption">
        <span>数据可用性</span>
        <strong>{{ nearestSegment.label }} · {{ nearestSegment.availabilityLabel }}</strong>
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

    <div class="timeline-meta">
      <span class="meta-text meta-text--left">阶段 <strong>{{ phaseLabel }}</strong></span>
      <span class="meta-text meta-text--center">进度 <strong>{{ progressPercent }}</strong></span>
      <span class="meta-text meta-text--right">观测时次 <strong>{{ observationTimeLabel }}</strong></span>
    </div>
  </section>
</template>

<style scoped>
.timeline {
  padding: 0.18rem 0.24rem 0.24rem;
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

.timeline-main { display: grid; grid-template-columns: minmax(0, 1fr) auto; align-items: start; gap: 0.4rem; }
.timeline-heading { display: grid; gap: 0.1rem; min-width: 0; }
.timeline-kicker { color: #8095ab; font-size: 0.52rem; text-transform: uppercase; letter-spacing: 0.1em; }
.timeline-heading strong { font-size: 0.96rem; color: #f2f8ff; letter-spacing:.01em; line-height: 1; }
.timeline-highlights { display: flex; flex-wrap: wrap; gap: 0.28rem; align-items: center; }
.timeline-live { color: #91aac0; font-size: 0.58rem; }
.inline-pill { display: inline-flex; align-items: center; padding: 0.16rem 0.42rem; border-radius: 999px; border: 1px solid rgba(136, 192, 255, 0.14); background: rgba(255,255,255,0.035); color: #cfe0f2; font-size: 0.55rem; }
.inline-pill--accent { border-color: rgba(90,162,255,.24); background: rgba(90,162,255,.1); color: #f2f8ff; }
.timeline-actions { display: inline-flex; gap: 0.28rem; align-items: center; }
.ghost-button { border: 1px solid rgba(136, 192, 255, 0.2); border-radius: 999px; min-width: 3.45rem; padding: 0.32rem 0.54rem; background: linear-gradient(180deg, rgba(14, 28, 49, 0.9), rgba(8, 18, 33, 0.72)); color: #dce8f4; cursor: pointer; font: inherit; font-size: 0.6rem; transition: border-color 0.2s ease, color 0.2s ease, transform 0.2s cubic-bezier(0.25, 0.46, 0.45, 0.94), background-color .2s ease, box-shadow .2s ease; }
.ghost-button--step { display: inline-flex; align-items: center; justify-content: center; gap: 0.3rem; box-shadow: 0 8px 18px rgba(1,8,16,.08); }
.ghost-icon { font-size: 0.72rem; line-height: 1; }
.ghost-button:hover { border-color: rgba(136, 192, 255, 0.34); color: #f4fbff; transform: translateY(-1px); box-shadow: 0 10px 24px rgba(1,8,16,.14); }
.timeline-track { position: relative; margin-top: 0.28rem; padding: 0.52rem 0.58rem 0.56rem; border-radius: 0.92rem; border: 1px solid rgba(136, 192, 255, 0.08); background: linear-gradient(180deg, rgba(6,14,26,.18), rgba(255,255,255,.02)); }
.availability-caption { display: flex; justify-content: space-between; align-items: center; gap: 0.45rem; margin-bottom: 0.12rem; color: #8da3b8; font-size: 0.5rem; letter-spacing:.06em; }
.availability-caption strong { font-size: 0.52rem; }
.availability-strip { display: grid; grid-template-columns: repeat(8, minmax(0, 1fr)); gap: 0.08rem; margin-bottom: 0.16rem; }
.availability-segment { height: 0.18rem; border-radius: 999px; opacity: 0.9; box-shadow: inset 0 0 0 1px rgba(255,255,255,0.04); }
.availability-ready { background: rgba(114, 255, 207, 0.92); }
.availability-partial { background: rgba(255, 196, 120, 0.9); }
.availability-empty { background: rgba(187, 137, 255, 0.82); }
.track-interactive { position: relative; margin-top: 0.02rem; padding: 0.24rem 0; }
.track-shell { position: relative; height: 0.42rem; border-radius: 999px; overflow: visible; background: rgba(255, 255, 255, 0.06); border: 1px solid rgba(136, 192, 255, 0.12); }
.track-fill, .track-buffer, .track-thumb { position: absolute; top: 0; bottom: 0; }
.track-fill { left: 0; width: var(--track-progress); background: linear-gradient(90deg, rgba(45, 110, 212, 0.22), var(--accent-color)); border-radius: 999px; }
.track-buffer { left: var(--track-progress); width: calc(100% - var(--track-progress)); background: linear-gradient(90deg, rgba(255, 255, 255, 0.1), rgba(255, 255, 255, 0.03)); border-radius: 0 999px 999px 0; }
.track-thumb { left: var(--track-progress); width: 0.76rem; height: 0.76rem; top: 50%; border-radius: 999px; background: #f7fbff; border: 1.5px solid rgba(90, 162, 255, 0.64); box-shadow: 0 0 0 5px rgba(90, 162, 255, 0.14); transform: translate(-50%, -50%); z-index: 1; will-change: left; }
.track-scale { display: flex; justify-content: space-between; align-items: center; margin-top: 0.12rem; color: #73889c; font-size: 0.5rem; letter-spacing: 0.04em; }
.slider { position: absolute; inset: 0; width: 100%; height: 100%; margin: 0; opacity: 0; cursor: pointer; z-index: 2; }
.timeline-ticks { display: grid; grid-template-columns: repeat(8, minmax(0, 1fr)); gap: 0.22rem; margin-top: 0.24rem; }
.tick-button { border: 1px solid transparent; padding: 0.26rem 0.12rem; border-radius: 0.62rem; background: rgba(255,255,255,0.025); color: #7f97ad; cursor: pointer; font: inherit; font-size: 0.56rem; text-align: center; transition: color 0.2s ease, border-color .2s ease, background-color .2s ease, transform .2s ease; }
.tick-button.active, .tick-button:hover { color: #f3fbff; transform: translateY(-1px); }
.tick-button.active { border-color: rgba(136,192,255,.2); background: rgba(90,162,255,.12); box-shadow: inset 0 1px 0 rgba(255,255,255,.05); }
.tick-ready { color: #a6f4d1; }
.tick-partial { color: #ffd38a; }
.tick-empty { color: #d5c0ff; }
.timeline-meta { display: grid; grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr); align-items: center; gap: 0.5rem; margin-top: 0.22rem; color: #8ba1b7; font-size: 0.6rem; }
.meta-text { display: inline-flex; align-items: center; gap: 0.24rem; min-width: 0; white-space: nowrap; }
.meta-text strong { color: #eef6ff; font-size: 0.64rem; font-weight: 600; white-space: nowrap; }
.meta-text--left { justify-self: start; }
.meta-text--center { justify-self: center; text-align: center; }
.meta-text--right { justify-self: end; }
@media (max-width: 700px) {
  .timeline { padding: 0.14rem 0.14rem 0.18rem; }
  .timeline-main { grid-template-columns: 1fr; }
  .timeline-actions { justify-content: stretch; }
  .ghost-button { flex: 1 1 0; min-width: 0; }
  .timeline-track { padding: 0.46rem 0.42rem 0.5rem; }
  .timeline-ticks { grid-template-columns: repeat(4, minmax(0, 1fr)); }
  .timeline-meta { grid-template-columns: 1fr; gap: 0.18rem; }
  .meta-text--left,
  .meta-text--center,
  .meta-text--right { justify-self: start; text-align: left; }
}
</style>
