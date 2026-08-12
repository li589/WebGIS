<script setup lang="ts">
/**
 * InfoPanel 分析工具：目录过滤 + 参数表单 + 运行/取消/进度。
 * 替换伪 πr² Buffer；真提交走 /analysis/runs。
 */
import { computed, onMounted, reactive, ref, watch } from 'vue'
import type { ActiveLayerDisplay } from '../../stores/layers/types'
import { useAnalysisRunnerStore } from '../../stores/analysis-runner'
import { useLayersStore } from '../../stores/layers'
import type { AnalysisToolDescriptor } from '../../services/analysis-api'
import { ANALYSIS_COPY } from '../../ui-copy'
import AppButton from '../ui/AppButton.vue'
import AnalysisResultCharts from './AnalysisResultCharts.vue'

const props = defineProps<{
  displayLayer: ActiveLayerDisplay
  selectedMapPoint: { lng: number; lat: number } | null
  pointWeather: unknown
  pointWeatherPrimaryValue: string
  pointWeatherNumericValue: number | null
  interactionMode: string
  isRealtimeWeatherLayer?: boolean
}>()

const emit = defineEmits<{
  enterSelectMode: []
  clearMapPoint: []
}>()

const runner = useAnalysisRunnerStore()
const layers = useLayersStore()

const selectedToolId = ref<string | null>(null)
const formValues = reactive<Record<string, unknown>>({})
const zonesOverlayId = ref('')
const showOnMap = ref(true)

const tools = computed(() => runner.toolsCache?.items ?? [])
const selectedTool = computed(
  () => tools.value.find((t) => t.tool_id === selectedToolId.value) ?? null,
)

const runState = computed(() => {
  if (!selectedToolId.value) return null
  return runner.toolStatus(selectedToolId.value, props.displayLayer.catalogId)
})

const canRun = computed(() => {
  const tool = selectedTool.value
  if (!tool || !tool.enabled) return false
  if (tool.tool_id === 'gis.buffer' && !props.selectedMapPoint && !props.displayLayer.isImported) {
    return false
  }
  if (
    ['gis.clip', 'stats.histogram', 'gis.reclassify', 'gis.zonal_stats'].includes(tool.tool_id) &&
    !props.displayLayer.isImportedRaster &&
    !props.displayLayer.importedRasterOverlayLayerId
  ) {
    return false
  }
  if (tool.tool_id === 'gis.clip') {
    const bbox = layers.currentMapBBox
    return Boolean(bbox)
  }
  return true
})

const runDisabledReason = computed(() => {
  const tool = selectedTool.value
  if (!tool) return '请选择工具'
  if (!tool.enabled) return tool.disabled_reason || '当前图层不可用'
  if (tool.tool_id === 'gis.buffer' && !props.selectedMapPoint && !props.displayLayer.isImported) {
    return '请先进入选择模式并在地图选点，或使用导入矢量层'
  }
  if (
    ['gis.clip', 'stats.histogram', 'gis.reclassify', 'gis.zonal_stats'].includes(tool.tool_id) &&
    !props.displayLayer.isImportedRaster &&
    !props.displayLayer.importedRasterOverlayLayerId
  ) {
    return '需要已导入的静态栅格图层'
  }
  if (tool.tool_id === 'gis.clip' && !layers.currentMapBBox) {
    return '无法获取当前视口 bbox'
  }
  return null
})

const estimatedAreaKm2 = computed(() => {
  const r = Number(formValues.distance)
  if (!Number.isFinite(r) || r <= 0) return null
  const unit = String(formValues.distance_unit || 'meters')
  const km = unit === 'kilometers' ? r : r / 1000
  return (Math.PI * km * km).toFixed(1)
})

const analysisCharts = computed(() => props.displayLayer.jobLayer?.analysisCharts ?? [])
const analysisTables = computed(() => props.displayLayer.jobLayer?.analysisTables ?? [])
const hasResults = computed(
  () => analysisCharts.value.length > 0 || analysisTables.value.length > 0,
)

async function refreshTools() {
  await runner.loadToolsForDisplay(props.displayLayer, {
    isWeather: Boolean(props.isRealtimeWeatherLayer),
  })
  if (!selectedToolId.value && tools.value.length) {
    const firstEnabled = tools.value.find((t) => t.enabled)
    selectedToolId.value = firstEnabled?.tool_id ?? tools.value[0].tool_id
  }
}

