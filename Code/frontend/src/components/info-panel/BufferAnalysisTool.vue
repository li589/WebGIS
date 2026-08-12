<script setup lang="ts">
import { computed, ref } from 'vue'

const props = defineProps<{
  pointLocation?: { lng: number; lat: number } | null
  currentValueText?: string
  currentNumericValue?: number | null
  layerName?: string
}>()

const radiusKm = ref(5)

const estimatedAreaKm2 = computed(() => {
  return (Math.PI * radiusKm.value * radiusKm.value).toFixed(1)
})

const centerValueLabel = computed(() => {
  if (props.currentValueText && props.currentValueText.trim()) return props.currentValueText
  if (typeof props.currentNumericValue === 'number' && Number.isFinite(props.currentNumericValue)) {
    return String(props.currentNumericValue)
  }
  return null
})
</script>

<template>
  <div class="buffer-tool-card">
    <div class="tool-head">
      <span class="tool-kicker">轻量分析工具</span>
      <h4>辐射缓冲区</h4>
      <p class="tool-note">仅计算几何覆盖面积（πr²），非栅格区域采样。</p>
    </div>

    <div class="radius-control">
      <div class="radius-label-row">
        <span>缓冲半径 (r)</span>
        <strong>{{ radiusKm }} km</strong>
      </div>
      <input
        v-model.number="radiusKm"
        type="range"
        min="1"
        max="50"
        step="1"
        class="radius-slider"
      />
      <div class="radius-ticks">
        <span>1 km</span>
        <span>25 km</span>
        <span>50 km</span>
      </div>
    </div>

    <div class="stats-grid">
      <div class="stat-box">
        <span class="stat-lbl">覆盖面积（估算）</span>
        <strong class="stat-val">{{ estimatedAreaKm2 }} km²</strong>
      </div>
      <div class="stat-box">
        <span class="stat-lbl">中心点</span>
        <strong class="stat-val mono">
          <template v-if="pointLocation">
            {{ pointLocation.lng.toFixed(3) }}, {{ pointLocation.lat.toFixed(3) }}
          </template>
          <template v-else>—</template>
        </strong>
      </div>
      <div v-if="centerValueLabel" class="stat-box stat-box--wide">
        <span class="stat-lbl">中心点当前值{{ layerName ? ` · ${layerName}` : '' }}</span>
        <strong class="stat-val">{{ centerValueLabel }}</strong>
      </div>
    </div>
  </div>
</template>

<style scoped>
.buffer-tool-card {
  margin-top: 0.55rem;
  padding: 0.55rem 0.6rem;
  border-radius: 0.65rem;
  border: 1px solid var(--border-default);
  background: var(--surface-raised);
}

.tool-head {
  display: grid;
  gap: 0.15rem;
  margin-bottom: 0.45rem;
}

.tool-kicker {
  font-size: var(--font-size-caption);
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--text-secondary);
}

.tool-head h4 {
  margin: 0;
  font-size: var(--font-size-caption);
  color: var(--text-primary);
}

.tool-note {
  margin: 0;
  font-size: var(--font-size-caption);
  color: var(--text-secondary);
  line-height: 1.35;
}

.radius-control {
  display: grid;
  gap: 0.28rem;
}

.radius-label-row {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  font-size: var(--font-size-caption);
  color: var(--text-secondary);
}

.radius-label-row strong {
  color: var(--accent);
  font-variant-numeric: tabular-nums;
}

.radius-slider {
  width: 100%;
  accent-color: var(--accent);
}

.radius-ticks {
  display: flex;
  justify-content: space-between;
  font-size: var(--font-size-caption);
  color: var(--text-secondary);
}

.stats-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0.35rem;
  margin-top: 0.5rem;
}

.stat-box {
  padding: 0.35rem 0.4rem;
  border-radius: 0.45rem;
  background: var(--surface-raised);
  border: 1px solid var(--border-subtle);
  display: grid;
  gap: 0.12rem;
}

.stat-box--wide {
  grid-column: 1 / -1;
}

.stat-lbl {
  font-size: var(--font-size-caption);
  color: var(--text-secondary);
}

.stat-val {
  font-size: var(--font-size-caption);
  color: var(--text-strong);
  font-weight: 600;
}

.stat-val.mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: var(--font-size-caption);
  font-weight: 500;
}
</style>
