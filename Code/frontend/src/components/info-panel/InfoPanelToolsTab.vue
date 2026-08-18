<script setup lang="ts">
/**
 * InfoPanel「工具」Tab 编排层：
 * 列表页（目录网格 + 分析结果）/ 工具子页（参数表单）/ 底图要素提取子页。
 * 可运行判定与表单校验在 ./tools/tool-page-model（纯函数，可单测）。
 * 真提交走 /analysis/runs（stores/analysis-runner）。
 */
import { computed, onMounted, reactive, ref, watch } from 'vue'
import type { ActiveLayerDisplay } from '../../stores/layers/types'
import { useAnalysisRunnerStore } from '../../stores/analysis-runner'
import { useLayersStore } from '../../stores/layers'
import { isShowAnalysisResultOnMapEnabled } from '../../services/settings-local'
import type { AnalysisToolDescriptor } from '../../services/analysis-api'
import AppButton from '../ui/AppButton.vue'
import AnalysisResultCharts from './AnalysisResultCharts.vue'
import BasemapFeatureExtractCard from './BasemapFeatureExtractCard.vue'
import ToolCatalogGrid from './tools/ToolCatalogGrid.vue'
import ToolRunPage from './tools/ToolRunPage.vue'
import PageBackButton from './tools/PageBackButton.vue'
import {
  initFormValues,
  phaseLabelFor,
  runDisabledReasonFor,
  canRunTool,
  sanitizeFormValues,
  validateFormValues,
  type ToolPage,
} from './tools/tool-page-model'

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

const page = ref<ToolPage>({ kind: 'list' })
const formValues = reactive<Record<string, unknown>>({})
const formErrors = reactive<Record<string, string>>({})
const zonesOverlayId = ref('')

const tools = computed(() => runner.toolsCache?.items ?? [])
const selectedTool = computed<AnalysisToolDescriptor | null>(() => {
  const p = page.value
  if (p.kind !== 'tool') return null
  return tools.value.find((t) => t.tool_id === p.toolId) ?? null
})

const runContext = computed(() => ({
  displayLayer: props.displayLayer,
  selectedMapPoint: props.selectedMapPoint,
  hasMapBBox: Boolean(layers.currentMapBBox),
}))

const runState = computed(() => {
  if (page.value.kind !== 'tool') return null
  return runner.toolStatus(page.value.toolId, props.displayLayer.catalogId)
})

const phaseLabel = computed(() => phaseLabelFor(runState.value?.phase))

/** 各工具当前运行状态角标（列表页网格用） */
const phaseBadges = computed<Record<string, string>>(() => {
  const badges: Record<string, string> = {}
  for (const tool of tools.value) {
    const label = phaseLabelFor(
      runner.toolStatus(tool.tool_id, props.displayLayer.catalogId)?.phase,
    )
    if (label) badges[tool.tool_id] = label
  }
  return badges
})

/** 各工具不可用原因（后端 disabled_reason 优先，前端数据前置条件兜底）→ 网格卡片引导 */
const blockedReasons = computed<Record<string, string>>(() => {
  const reasons: Record<string, string> = {}
  for (const tool of tools.value) {
    const reason = tool.disabled_reason || runDisabledReasonFor(tool, runContext.value)
    if (reason) reasons[tool.tool_id] = reason
  }
  return reasons
})

/** 当前工作区已导入矢量层（供分区统计 overlay id 下拉建议） */
const importedVectorOptions = computed(() =>
  layers.activeLayersDisplay
    .filter((layer) => layer.importedVectorBackendLayerId)
    .map((layer) => ({ id: layer.importedVectorBackendLayerId as string, label: layer.name })),
)