function initForm(tool: AnalysisToolDescriptor | null) {
  Object.keys(formValues).forEach((k) => delete formValues[k])
  if (!tool) return
  for (const field of tool.param_schema) {
    formValues[field.key] = field.default ?? ''
  }
  if (tool.tool_id === 'gis.buffer' && formValues.distance == null) {
    formValues.distance = 5000
    formValues.distance_unit = 'meters'
  }
}

watch(selectedTool, (t) => initForm(t), { immediate: true })

watch(
  () => props.displayLayer.catalogId,
  () => {
    void refreshTools()
  },
)

onMounted(() => {
  void refreshTools()
})

async function onRun() {
  const tool = selectedTool.value
  if (!tool || !canRun.value) return
  const params = { ...formValues }
  let bbox = null as null | {
    west: number
    south: number
    east: number
    north: number
  }
  if (tool.tool_id === 'gis.clip') {
    const cb = layers.currentMapBBox
    if (cb) {
      bbox = { west: cb.west, south: cb.south, east: cb.east, north: cb.north }
      params.west = cb.west
      params.south = cb.south
      params.east = cb.east
      params.north = cb.north
    }
  }
  await runner.submitTool({
    tool,
    display: props.displayLayer,
    params,
    mapPoint: props.selectedMapPoint,
    bbox,
    zonesOverlayLayerId: zonesOverlayId.value || null,
    showOnMap: showOnMap.value,
  })
}

async function onCancel() {
  const tool = selectedTool.value
  if (!tool) return
  await runner.cancelRun(props.displayLayer.catalogId, tool.tool_id)
}

function selectTool(tool: AnalysisToolDescriptor) {
  selectedToolId.value = tool.tool_id
}

const phaseLabel = computed(() => {
  const p = runState.value?.phase
  if (!p || p === 'idle') return ''
  const map: Record<string, string> = {
    queued: '排队中',
    submitting: '提交中',
    running: '运行中',
    succeeded: '已完成',
    failed: '失败',
    cancelled: '已取消',
  }
  return map[p] || p
})
</script>

<template>
  <section id="analysis-tools" class="analysis-section analysis-section--tools">
    <div class="section-kicker">工具</div>
    <h3>分析工具</h3>

    <div class="weather-layer-btn-row" style="margin-bottom: 0.55rem; gap: 0.4rem">
      <AppButton
        v-if="interactionMode !== 'select'"
        size="xs"
        variant="secondary"
        @click="emit('enterSelectMode')"
      >
        进入选择模式
      </AppButton>
      <AppButton
        v-if="selectedMapPoint || pointWeather"
        size="xs"
        variant="secondary"
        @click="emit('clearMapPoint')"
      >
        清除选点
      </AppButton>
      <span v-if="selectedMapPoint" class="weather-mini-meta">
        {{ selectedMapPoint.lng.toFixed(3) }}, {{ selectedMapPoint.lat.toFixed(3) }}
      </span>
    </div>

    <p v-if="runner.lastHint" class="tool-hint">{{ runner.lastHint }}</p>
    <p v-if="runner.toolsError" class="tool-error">{{ runner.toolsError }}</p>
    <p v-if="runner.toolsLoading" class="tool-hint">加载工具目录…</p>

    <div class="tool-list">
      <button
        v-for="tool in tools"
        :key="tool.tool_id"
        type="button"
        class="tool-chip"
        :class="{
          'tool-chip--active': selectedToolId === tool.tool_id,
          'tool-chip--disabled': !tool.enabled,
        }"
        :title="tool.disabled_reason || tool.description"
        :disabled="!tool.enabled && selectedToolId !== tool.tool_id"
        @click="selectTool(tool)"
      >
        {{ tool.title }}
      </button>
    </div>

    <div v-if="selectedTool" class="tool-card">
      <div class="tool-head">
        <span class="tool-kicker">{{ selectedTool.category }}</span>
        <h4>{{ selectedTool.title }}</h4>
        <p class="tool-note">{{ selectedTool.description }}</p>
        <p v-if="!selectedTool.enabled && selectedTool.disabled_reason" class="tool-error">
          {{ selectedTool.disabled_reason }}
        </p>
      </div>

      <div class="param-grid">
        <label v-for="field in selectedTool.param_schema" :key="field.key" class="param-row">
          <span class="param-label">
            {{ field.title || field.key }}
            <em v-if="field.unit">（{{ field.unit }}）</em>
          </span>
          <select
            v-if="field.type === 'enum' && field.options?.length"
            v-model="formValues[field.key]"
            class="param-input"
          >
            <option v-for="opt in field.options" :key="opt" :value="opt">{{ opt }}</option>
          </select>
          <input
            v-else-if="field.type === 'number' || field.type === 'integer'"
            v-model.number="formValues[field.key]"
            type="number"
            class="param-input"
            :min="field.min ?? undefined"
            :max="field.max ?? undefined"
          />
          <input
            v-else
            v-model="formValues[field.key]"
            type="text"
            class="param-input"
            :placeholder="field.description || ''"
          />
        </label>

        <label v-if="selectedTool.tool_id === 'gis.zonal_stats'" class="param-row">
          <span class="param-label">分区矢量 overlay id（可选）</span>
          <input v-model="zonesOverlayId" type="text" class="param-input" placeholder="imported-…" />
        </label>

        <label class="param-row param-row--check">
          <input v-model="showOnMap" type="checkbox" />
          <span>成功后在地图显示新图层（默认开）</span>
        </label>
      </div>

      <div v-if="selectedTool.tool_id === 'gis.buffer' && estimatedAreaKm2" class="stats-grid">
        <div class="stat-box">
          <span class="stat-lbl">几何面积提示（πr²，非分析结果）</span>
          <strong class="stat-val">{{ estimatedAreaKm2 }} km²</strong>
        </div>
      </div>

      <div class="run-row">
        <AppButton size="sm" variant="primary" :disabled="!canRun" @click="onRun">
          运行
        </AppButton>
        <AppButton
          v-if="runState && (runState.phase === 'running' || runState.phase === 'submitting' || runState.phase === 'queued')"
          size="sm"
          variant="secondary"
          @click="onCancel"
        >
          取消
        </AppButton>
        <span v-if="phaseLabel" class="run-phase">{{ phaseLabel }}</span>
      </div>
      <p v-if="runDisabledReason && !canRun" class="tool-hint">{{ runDisabledReason }}</p>
      <p v-if="runState?.message" class="tool-hint">{{ runState.message }}</p>
      <p v-if="!canRun && !runDisabledReason" class="analysis-sparse-card">
        {{ ANALYSIS_COPY.sparseToolsHint }}
      </p>
    </div>

    <div v-if="hasResults" class="result-block">
      <div class="section-kicker">分析结果</div>
      <AnalysisResultCharts :charts="analysisCharts" :tables="analysisTables" />
    </div>
  </section>
