<script setup lang="ts">
import { computed } from 'vue'

export interface OverlayBarItem {
  layerId: string
  name: string
  category?: string
  valueText: string
  numericValue: number | null
  unit?: string
  accentColor?: string
}

const props = defineProps<{
  items: OverlayBarItem[]
  title?: string
}>()

const maxNumeric = computed(() => {
  const nums = props.items.map((i) => (i.numericValue !== null ? Math.abs(i.numericValue) : 0))
  return Math.max(1, ...nums)
})
</script>

<template>
  <div class="multi-overlay-chart-card">
    <div class="chart-head">
      <span class="chart-title">{{ title || '多层共显提取对比' }}</span>
      <span class="chart-badge">{{ items.length }} 个共显层</span>
    </div>

    <ul class="bar-list">
      <li v-for="item in items" :key="item.layerId" class="bar-item">
        <div class="bar-meta">
          <span class="bar-name">{{ item.name }}</span>
          <span class="bar-val" :class="{ na: item.numericValue === null }">
            {{ item.valueText }}
          </span>
        </div>
        <div class="bar-track">
          <div
            class="bar-fill"
            :style="{
              width:
                item.numericValue !== null
                  ? `${Math.min(100, Math.max(5, (Math.abs(item.numericValue) / maxNumeric) * 100))}%`
                  : '0%',
              backgroundColor: item.accentColor || 'var(--accent)',
            }"
          ></div>
        </div>
      </li>
    </ul>
  </div>
</template>

<style scoped>
.multi-overlay-chart-card {
  background: var(--surface-1);
  backdrop-filter: blur(8px);
  border: 1px solid var(--surface-hover);
  border-radius: 10px;
  padding: 0.8rem;
  margin-top: 0.6rem;
}

.chart-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 0.6rem;
}

.chart-title {
  font-size: var(--font-size-caption);
  font-weight: 600;
  color: var(--text-strong);
}

.chart-badge {
  font-size: var(--font-size-caption);
  background: rgba(79, 195, 247, 0.15);
  color: var(--accent);
  padding: 0.15rem 0.45rem;
  border-radius: 4px;

  border: 1px solid rgba(79, 195, 247, 0.25);
}

.bar-list {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 0.55rem;
}

.bar-item {
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
}

.bar-meta {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: var(--font-size-caption);
}

.bar-name {
  color: var(--text-primary);
  font-weight: 500;
}

.bar-val {
  color: var(--success);
  font-weight: 600;

  font-family: var(--font-mono);
}

.bar-val.na {
  color: var(--text-muted);
}

.bar-track {
  width: 100%;
  height: 6px;
  background: var(--surface-hover);
  border-radius: 3px;
  overflow: hidden;
}

.bar-fill {
  height: 100%;
  border-radius: 3px;
  transition: width 0.4s cubic-bezier(0.4, 0, 0.2, 1);
}
</style>