const estimatedAreaKm2 = computed(() => {
  if (selectedTool.value?.tool_id !== 'gis.buffer') return null
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
const currentMapBBox = computed(() => layers.currentMapBBox)

async function refreshTools() {
  await runner.loadToolsForDisplay(props.displayLayer, {
    isWeather: Boolean(props.isRealtimeWeatherLayer),
  })
}

function applyFormValues(tool: AnalysisToolDescriptor | null) {
  Object.keys(formValues).forEach((k) => delete formValues[k])
  Object.keys(formErrors).forEach((k) => delete formErrors[k])
  if (!tool) return
  for (const [key, value] of Object.entries(initFormValues(tool))) {
    formValues[key] = value
  }
}

watch(selectedTool, (tool) => applyFormValues(tool))

watch(
  () => props.displayLayer.catalogId,
  () => {
    page.value = { kind: 'list' }
    void refreshTools()
  },
)

onMounted(() => {
  void refreshTools()
})

function onGridSelect(entryId: string) {
  if (entryId === 'basemap-extract') {
    page.value = { kind: 'extract' }
    return
  }
  const tool = tools.value.find((t) => t.tool_id === entryId)
  if (tool) page.value = { kind: 'tool', toolId: entryId }
}

function onSetField(key: string, value: unknown) {
  formValues[key] = value
}

async function onRun() {
  const tool = selectedTool.value
  if (!tool || !canRunTool(tool, runContext.value)) return
  const { ok, errors } = validateFormValues(tool, formValues)
  Object.keys(formErrors).forEach((k) => delete formErrors[k])
  for (const [key, message] of Object.entries(errors)) formErrors[key] = message
  if (!ok) return

  const params = sanitizeFormValues(formValues)
  let bbox = null as null | { west: number; south: number; east: number; north: number }
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
  if (
    (tool.tool_id === 'gis.buffer' || tool.tool_id === 'gis.vector_to_raster') &&
    !props.selectedMapPoint &&
    props.displayLayer.importedVectorBackendLayerId
  ) {
    params.imported_vector_layer_id = props.displayLayer.importedVectorBackendLayerId
  }
  await runner.submitTool({
    tool,
    display: props.displayLayer,
    params,
    mapPoint: props.selectedMapPoint ?? null,
    bbox,
    zonesOverlayLayerId: zonesOverlayId.value || null,
    showOnMap: isShowAnalysisResultOnMapEnabled(),
  })
}

async function onCancel() {
  const tool = selectedTool.value
  if (!tool) return
  await runner.cancelRun(props.displayLayer.catalogId, tool.tool_id)
}

const activeToolRunHint = computed(() => {
  const tool = selectedTool.value
  if (!tool) return ''
  if (canRunTool(tool, runContext.value)) return runState.value?.message ?? ''
  return runDisabledReasonFor(tool, runContext.value) ?? ''
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

    <!-- ── 列表页：目录网格 + 分析结果 ── -->
    <template v-if="page.kind === 'list'">
      <p v-if="runner.lastHint" class="tool-hint">{{ runner.lastHint }}</p>
      <p v-if="runner.toolsError" class="tool-error">{{ runner.toolsError }}</p>
      <p v-if="runner.toolsLoading" class="tool-hint">加载工具目录…</p>

      <ToolCatalogGrid
        :tools="tools"
        :phase-badges="phaseBadges"
        :blocked-reasons="blockedReasons"
        @select="onGridSelect"
      />

      <div v-if="hasResults" class="result-block">
        <div class="section-kicker">分析结果</div>
        <AnalysisResultCharts :charts="analysisCharts" :tables="analysisTables" />
      </div>
    </template>

    <!-- ── 工具子页：参数表单 ── -->
    <template v-else-if="page.kind === 'tool' && selectedTool">
      <div class="tool-page-card">
        <ToolRunPage
          v-model:zones-overlay-id="zonesOverlayId"
          :tool="selectedTool"
          :form-values="formValues"
          :form-errors="formErrors"
          :run-context="runContext"
          :run-phase="runState?.phase ?? ''"
          :run-phase-label="phaseLabel"
          :run-message="runState?.message ?? ''"
          :imported-vector-options="importedVectorOptions"
          @back="page = { kind: 'list' }"
          @run="onRun"
          @cancel="onCancel"
          @set-field="onSetField"
        />

        <div v-if="estimatedAreaKm2" class="stats-grid">
          <div class="stat-box">
            <span class="stat-lbl">几何面积提示（πr²，非分析结果）</span>
            <strong class="stat-val">{{ estimatedAreaKm2 }} km²</strong>
          </div>
        </div>

        <p v-if="activeToolRunHint" class="tool-hint">{{ activeToolRunHint }}</p>
      </div>
    </template>

    <!-- ── 底图要素提取子页 ── -->
    <template v-else-if="page.kind === 'extract'">
      <div class="tool-page-card">
        <div class="tool-page-head">
          <PageBackButton label="工具列表" @back="page = { kind: 'list' }" />
          <span class="tool-kicker">basemap</span>
          <h4 class="tool-title">底图要素提取</h4>
          <p class="tool-note">
            从底图提取行政区 / 道路要素并自动创建矢量图层。栅格底图无原生要素，
            行政区来自内置边界数据，道路来自 OpenStreetMap（需外部网络）。
          </p>
        </div>
        <BasemapFeatureExtractCard
          :selected-map-point="selectedMapPoint"
          :current-map-b-box="currentMapBBox"
          @enter-select-mode="emit('enterSelectMode')"
        />
      </div>
    </template>
  </section>
</template>

<style scoped>
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

.tool-page-card {
  padding: 0.55rem 0.6rem;
  border-radius: 0.65rem;
  border: 1px solid var(--border-default);
  background: var(--surface-raised);
}

.tool-page-head {
  display: grid;
  gap: 0.15rem;
  margin-bottom: 0.5rem;
}

.tool-kicker {
  font-size: var(--font-size-caption);
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--text-secondary);
}

.tool-title {
  margin: 0;
  font-size: var(--font-size-body);
}

.tool-note {
  margin: 0.2rem 0 0;
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