</template>

<style scoped>
.tool-list {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem;
  margin-bottom: 0.55rem;
}

.tool-chip {
  border: 1px solid var(--border-default);
  background: var(--surface-raised);
  color: var(--text-primary);
  border-radius: 0.45rem;
  padding: 0.28rem 0.55rem;
  font-size: var(--font-size-caption);
  cursor: pointer;
}

.tool-chip--active {
  border-color: var(--accent, #3b82f6);
  background: color-mix(in srgb, var(--accent, #3b82f6) 18%, transparent);
}

.tool-chip--disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.tool-card {
  margin-top: 0.35rem;
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

.tool-note,
.tool-hint {
  margin: 0.25rem 0 0;
  font-size: var(--font-size-caption);
  color: var(--text-secondary);
}

.tool-error {
  margin: 0.25rem 0 0;
  font-size: var(--font-size-caption);
  color: var(--danger, #b91c1c);
}

.param-grid {
  display: grid;
  gap: 0.4rem;
}

.param-row {
  display: grid;
  gap: 0.2rem;
}

.param-row--check {
  grid-template-columns: auto 1fr;
  align-items: center;
  gap: 0.4rem;
}

.param-label {
  font-size: var(--font-size-caption);
  color: var(--text-secondary);
}

.param-input {
  width: 100%;
  border: 1px solid var(--border-default);
  border-radius: 0.4rem;
  padding: 0.28rem 0.4rem;
  background: var(--surface-base, transparent);
  color: inherit;
}

.run-row {
  display: flex;
  align-items: center;
  gap: 0.45rem;
  margin-top: 0.55rem;
}

.run-phase {
  font-size: var(--font-size-caption);
  color: var(--text-secondary);
}

.stats-grid {
  display: grid;
  gap: 0.35rem;
  margin-top: 0.45rem;
}

.stat-box {
  padding: 0.35rem 0.45rem;
  border-radius: 0.45rem;
  border: 1px solid var(--border-default);
}

.stat-lbl {
  display: block;
  font-size: var(--font-size-caption);
  color: var(--text-secondary);
}

.stat-val {
  font-size: var(--font-size-body);
}

.result-block {
  margin-top: 0.75rem;
}
</style>
