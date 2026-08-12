<script setup lang="ts">
/**
 * Legacy BufferAnalysisTool — superseded by InfoPanelToolsTab GIS panel.
 * Kept as a thin compatibility stub so older imports do not break.
 * Prefer the panel `gis.buffer` tool which submits a real workflow-run.
 */
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
      <span class="tool-kicker">已迁移</span>
      <h4>辐射缓冲区</h4>
      <p class="tool-note">
        请使用上方「缓冲区」分析工具提交真实 GIS 缓冲；此处仅保留 πr² 面积提示。
      </p>
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
}
.tool-note {
  margin: 0;
  font-size: var(--font-size-caption);
  color: var(--text-secondary);
}
.radius-control {
  margin: 0.4rem 0;
}
.radius-label-row {
  display: flex;
  justify-content: space-between;
  font-size: var(--font-size-caption);
}
.radius-slider {
  width: 100%;
}
.stats-grid {
  display: grid;
  gap: 0.35rem;
}
.stat-box {
  padding: 0.35rem 0.45rem;
  border-radius: 0.45rem;
  border: 1px solid var(--border-default);
}
.stat-box--wide {
  grid-column: 1 / -1;
}
.stat-lbl {
  display: block;
  font-size: var(--font-size-caption);
  color: var(--text-secondary);
}
.stat-val {
  font-size: var(--font-size-body);
}
.mono {
  font-variant-numeric: tabular-nums;
}
</style>
