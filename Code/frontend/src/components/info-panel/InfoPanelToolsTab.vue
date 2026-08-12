/** * InfoPanel 工具 Tab：选择模式入口 + 缓冲分析。 * * 从 InfoPanel.vue 模板抽取（原 1665-1706
行）。纯展示组件。 */
<script setup lang="ts">
import type { ActiveLayerDisplay } from '../../stores/layers/types'
import { ANALYSIS_COPY } from '../../ui-copy'
import BufferAnalysisTool from './BufferAnalysisTool.vue'

defineProps<{
  displayLayer: ActiveLayerDisplay
  selectedMapPoint: { lng: number; lat: number } | null
  pointWeather: unknown
  pointWeatherPrimaryValue: string
  pointWeatherNumericValue: number | null
  interactionMode: string
}>()

const emit = defineEmits<{
  enterSelectMode: []
  clearMapPoint: []
}>()
</script>

<template>
  <section v-show="true" id="analysis-tools" class="analysis-section analysis-section--tools">
    <div class="section-kicker">工具</div>
    <h3>分析工具</h3>
    <div class="weather-layer-btn-row" style="margin-bottom: 0.55rem; gap: 0.4rem">
      <button
        v-if="interactionMode !== 'select'"
        type="button"
        class="weather-mini-btn"
        @click="emit('enterSelectMode')"
      >
        进入选择模式
      </button>
      <button
        v-if="selectedMapPoint || pointWeather"
        type="button"
        class="weather-mini-btn"
        @click="emit('clearMapPoint')"
      >
        清除选点
      </button>
      <span v-if="selectedMapPoint" class="weather-mini-meta">
        {{ selectedMapPoint.lng.toFixed(3) }}, {{ selectedMapPoint.lat.toFixed(3) }}
      </span>
    </div>
    <div v-if="!selectedMapPoint" class="analysis-sparse-card">
      <p>{{ ANALYSIS_COPY.sparseToolsHint }}</p>
    </div>
    <BufferAnalysisTool
      v-if="selectedMapPoint"
      :point-location="selectedMapPoint"
      :layer-name="displayLayer.name"
      :current-value-text="pointWeatherPrimaryValue !== '--' ? pointWeatherPrimaryValue : undefined"
      :current-numeric-value="pointWeatherNumericValue"
    />
  </section>
</template>
