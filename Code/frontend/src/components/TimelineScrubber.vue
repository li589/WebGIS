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
const liveLabel = computed(() => `${props.hourLabel} / 24h`)
const phaseLabel = computed(() => {
  if (props.currentHour < 6) return '夜间'
  if (props.currentHour < 11) return '上午'
  if (props.currentHour < 17) return '午后'
  if (props.currentHour < 20) return '傍晚'
  return '夜间'
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
        <p class="timeline-label">时间轴</p>
        <strong>{{ hourLabel }}</strong>
        <span class="timeline-live">{{ liveLabel }}</span>
      </div>

      <div class="timeline-actions">
        <button class="ghost-button" type="button" title="前 1 小时" @click="emit('step', -1)">
          <span aria-hidden="true">-1h</span>
        </button>
        <button class="ghost-button" type="button" title="后 1 小时" @click="emit('step', 1)">
          <span aria-hidden="true">+1h</span>
        </button>
      </div>
    </div>

    <div class="timeline-track">
      <div class="availability-caption">
        <span>全天可用性</span>
        <strong>{{ availabilityLabel }}</strong>
      </div>
      <div class="availability-strip" aria-hidden="true">
        <span
          v-for="segment in timelineSegments"
          :key="segment.hour"
          class="availability-segment"
          :class="`availability-${segment.state}`"
        ></span>
      </div>
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
      <span>{{ phaseLabel }}</span>
      <strong>{{ progressPercent }}</strong>
      <span>{{ observationTimeLabel }} · 连续定位</span>
    </div>
  </section>
</template>

<style scoped>
.timeline {
  padding: 0.72rem 0.8rem 0.8rem;
  border-radius: 1rem;
  border: 1px solid rgba(148, 163, 184, 0.15);
  background: rgba(10, 18, 33, 0.74);
  backdrop-filter: blur(12px);
  box-shadow: 0 14px 30px rgba(1, 8, 16, 0.2);
}

.timeline-main {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 0.75rem;
}

.timeline-heading {
  display: grid;
  gap: 0.18rem;
}

.timeline-label {
  margin: 0;
  color: #8095ab;
  font-size: 0.68rem;
  text-transform: uppercase;
  letter-spacing: 0.08em;
}

strong {
  font-size: 0.92rem;
  color: #f2f8ff;
}

.timeline-live {
  color: #87a1b8;
  font-size: 0.7rem;
}

.timeline-actions {
  display: inline-flex;
  gap: 0.4rem;
}

.ghost-button {
  border: 1px solid rgba(136, 192, 255, 0.2);
  border-radius: 999px;
  min-width: 3.1rem;
  padding: 0.34rem 0.56rem;
  background: rgba(8, 18, 33, 0.84);
  color: #dce8f4;
  cursor: pointer;
  font: inherit;
  font-size: 0.72rem;
  /* 性能优化：仅 GPU 属性的过渡，避免触发重排 */
  transition: border-color 0.2s ease, color 0.2s ease, transform 0.2s cubic-bezier(0.25, 0.46, 0.45, 0.94);
}

.ghost-button:hover {
  border-color: rgba(136, 192, 255, 0.34);
  color: #f4fbff;
  transform: translateY(-1px);
}

.timeline-track {
  position: relative;
  margin-top: 0.72rem;
}

.availability-caption {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 0.6rem;
  margin-bottom: 0.28rem;
  color: #8da3b8;
  font-size: 0.6rem;
}

.availability-caption strong {
  font-size: 0.64rem;
}

.availability-strip {
  display: grid;
  grid-template-columns: repeat(8, minmax(0, 1fr));
  gap: 0.18rem;
  margin-bottom: 0.34rem;
}

.availability-segment {
  height: 0.22rem;
  border-radius: 999px;
  opacity: 0.9;
}

.availability-ready {
  background: rgba(114, 255, 207, 0.92);
}

.availability-partial {
  background: rgba(255, 196, 120, 0.9);
}

.availability-empty {
  background: rgba(187, 137, 255, 0.82);
}

.track-shell {
  position: relative;
  height: 0.56rem;
  border-radius: 999px;
  overflow: hidden;
  background: rgba(255, 255, 255, 0.06);
  border: 1px solid rgba(136, 192, 255, 0.12);
}

.track-fill,
.track-buffer,
.track-thumb {
  position: absolute;
  top: 0;
  bottom: 0;
}

.track-fill {
  left: 0;
  width: var(--track-progress);
  background: linear-gradient(90deg, rgba(45, 110, 212, 0.22), var(--accent-color));
}

.track-buffer {
  left: var(--track-progress);
  width: calc(100% - var(--track-progress));
  background: linear-gradient(90deg, rgba(255, 255, 255, 0.1), rgba(255, 255, 255, 0.03));
}

.track-thumb {
  left: var(--track-progress);
  width: 1rem;
  height: 1rem;
  top: 50%;
  border-radius: 999px;
  background: #f7fbff;
  border: 2px solid rgba(90, 162, 255, 0.64);
  box-shadow: 0 0 0 8px rgba(90, 162, 255, 0.22);
  transform: translate(-50%, -50%);
  z-index: 0;
  will-change: left;
  /* 性能优化：GPU 加速 */
  translate: -50% -50%;
}

.slider {
  position: absolute;
  left: 0;
  right: 0;
  top: 50%;
  height: 1.5rem;
  margin: 0;
  transform: translateY(-50%);
  opacity: 0;
  cursor: pointer;
  /* Expand hit area to cover the thumb without extending beyond track ends */
  z-index: 1;
}

.timeline-ticks {
  display: flex;
  justify-content: space-between;
  gap: 0.4rem;
  margin-top: 0.54rem;
}

.tick-button {
  border: none;
  padding: 0;
  background: transparent;
  color: #7f97ad;
  cursor: pointer;
  font: inherit;
  font-size: 0.66rem;
  transition: color 0.2s ease;
}

.tick-button.active,
.tick-button:hover {
  color: #f3fbff;
}

.tick-ready {
  color: #a6f4d1;
}

.tick-partial {
  color: #ffd38a;
}

.tick-empty {
  color: #d5c0ff;
}

.timeline-meta {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 0.6rem;
  margin-top: 0.58rem;
  color: #8ba1b7;
  font-size: 0.7rem;
}

.timeline-meta strong {
  font-size: 0.74rem;
}

@media (max-width: 700px) {
  .timeline-main {
    flex-direction: column;
    align-items: flex-start;
  }

  .timeline-ticks {
    overflow-x: auto;
    padding-bottom: 0.15rem;
  }
}
</style>
