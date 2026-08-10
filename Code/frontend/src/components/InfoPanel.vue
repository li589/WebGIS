<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'

import type { ActiveLayerDisplay, LayerHotspot } from '../stores/layers/types'
import type { WeatherPointResponse, WeatherProviderForLayer } from '../services/runtime-api'
import { getWeatherProvidersForLayer } from '../services/runtime-api'
import { useLayersStore } from '../stores/layers'
import { useUiStore } from '../stores/ui'
import { useLogStore } from '../stores/log'
import { useWeatherTileManager } from '../stores/weather-tile-manager'
import { useWeatherSourcePrefsStore } from '../stores/weather-source-prefs'
import { buildResultDisplayModel } from './info-panel/result-adapter'
import {
  WEATHER_PALETTE_OPTIONS,
  buildWeatherLegendGradient,
  buildWeatherLegendStops,
  hasRenderableSymbology,
  isMapLinkedPalette,
  paletteIdsEqual,
  resolveCanonicalPaletteId,
} from './map/layer-symbology'
import {
  resolveEffectiveLayerSymbology,
  buildLegendExplainer,
} from './map/effective-layer-symbology'
import { useOverlaySymbologyStore } from '../stores/overlay-symbology'
import { windDisplayModeLabel, type WindDisplayMode } from './map/wind-display-mode'
import { ANALYSIS_COPY, INSPECT_COPY, LAYERS_COPY, DATA_COPY } from '../ui-copy'
import { openDataWorkspace, openDatedExportForLayer } from '../data-manager/core/workspace-store'
import { exportLayer } from '../data-manager/adapters/export'
import {
  resolveAnalysisStageKind,
  resolveStaticLayerHint,
  resolveWorkflowStageCopy,
} from './info-panel/analysis-panel-summary'
import {
  normalizeAnalysisFocusIds,
  resolveAnalysisTabForFocusIds,
  type AnalysisTabId,
} from './info-panel/analysis-tab-focus'
import { resolveWeatherWorkflowStage } from '../utils/weather-tile-readiness'
import PointTimeSeriesChart from './info-panel/PointTimeSeriesChart.vue'
import MultiOverlayBarChart from './info-panel/MultiOverlayBarChart.vue'
import BufferAnalysisTool from './info-panel/BufferAnalysisTool.vue'
import AnalysisResultCharts from './info-panel/AnalysisResultCharts.vue'

const layersStore = useLayersStore()
const uiStore = useUiStore()
const logStore = useLogStore()
const weatherTileManager = useWeatherTileManager()
const weatherSourcePrefs = useWeatherSourcePrefsStore()
const overlaySymbologyStore = useOverlaySymbologyStore()
const importActionHint = ref('')
let importHintTimer: number | null = null

const activeTab = ref<AnalysisTabId>('visual')

function setActiveTab(tab: AnalysisTabId) {
  activeTab.value = tab
}

const weatherProviderOptions = ref<WeatherProviderForLayer[]>([])
const weatherProvidersLoading = ref(false)
const weatherProvidersError = ref<string | null>(null)
let weatherProvidersAbort: AbortController | null = null

function flashImportHint(message: string) {
  importActionHint.value = message
  if (importHintTimer !== null) window.clearTimeout(importHintTimer)
  importHintTimer = window.setTimeout(() => {
    importActionHint.value = ''
    importHintTimer = null
  }, 3200)
}

const props = defineProps<{
  activeLayer: ActiveLayerDisplay
  stageLabel: string
  visibleHotspots: LayerHotspot[]
  selectedLayer?: ActiveLayerDisplay | null
  selectedHotspot?: LayerHotspot | null
  selectedMapPoint?: { lng: number; lat: number } | null
  /** 与瓦片对齐的预报 hour 索引，用于高亮点查小时条 */
  inspectHour?: number
  isSubmitting?: boolean
  workflowError?: string | null
  pointWeather?: WeatherPointResponse | null
  pointWeatherLoading?: boolean
  pointWeatherError?: string | null
  overlayTimeStates?: import('./map/overlay-image-module').OverlayTimeState[]
  overlayPointValues?: import('../services/runtime-api').OverlayPointValue[]
  /** 当前选中时间序列栅格在选点处的全时间块数值 */
  selectedOverlayTimeSeries?: import('../services/runtime-api').OverlayPointValue[]
}>()

const emit = defineEmits<{
  toggleLayerVisibility: [instanceId: string]
  setLayerOpacity: [payload: { instanceId: string; opacity: number }]
  selectHotspot: [hotspotId: string]
  clearMapPoint: []
  enterSelectMode: []
  queryOverlaySeries: [payload: { lng: number; lat: number }]
}>()

function enterInspectTools() {
  setActiveTab('tools')
  emit('enterSelectMode')
}

function queryDefaultOverlaySeries() {
  // 撒哈拉稳定观测点，确保 SM/VOD/OMEGA 5块均可见；用户点图后会被选点覆盖。
  emit('queryOverlaySeries', { lng: 11.25, lat: 19.7623 })
}

const displayLayer = computed(() => props.selectedLayer ?? props.activeLayer)
const jobLayer = computed(() => displayLayer.value?.jobLayer)
const resultModel = computed(() => buildResultDisplayModel(jobLayer.value?.resultView ?? null))
const analysisSummary = computed(() => {
  if (displayLayer.value.isImported) {
    return ANALYSIS_COPY.overviewImportedVector(
      displayLayer.value.importedGeometryType ?? '—',
      displayLayer.value.importedFeatureCount ?? 0,
    )
  }
  if (displayLayer.value.isImportedRaster) {
    return ANALYSIS_COPY.overviewImportedRaster
  }
  if (displayLayer.value.isAdminBoundary) {
    return ANALYSIS_COPY.overviewBoundary
  }
  return displayLayer.value.summary || props.activeLayer.summary
})
const jobReportSummary = computed(
  () => jobLayer.value?.resultView?.summary ?? jobLayer.value?.reportSummary ?? '',
)
const isRealtimeWeatherLayer = computed(() =>
  layersStore.isWeatherEngineLayer(displayLayer.value.catalogId),
)

const selectedWeatherProvider = computed({
  get: () => weatherSourcePrefs.getProvider(displayLayer.value.catalogId),
  set: (value: string) => {
    layersStore.applyWeatherProviderPreference(displayLayer.value.catalogId, value || 'auto')
  },
})

const selectedWeatherProviderSparse = computed(() => {
  const pref = selectedWeatherProvider.value
  if (!pref || pref === 'auto') return false
  const row = weatherProviderOptions.value.find((p) => p.provider_id === pref)
  return row?.grid_mode === 'sparse' || row?.data_quality === 'sparse'
})

const selectedWeatherProviderHint = computed(() => {
  const pref = selectedWeatherProvider.value
  if (!pref || pref === 'auto') return null
  const row = weatherProviderOptions.value.find((p) => p.provider_id === pref)
  if (!row?.hint || row.data_quality === 'observed') return null
  return row.hint
})

function weatherProviderOptionLabel(p: WeatherProviderForLayer): string {
  const bits = [p.display_name]
  if (!p.enabled) bits.push('（未启用）')
  if (p.data_quality === 'extrapolated') bits.push(' · 外推')
  else if (p.data_quality === 'sparse' || p.grid_mode === 'sparse') bits.push(' · 稀疏')
  return bits.join('')
}

watch(
  () => (isRealtimeWeatherLayer.value ? displayLayer.value.catalogId : null),
  async (catalogId) => {
    if (weatherProvidersAbort) {
      weatherProvidersAbort.abort()
      weatherProvidersAbort = null
    }
    weatherProviderOptions.value = []
    weatherProvidersError.value = null
    if (!catalogId) return
    weatherProvidersLoading.value = true
    const controller = new AbortController()
    weatherProvidersAbort = controller
    try {
      const resp = await getWeatherProvidersForLayer(catalogId, {
        includeDisabled: true,
        signal: controller.signal,
      })
      if (controller.signal.aborted) return
      const providers = resp.providers ?? []
      weatherProviderOptions.value = providers
      // Drop stale pin: disabled / unsupported / unknown provider_id would 503 tiles.
      const pref = weatherSourcePrefs.getProvider(catalogId)
      if (pref && pref !== 'auto') {
        const match = providers.find((p) => p.provider_id === pref)
        if (!match || !match.enabled) {
          layersStore.applyWeatherProviderPreference(catalogId, 'auto')
        }
      }
    } catch (error) {
      if (controller.signal.aborted) return
      weatherProvidersError.value = error instanceof Error ? error.message : '无法加载天气源列表'
    } finally {
      if (!controller.signal.aborted) weatherProvidersLoading.value = false
      if (weatherProvidersAbort === controller) weatherProvidersAbort = null
    }
  },
  { immediate: true },
)

const weatherRenderHint = computed(
  () =>
    displayLayer.value?.renderHint ??
    jobLayer.value?.mapLayerPayload?.renderHint ??
    props.pointWeather?.render_hint ??
    null,
)

/** 侧栏同源 overlay meta + 可选 overlayTimeStates 兜底 */
const overlayStyleMeta = computed(() => {
  void overlaySymbologyStore.version
  const overlayId = displayLayer.value.importedRasterOverlayLayerId ?? displayLayer.value.catalogId
  const fromStore = overlaySymbologyStore.getMeta(overlayId)
  if (fromStore?.palette) return fromStore
  const states = props.overlayTimeStates ?? []
  const match = states.find((s) => s.layerId === overlayId)
  if (!match) return fromStore
  return {
    palette: match.palette,
    vmin: match.vmin,
    vmax: match.vmax,
    unit: match.unit,
    opacity: match.opacity,
  }
})

watch(
  () =>
    [
      displayLayer.value.catalogId,
      displayLayer.value.renderHint,
      displayLayer.value.isImported,
      displayLayer.value.isImportedRaster,
      displayLayer.value.isAdminBoundary,
    ] as const,
  ([catalogId, renderHint, isImported, isImportedRaster, isAdminBoundary]) => {
    if (!catalogId || isImported || isAdminBoundary) return
    // 天气有 renderHint 时不必拉 overlay meta；有源 overlay / 导入栅格需要 supports_recolor
    if (renderHint && !isImportedRaster) return
    void overlaySymbologyStore.ensureMeta(catalogId)
  },
  { immediate: true },
)

const styleSymbology = computed(() => {
  void weatherTileManager.dataVersion
  const viewportGeojson =
    isRealtimeWeatherLayer.value && displayLayer.value.catalogId
      ? weatherTileManager.getMergedGeojsonForViewport(displayLayer.value.catalogId)
      : null
  return resolveEffectiveLayerSymbology({
    paletteOverride: displayLayer.value.paletteOverride,
    renderHint: weatherRenderHint.value,
    overlayMeta: overlayStyleMeta.value,
    viewportGeojson,
  })
})
const styleRenderHint = computed(() => styleSymbology.value.hint)

/** 样式 Tab：字段名（与原符号浮窗对齐） */
const styleFieldLabel = computed(() => {
  const hint = styleRenderHint.value
  if (hint?.primary_metric) return hint.primary_metric
  return displayLayer.value.metricLabel || ''
})

/** 样式 Tab：数值范围（图例 ticks 或 overlay meta） */
const styleRangeMeta = computed(() => {
  const hint = styleRenderHint.value
  const meta = overlayStyleMeta.value
  let vmin = '—'
  let vmax = '—'
  if (hint?.legend_ticks?.length) {
    const first = hint.legend_ticks[0]
    const last = hint.legend_ticks[hint.legend_ticks.length - 1]
    vmin = typeof first === 'number' ? String(first) : String(first ?? '—')
    vmax = typeof last === 'number' ? String(last) : String(last ?? '—')
  } else if (meta) {
    if (meta.vmin != null) vmin = String(meta.vmin)
    if (meta.vmax != null) vmax = String(meta.vmax)
  }
  const unit = hint?.unit_label || meta?.unit || ''
  const hasRange =
    Boolean(hint) ||
    Boolean(meta?.palette) ||
    displayLayer.value.isImportedRaster ||
    vmin !== '—' ||
    vmax !== '—'
  return { vmin, vmax, unit, hasRange }
})

const weatherLegendStops = computed(() =>
  styleRenderHint.value ? buildWeatherLegendStops(styleRenderHint.value) : [],
)
const weatherLegendGradient = computed(() =>
  styleRenderHint.value ? buildWeatherLegendGradient(styleRenderHint.value) : '',
)
const currentPaletteId = computed(() =>
  resolveCanonicalPaletteId(
    displayLayer.value?.paletteOverride ?? styleRenderHint.value?.palette ?? '',
  ),
)
const paletteOptions = WEATHER_PALETTE_OPTIONS
const paletteDropdownOpen = ref(false)
const canEditPalette = computed(() =>
  isMapLinkedPalette({
    hasRenderHint: Boolean(weatherRenderHint.value),
    isImportedRaster: displayLayer.value.isImportedRaster,
    supportsRecolor: Boolean(overlayStyleMeta.value?.supports_recolor),
  }),
)

const rangeEditVmin = computed({
  get: () => {
    if (displayLayer.value.vminOverride != null) return String(displayLayer.value.vminOverride)
    const meta = overlayStyleMeta.value
    if (meta?.vmin != null) return String(meta.vmin)
    const ticks = styleRenderHint.value?.legend_ticks
    const first = ticks?.[0]
    return typeof first === 'number' ? String(first) : ''
  },
  set: (raw: string) => {
    if (!displayLayer.value?.instanceId || !canEditPalette.value) return
    const n = raw.trim() === '' ? null : Number(raw)
    layersStore.setLayerRangeOverride(displayLayer.value.instanceId, {
      vmin: n != null && Number.isFinite(n) ? n : null,
    })
  },
})

const rangeEditVmax = computed({
  get: () => {
    if (displayLayer.value.vmaxOverride != null) return String(displayLayer.value.vmaxOverride)
    const meta = overlayStyleMeta.value
    if (meta?.vmax != null) return String(meta.vmax)
    const ticks = styleRenderHint.value?.legend_ticks
    const last = ticks?.length ? ticks[ticks.length - 1] : undefined
    return typeof last === 'number' ? String(last) : ''
  },
  set: (raw: string) => {
    if (!displayLayer.value?.instanceId || !canEditPalette.value) return
    const n = raw.trim() === '' ? null : Number(raw)
    layersStore.setLayerRangeOverride(displayLayer.value.instanceId, {
      vmax: n != null && Number.isFinite(n) ? n : null,
    })
  },
})

const nodataModeValue = computed({
  get: () => displayLayer.value.nodataMode ?? 'transparent',
  set: (mode: 'transparent' | 'solid') => {
    if (!displayLayer.value?.instanceId || !canEditPalette.value) return
    layersStore.setLayerNodataDisplay(displayLayer.value.instanceId, {
      mode,
      color: mode === 'solid' ? displayLayer.value.nodataColor || '#808080' : null,
    })
  },
})

const nodataColorValue = computed({
  get: () => displayLayer.value.nodataColor || '#808080',
  set: (color: string) => {
    if (!displayLayer.value?.instanceId || !canEditPalette.value) return
    layersStore.setLayerNodataDisplay(displayLayer.value.instanceId, {
      mode: 'solid',
      color,
    })
  },
})

function handleSelectPalette(paletteId: string) {
  if (!canEditPalette.value) return
  const defaultId = resolveCanonicalPaletteId(
    weatherRenderHint.value?.palette ?? overlayStyleMeta.value?.palette ?? '',
  )
  const target = paletteIdsEqual(paletteId, defaultId) ? null : paletteId
  if (displayLayer.value?.instanceId) {
    layersStore.setLayerPaletteOverride(displayLayer.value.instanceId, target)
  }
  paletteDropdownOpen.value = false
}
function togglePaletteDropdown() {
  if (!canEditPalette.value) return
  paletteDropdownOpen.value = !paletteDropdownOpen.value
}
const tileStats = computed(() =>
  isRealtimeWeatherLayer.value ? weatherTileManager.getStats(displayLayer.value.catalogId) : null,
)
const hasWeatherLayerAsset = computed(() => {
  if (isRealtimeWeatherLayer.value) return (tileStats.value?.cached ?? 0) > 0
  return !!jobLayer.value?.mapLayerPayload?.layerAssets?.geojsonUrl
})
const jobEventNotes = computed(
  () => jobLayer.value?.eventMessages ?? jobLayer.value?.diagnosticNotes ?? [],
)

const canToggleParticleFlow = computed(() =>
  layersStore.supportsParticleFlow(displayLayer.value.catalogId),
)
/** 该层是否持有风场三态控件归属（含「网格」色底态） */
const ownsWindDisplay = computed(
  () => layersStore.particleFlowCatalogId === displayLayer.value.catalogId,
)
const currentWindDisplayMode = computed<WindDisplayMode>(() => {
  if (!ownsWindDisplay.value) return 'off'
  return layersStore.windDisplayMode
})
const legendExplainer = computed(() =>
  buildLegendExplainer({
    hint: styleRenderHint.value,
    windDisplayMode: canToggleParticleFlow.value ? currentWindDisplayMode.value : null,
    canToggleParticleFlow: canToggleParticleFlow.value,
  }),
)
function handleSetWindDisplayMode(mode: WindDisplayMode) {
  // 本层已归属时可自由三态切换；其它层需等瓦片就绪才能抢占
  if (mode !== 'off' && particleFlowButtonDisabled.value) return
  layersStore.setWindDisplayMode(displayLayer.value.catalogId, mode)
}
/** 无数据且非本层归属时禁用「粒子流/流量场」；「网格」永远可点 */
const particleFlowButtonDisabled = computed(() => {
  if (ownsWindDisplay.value) return false
  return !hasWeatherLayerAsset.value
})
const windStyleChipLabel = computed(() => {
  if (!canToggleParticleFlow.value) return styleRenderHint.value?.paint_mode ?? '样式'
  return windDisplayModeLabel(currentWindDisplayMode.value)
})

/** 任意选中层可进样式 Tab（至少调透明度；天气/导入另有专项控件） */
const hasLayerStyleSection = computed(() => !!displayLayer.value.instanceId)

/** 除透明度外是否还有符号/专项样式控件 */
const hasAdvancedStyleControls = computed(
  () =>
    hasRenderableSymbology({
      renderHint: weatherRenderHint.value,
      overlayMeta: overlayStyleMeta.value,
      isAdminBoundary: displayLayer.value.isAdminBoundary,
      isImported: displayLayer.value.isImported,
      isImportedRaster: displayLayer.value.isImportedRaster,
    }) ||
    canToggleParticleFlow.value ||
    isRealtimeWeatherLayer.value ||
    !!displayLayer.value.isImported ||
    !!displayLayer.value.isImportedRaster,
)

/** 天气点查区块：有查询态或已选点时展示；否则走稀疏空态卡 */
const hasPointWeatherSection = computed(
  () =>
    isRealtimeWeatherLayer.value &&
    (props.pointWeatherLoading ||
      !!props.pointWeatherError ||
      !!props.pointWeather ||
      !!props.selectedMapPoint),
)

const showCompactHero = computed(
  () =>
    displayLayer.value.isImported ||
    displayLayer.value.isImportedRaster ||
    displayLayer.value.isAdminBoundary,
)

function formatBounds(bounds?: [number, number, number, number] | null): string {
  if (!bounds || bounds.length !== 4) return '—'
  return `${bounds[0].toFixed(3)}, ${bounds[1].toFixed(3)} → ${bounds[2].toFixed(3)}, ${bounds[3].toFixed(3)}`
}

async function exportImportedGeoJson() {
  const id = displayLayer.value.instanceId
  if (!id) return
  const active = layersStore.activeLayers.find((l) => l.instanceId === id)
  if (!active) return
  try {
    await exportLayer(active, 'geojson')
    flashImportHint('已导出 GeoJSON')
    logStore.logOperation('export-geojson', `导出 GeoJSON：${displayLayer.value.name || id}`)
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e)
    flashImportHint(`导出失败：${msg}`)
    logStore.logOperation('export-fail', '分析框导出 GeoJSON 失败', msg)
  }
}

async function exportImportedCsv() {
  const id = displayLayer.value.instanceId
  if (!id) return
  const active = layersStore.activeLayers.find((l) => l.instanceId === id)
  if (!active) return
  try {
    await exportLayer(active, 'csv')
    flashImportHint('已导出 CSV')
    logStore.logOperation('export-csv', `导出 CSV：${displayLayer.value.name || id}`)
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e)
    flashImportHint(`导出失败：${msg}`)
    logStore.logOperation('export-fail', '分析框导出 CSV 失败', msg)
  }
}

async function exportImportedRaster(format: 'png' | 'tif') {
  const id = displayLayer.value.instanceId
  if (!id) return
  const active = layersStore.activeLayers.find((l) => l.instanceId === id)
  if (!active) return
  // 汇合到数据导出框（预选当前生效时刻）
  if (active.importedRaster) {
    const times = active.importedRaster.timeList ?? []
    let time: string | null = null
    if (times.length) {
      const eff = active.importedRaster.effectiveTimeLabel
      time =
        (eff && times.find((t) => eff === t || eff.startsWith(t))) ||
        times[times.length - 1] ||
        null
    }
    openDatedExportForLayer(id, time)
    logStore.logOperation(
      `export-open-${format}`,
      `打开导出：${displayLayer.value.name || id}${time ? ` @ ${time}` : ''}`,
    )
    return
  }
  try {
    await exportLayer(active, format)
    flashImportHint(format === 'png' ? '已导出 PNG' : '已导出 GeoTIFF')
    logStore.logOperation(
      `export-${format}`,
      `导出 ${format.toUpperCase()}：${displayLayer.value.name || id}`,
    )
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e)
    flashImportHint(`导出失败：${msg}`)
    logStore.logOperation('export-fail', `分析框导出 ${format.toUpperCase()} 失败`, msg)
  }
}

function patchImportedVectorStyle(
  patch: Partial<{ color: string; width: number; radius: number; fillOpacity: number }>,
) {
  const id = displayLayer.value.instanceId
  if (!id || !displayLayer.value.isImported) return
  layersStore.setImportedVectorStyle(id, patch)
}

const importedVectorStyle = computed(() => displayLayer.value.importedVectorStyle ?? {})

const WEATHER_METRIC_LABELS: Record<string, string> = {
  wind_speed_10m: '实时风速',
  wind_speed_80m: '80m 风速',
  wind_speed_120m: '120m 风速',
  wind_speed_180m: '180m 风速',
  wind_speed_850hPa: '850hPa 风速',
  wind_speed_500hPa: '500hPa 风速',
  wind_speed_200hPa: '200hPa 风速',
  temperature_2m: '实时气温',
  temperature_80m: '80m 气温',
  temperature_120m: '120m 气温',
  temperature_180m: '180m 气温',
  temperature_850hPa: '850hPa 气温',
  temperature_500hPa: '500hPa 气温',
  temperature_200hPa: '200hPa 气温',
  precipitation: '实时降水',
  relative_humidity_2m: '实时湿度',
  pressure_msl: '实时气压',
  visibility: '实时能见度',
}

function asWeatherRecord(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === 'object' ? (value as Record<string, unknown>) : null
}

function readWeatherMetricValue(
  source: unknown,
  metricKey: string | null | undefined,
): number | null {
  if (!metricKey) return null
  const record = asWeatherRecord(source)
  const value = record?.[metricKey]
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function normalizeWeatherUnit(unit: string | null | undefined): string {
  if (unit === 'C') return '°C'
  return unit ?? ''
}

const pointWeatherMetric = computed(() => {
  const metricKey =
    props.pointWeather?.render_hint?.primary_metric ??
    weatherRenderHint.value?.primary_metric ??
    layersStore.getLayerPrimaryMetric(displayLayer.value.catalogId) ??
    'temperature_2m'
  const unit =
    props.pointWeather?.render_hint?.unit_label ?? weatherRenderHint.value?.unit_label ?? ''
  return {
    key: metricKey,
    label: WEATHER_METRIC_LABELS[metricKey] ?? '实时指标',
    unit: normalizeWeatherUnit(unit),
  }
})

const pointWeatherPrimaryLabel = computed(() => pointWeatherMetric.value.label)

// ── 元数据详情 ──────────────────────────────────────────────────────────────
const layerMetadata = computed(() => {
  const dl = displayLayer.value
  const weather = props.pointWeather
  const meta: { label: string; value: string }[] = [
    { label: '数据源', value: dl.sourceLabel || '—' },
    { label: '更新频率', value: dl.updateLabel || '—' },
    { label: '观测时间', value: dl.observationTimeLabel || '—' },
    { label: '可用性', value: dl.availabilityLabel || '—' },
  ]
  if (weather) {
    meta.push({ label: '数据提供方', value: weather.provider || '—' })
    meta.push({ label: '气象模型', value: weather.model || '—' })
    meta.push({ label: '缓存状态', value: weather.cache_status || '—' })
  }
  if (dl.jobLayer) {
    meta.push({ label: '作业状态', value: dl.jobLayer.status || '—' })
    if (dl.jobLayer.diagnosticNotes?.length) {
      meta.push({ label: '诊断', value: dl.jobLayer.diagnosticNotes.slice(0, 2).join('；') })
    }
  }
  return meta
})

// ── 叠加图层列表 ────────────────────────────────────────────────────────────
const overlayLayers = computed(() => {
  const timeStateMap = new Map((props.overlayTimeStates ?? []).map((s) => [s.layerId, s]))
  return layersStore.activeLayersDisplay
    .filter((l) => l.visible && Boolean(l.importedRasterOverlayLayerId))
    .map((l) => {
      const overlayLayerId = l.importedRasterOverlayLayerId ?? l.catalogId
      const ts = timeStateMap.get(overlayLayerId)
      return {
        name: l.name,
        category: l.category,
        availabilityState: l.availabilityState,
        accentColor: l.accentColor,
        catalogId: l.catalogId,
        overlayLayerId,
        palette: ts?.palette ?? null,
        vmin: ts?.vmin ?? null,
        vmax: ts?.vmax ?? null,
        unit: ts?.unit ?? '',
        currentTime: ts?.currentTime ?? null,
        isTimeSeries: ts?.category === 'time-series',
      }
    })
})

// ── 叠加图层像素值查询结果 ──────────────────────────────────────────────────
const overlayPointValueMap = computed(() => {
  const m = new Map<string, import('../services/runtime-api').OverlayPointValue>()
  for (const v of props.overlayPointValues ?? []) {
    m.set(v.layer_id, v)
  }
  return m
})

// ── 历史趋势方向识别 ────────────────────────────────────────────────────────
const trendDirection = computed<'up' | 'down' | 'flat'>(() => {
  const text = displayLayer.value?.trendLabel ?? ''
  if (/上升|增长|偏高|高于|增|升|回暖/.test(text)) return 'up'
  if (/下降|降低|偏低|低于|减|降|转凉/.test(text)) return 'down'
  return 'flat'
})
const trendArrowSymbol = computed(() => {
  if (trendDirection.value === 'up') return '↗'
  if (trendDirection.value === 'down') return '↘'
  return '→'
})
const pointWeatherPrimaryValue = computed(() => {
  const weather = props.pointWeather
  if (!weather) return '--'
  const hourIdx = Math.max(0, Math.floor(props.inspectHour ?? 0))
  const hourly = weather.hourly ?? []
  if (hourly.length > 0 && hourIdx < hourly.length) {
    const entry = hourly[hourIdx]
    const metricValue =
      typeof entry.primary_value === 'number'
        ? entry.primary_value
        : readWeatherMetricValue(entry, pointWeatherMetric.value.key)
    return formatMetric(metricValue, pointWeatherMetric.value.unit)
  }
  return formatMetric(
    readWeatherMetricValue(weather.current, pointWeatherMetric.value.key),
    pointWeatherMetric.value.unit,
  )
})

/** 点查主指标原始数值（供缓冲工具展示中心点当前值） */
const pointWeatherNumericValue = computed((): number | null => {
  const weather = props.pointWeather
  if (!weather) return null
  const hourIdx = Math.max(0, Math.floor(props.inspectHour ?? 0))
  const hourly = weather.hourly ?? []
  if (hourly.length > 0 && hourIdx < hourly.length) {
    const entry = hourly[hourIdx]
    if (typeof entry.primary_value === 'number' && Number.isFinite(entry.primary_value)) {
      return entry.primary_value
    }
    return readWeatherMetricValue(entry, pointWeatherMetric.value.key)
  }
  return readWeatherMetricValue(weather.current, pointWeatherMetric.value.key)
})

const pointWeatherRows = computed(() => {
  const weather = props.pointWeather
  if (!weather) return []
  const primaryValue = pointWeatherPrimaryValue.value
  return [
    {
      label: INSPECT_COPY.fieldPoint,
      value:
        weather.place_name ?? `${weather.latitude.toFixed(3)}, ${weather.longitude.toFixed(3)}`,
    },
    {
      label: INSPECT_COPY.fieldLayer,
      value: weather.layer_id || displayLayer.value.catalogId || '—',
    },
    { label: INSPECT_COPY.fieldModel, value: weather.model },
    {
      label: pointWeatherMetric.value.label,
      value: primaryValue,
    },
    {
      label: INSPECT_COPY.fieldObserved,
      value: weather.observation_time ? formatTime(weather.observation_time) : '--',
    },
  ]
})
const pointWeatherHourlyRows = computed(() => {
  const weather = props.pointWeather
  if (!weather) return []
  const activeHour = Math.max(0, Math.floor(props.inspectHour ?? 0))
  return (weather.hourly ?? [])
    .slice(0, Math.max(8, activeHour + 1))
    .map((entry, index) => {
      const metricValue =
        typeof entry.primary_value === 'number'
          ? entry.primary_value
          : readWeatherMetricValue(entry, pointWeatherMetric.value.key)
      const metric = formatMetric(metricValue, pointWeatherMetric.value.unit)
      return {
        time: formatHour(entry.time),
        metric,
        active: index === activeHour,
      }
    })
    .filter((entry) => entry.metric !== `-- ${pointWeatherMetric.value.unit}`.trim())
})

const pointWeatherHourlyChartRows = computed(() => {
  return pointWeatherHourlyRows.value.map((row) => ({
    time: row.time,
    metric: row.metric,
    active: row.active,
  }))
})

const multiOverlayBarItems = computed(() => {
  const list = overlayLayers.value ?? []
  return list.map((layer) => {
    const pt = overlayPointValueMap.value.get(layer.overlayLayerId)
    const val = pt?.value ?? null
    return {
      layerId: layer.overlayLayerId,
      name: layer.name,
      category: layer.category,
      valueText: pt && pt.value !== null ? formatOverlayValue(pt) : 'N/A',
      numericValue: typeof val === 'number' && Number.isFinite(val) ? val : null,
      unit: pt?.unit || layer.unit || '',
      accentColor: layer.accentColor,
    }
  })
})

/** 多层叠加柱状图：有选点且存在其它可见 overlay 即可（不绑天气 section） */
const showMultiOverlayBar = computed(
  () => !!props.selectedMapPoint && multiOverlayBarItems.value.length > 0,
)

const selectedOverlayTimeSeriesRows = computed(() => {
  const activeTime = (props.overlayTimeStates ?? []).find(
    (s) => s.layerId === displayLayer.value.importedRasterOverlayLayerId,
  )?.currentTime
  return (props.selectedOverlayTimeSeries ?? [])
    .filter((item) => item.time)
    .map((item) => ({
      time: item.time!.replace('_', ' → '),
      metric: formatOverlayValue(item),
      numericValue:
        typeof item.value === 'number' && Number.isFinite(item.value) ? item.value : undefined,
      active: item.time === activeTime,
    }))
})

const showSelectedOverlayTimeSeries = computed(
  () => !!props.selectedMapPoint && selectedOverlayTimeSeriesRows.value.length > 0,
)

/** 汇报演示兜底：未点地图时，允许按当前选中图层默认数据点展示时序。 */
const showDemoOverlayTimeSeries = computed(
  () => !props.selectedMapPoint && selectedOverlayTimeSeriesRows.value.length > 0,
)

const analysisCharts = computed(() => jobLayer.value?.analysisCharts ?? [])
const analysisTables = computed(() => jobLayer.value?.analysisTables ?? [])
const hasAnalysisCharts = computed(
  () => analysisCharts.value.length > 0 || analysisTables.value.length > 0,
)

const hasVisualTabContent = computed(
  () =>
    hasAnalysisCharts.value ||
    hasPointWeatherSection.value ||
    showMultiOverlayBar.value ||
    showSelectedOverlayTimeSeries.value ||
    showDemoOverlayTimeSeries.value ||
    displayLayer.value.isImportedRaster ||
    !!resultModel.value ||
    props.visibleHotspots.length > 0,
)

const pointInspectStatusLabel = computed(() => {
  if (props.pointWeatherLoading) return INSPECT_COPY.statusQuerying
  if (props.pointWeatherError) return INSPECT_COPY.statusFailed
  if (props.pointWeather) return props.pointWeather.cache_status || INSPECT_COPY.statusReady
  if (uiStore.interactionMode === 'select') return INSPECT_COPY.statusWaitingClick
  return INSPECT_COPY.statusNeedSelectMode
})
const canRunWorkflow = computed(
  () =>
    !displayLayer.value?.isAdminBoundary &&
    !displayLayer.value?.isImported &&
    !displayLayer.value?.isImportedRaster &&
    !isRealtimeWeatherLayer.value &&
    layersStore.supportsAnalysisWorkflow(displayLayer.value.catalogId),
)
const isWorkflowRunning = computed(
  () => jobLayer.value?.status === 'running' || jobLayer.value?.status === 'queued',
)
const runBlockedReason = computed(() =>
  layersStore.getCatalogRunBlockReason(displayLayer.value.catalogId),
)
const workflowStage = computed(() => {
  if (props.isSubmitting) return 'submitting'
  if (isRealtimeWeatherLayer.value) {
    return resolveWeatherWorkflowStage(tileStats.value)
  }
  if (jobLayer.value?.status === 'queued') return 'queued'
  if (jobLayer.value?.status === 'running') return 'running'
  if (jobLayer.value?.status === 'succeeded') return 'succeeded'
  if (jobLayer.value?.status === 'failed') return 'failed'
  return 'idle'
})

/** 从图层目录中查找关联的工作流名称和引擎 */
const workflowMeta = computed(() => {
  const cid = displayLayer.value.catalogId
  if (!cid) return { name: '', engine: '', engineLabel: '', engineIcon: '' }
  const libItem = layersStore.layerLibrary.find((l) => l.catalogId === cid)
  const engine = libItem?.engine ?? displayLayer.value.engine ?? ''
  const name = libItem?.workflowName ?? ''
  const engineLabel =
    engine === 'weather'
      ? '天气引擎'
      : engine === 'python_provider'
        ? 'Python 处理器'
        : engine === 'gee'
          ? 'GEE'
          : engine === 'general'
            ? '通用'
            : ''
  const engineIcon =
    engine === 'weather' ? '☀' : engine === 'python_provider' ? '⚡' : engine === 'gee' ? '🌍' : '◈'
  return { name, engine, engineLabel, engineIcon }
})

/** 工作流进度（0-100） */
const workflowProgress = computed(() => {
  if (!jobLayer.value) return 0
  return Math.max(0, Math.min(100, jobLayer.value.progress ?? 0))
})

/** 最近事件消息 */
const latestEventMessage = computed(() => {
  const msgs = jobLayer.value?.eventMessages
  if (!msgs || msgs.length === 0) return ''
  return msgs[msgs.length - 1]
})

const hasRealSelection = computed(() => Boolean(displayLayer.value.instanceId))

/** 图表 Tab 稀疏态说明（有选中但尚无图表载荷） */
const sparseVisualHint = computed(() => {
  if (isRealtimeWeatherLayer.value) return ANALYSIS_COPY.sparseVisualWeather
  if (canRunWorkflow.value) return ANALYSIS_COPY.sparseVisualWorkflow
  return ANALYSIS_COPY.sparseVisualStatic
})

const analysisStageKind = computed(() =>
  resolveAnalysisStageKind({
    hasRealSelection: hasRealSelection.value,
    isWeather: isRealtimeWeatherLayer.value,
    isImported: !!displayLayer.value.isImported,
    isImportedRaster: !!displayLayer.value.isImportedRaster,
    isAdminBoundary: !!displayLayer.value.isAdminBoundary,
    canRunWorkflow: canRunWorkflow.value,
  }),
)

const hasWeatherTileActivity = computed(() => {
  const stats = tileStats.value
  if (!stats) return false
  return stats.pending > 0 || stats.cached > 0
})

const showWorkflowStageRow = computed(
  () =>
    canRunWorkflow.value ||
    isWorkflowRunning.value ||
    (isRealtimeWeatherLayer.value && hasRealSelection.value && hasWeatherTileActivity.value),
)

const workflowStageCopy = computed(() =>
  resolveWorkflowStageCopy({
    stage: workflowStage.value,
    progress: workflowProgress.value,
    isWeather: isRealtimeWeatherLayer.value && hasRealSelection.value,
    tilePending: tileStats.value?.pending ?? 0,
    tileCached: tileStats.value?.cached ?? 0,
    tileVisible: tileStats.value?.visible ?? 0,
  }),
)

const weatherTopLines = computed(() => {
  if (!hasRealSelection.value || !isRealtimeWeatherLayer.value) return [] as string[]
  const lines: string[] = [ANALYSIS_COPY.weatherAutoLoad]
  const stats = tileStats.value
  if (stats) {
    lines.push(ANALYSIS_COPY.weatherTileLine(stats.cached, stats.visible, stats.pending))
  } else {
    lines.push(ANALYSIS_COPY.weatherNoTilesYet)
  }
  const timeLabel = displayLayer.value.observationTimeLabel
  if (timeLabel && timeLabel !== '—') {
    lines.push(`${ANALYSIS_COPY.metaTime}：${timeLabel}`)
  }
  if (canToggleParticleFlow.value) {
    lines.push(ANALYSIS_COPY.weatherWindMode(windStyleChipLabel.value))
  }
  const source = displayLayer.value.sourceLabel
  if (source && source !== '—') {
    lines.push(`${ANALYSIS_COPY.metaSource}：${source}`)
  }
  return lines
})

const staticTopHint = computed(() => resolveStaticLayerHint(analysisStageKind.value))

const analysisScrollEl = ref<HTMLElement | null>(null)
const topSummaryEl = ref<HTMLElement | null>(null)
// 待清理的 setTimeout 句柄（组件卸载时统一清理，避免回调在卸载后执行）
const pendingTimers: number[] = []

function formatMetric(value: number | null | undefined, unit: string) {
  if (typeof value !== 'number' || Number.isNaN(value)) return `-- ${unit}`.trim()
  return `${value.toFixed(1)} ${unit}`.trim()
}

function formatOverlayValue(v: import('../services/runtime-api').OverlayPointValue): string {
  if (v.value === null || v.value === undefined) return 'N/A'
  const digits = Math.abs(v.value) >= 100 ? 1 : 3
  return `${v.value.toFixed(digits)} ${v.unit}`.trim()
}

function formatTime(value: string) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString()
}

function formatHour(value: string) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return `${String(date.getHours()).padStart(2, '0')}:00`
}

function handleToggleLayerVisibility() {
  if (!displayLayer.value?.instanceId) return
  emit('toggleLayerVisibility', displayLayer.value.instanceId)
}

function handleLayerOpacityInput(event: Event) {
  if (!displayLayer.value?.instanceId) return
  const target = event.target as HTMLInputElement
  emit('setLayerOpacity', {
    instanceId: displayLayer.value.instanceId,
    opacity: Number(target.value) / 100,
  })
}

function scrollAnalysisIntoView(selector: string) {
  const t = window.setTimeout(() => {
    const el = analysisScrollEl.value?.querySelector(selector) as HTMLElement | null
    el?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }, 0)
  pendingTimers.push(t)
}

function scrollToTopSummary() {
  const t = window.setTimeout(() => {
    topSummaryEl.value?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }, 0)
  pendingTimers.push(t)
}

async function focusRequestedAnalysisSection(ids: string[], token: number) {
  const normalized = normalizeAnalysisFocusIds(ids)
  const tab = resolveAnalysisTabForFocusIds(normalized)
  if (tab) activeTab.value = tab
  await nextTick()
  let attempt = 0

  const tryFocus = () => {
    const container = analysisScrollEl.value
    if (!container) return
    const target = normalized
      .map((id) => {
        try {
          return container.querySelector<HTMLElement>(`#${CSS.escape(id)}`)
        } catch {
          return container.querySelector<HTMLElement>(`#${id}`)
        }
      })
      .find((element) => element !== null)
    if (target) {
      target.scrollIntoView({ behavior: 'smooth', block: 'start' })
      uiStore.clearAnalysisFocusRequest(token)
      return
    }
    if (attempt >= 3) {
      uiStore.clearAnalysisFocusRequest(token)
      return
    }
    attempt += 1
    const retryTimer = window.setTimeout(tryFocus, 90)
    pendingTimers.push(retryTimer)
  }

  tryFocus()
}

watch(
  () => displayLayer.value?.instanceId,
  (instanceId) => {
    scrollToTopSummary()
    // 「查看报告」等显式焦点优先
    if (uiStore.analysisFocusRequest) return
    if (!instanceId) {
      if (activeTab.value === 'style') activeTab.value = 'visual'
      return
    }
    // 导入层：切到元数据并滚到导入专项（导出/属性）
    if (displayLayer.value.isImported || displayLayer.value.isImportedRaster) {
      activeTab.value = 'meta'
      void scrollAnalysisIntoView('#imported-layer')
      return
    }
    // 当前 Tab 对该层无内容时回退，避免样式空白页
    if (activeTab.value === 'style' && !hasLayerStyleSection.value) {
      activeTab.value = 'visual'
    }
  },
  { immediate: true },
)

watch(
  () => props.selectedHotspot?.id,
  (hotspotId) => {
    scrollToTopSummary()
    if (hotspotId) {
      activeTab.value = 'visual'
      void scrollAnalysisIntoView(`#hotspot-${hotspotId}`)
      return
    }
    if (props.visibleHotspots.length > 0) {
      activeTab.value = 'visual'
      void scrollAnalysisIntoView('#hotspot-section')
    }
  },
)

/** 天气点查开始或结果到达 → 图表 Tab，避免人停在工具而结果在别处 */
watch(
  () => [props.pointWeatherLoading, !!props.pointWeather, !!props.pointWeatherError] as const,
  ([loading, hasResult, hasError], prev) => {
    if (!isRealtimeWeatherLayer.value) return
    const becameActive =
      (loading && !prev?.[0]) || (hasResult && !prev?.[1]) || (hasError && !prev?.[2])
    if (becameActive) activeTab.value = 'visual'
  },
)

watch(
  () => uiStore.analysisFocusRequest,
  (request) => {
    if (!request) return
    void focusRequestedAnalysisSection(request.ids, request.token)
  },
)

onBeforeUnmount(() => {
  pendingTimers.forEach((t) => window.clearTimeout(t))
  pendingTimers.length = 0
  if (importHintTimer !== null) {
    window.clearTimeout(importHintTimer)
    importHintTimer = null
  }
  if (weatherProvidersAbort) {
    weatherProvidersAbort.abort()
    weatherProvidersAbort = null
  }
})
</script>

<template>
  <aside class="panel" :style="{ '--accent-color': displayLayer.accentColor }">
    <!-- 无选中：整页空态，不展示 Tab / 分区壳 -->
    <div v-if="!hasRealSelection" ref="analysisScrollEl" class="analysis-idle">
      <div class="analysis-idle-orb" aria-hidden="true"></div>
      <p class="analysis-idle-kicker">{{ ANALYSIS_COPY.panelTitle }}</p>
      <h2 class="analysis-idle-title">{{ ANALYSIS_COPY.emptyTitle }}</h2>
      <p class="analysis-idle-lead">{{ ANALYSIS_COPY.emptyLeadShort }}</p>
      <ul class="analysis-idle-steps">
        <li>{{ ANALYSIS_COPY.emptyStepAdd }}</li>
        <li>{{ ANALYSIS_COPY.emptyStepInspect }}</li>
        <li>{{ ANALYSIS_COPY.emptyStepStyle }}</li>
      </ul>
    </div>

    <template v-else>
      <!-- Tab 始终贴顶 -->
      <div class="panel-sticky-chrome">
        <div class="dashboard-nav-tabs">
          <button
            type="button"
            class="dash-tab"
            :class="{ active: activeTab === 'visual' }"
            @click="setActiveTab('visual')"
          >
            图表
          </button>
          <button
            type="button"
            class="dash-tab"
            :class="{ active: activeTab === 'tools' }"
            @click="setActiveTab('tools')"
          >
            工具
          </button>
          <button
            type="button"
            class="dash-tab"
            :class="{ active: activeTab === 'style' }"
            @click="setActiveTab('style')"
          >
            样式
          </button>
          <button
            type="button"
            class="dash-tab"
            :class="{ active: activeTab === 'meta' }"
            @click="setActiveTab('meta')"
          >
            元数据
          </button>
        </div>
        <div class="panel-stage-row">
          <span class="readiness readiness--inline" :title="stageLabel">{{ stageLabel }}</span>
        </div>
      </div>

      <div ref="analysisScrollEl" class="panel-scroll">
        <div ref="topSummaryEl" class="panel-topline">
          <div v-if="workflowError" class="workflow-error">
            <span class="error-icon">⚠️</span>
            <span class="error-message">{{ workflowError }}</span>
          </div>

          <!-- 天气层：短摘要（详细进元数据 Tab） -->
          <div v-if="isRealtimeWeatherLayer" class="analysis-context-card">
            <p class="analysis-context-line">
              {{ displayLayer.name }}
              <span v-if="weatherTopLines[0]"> · {{ weatherTopLines[0] }}</span>
            </p>
          </div>

          <!-- 导入/边界/静态：短说明 -->
          <div v-else-if="!canRunWorkflow" class="analysis-context-card">
            <p class="analysis-context-line">{{ displayLayer.name }} · {{ staticTopHint }}</p>
          </div>

          <!-- 可跑工作流：引擎信息 + 进度（运行入口在侧栏右键 / 编辑器） -->
          <template v-else>
            <div v-if="runBlockedReason" class="run-block-hint">
              {{ runBlockedReason }}
            </div>
            <div v-if="workflowMeta.engineLabel" class="workflow-meta-row">
              <span class="wf-engine-icon" aria-hidden="true">{{ workflowMeta.engineIcon }}</span>
              <span class="wf-engine-label">{{ workflowMeta.engineLabel }}</span>
              <span v-if="workflowMeta.name" class="wf-name">{{ workflowMeta.name }}</span>
            </div>
          </template>

          <!-- 阶段行：仅工作流运行中，或天气确有瓦片活动时 -->
          <div v-if="showWorkflowStageRow" class="workflow-stage-row">
            <span class="stage-pill" :class="workflowStage">{{ workflowStage }}</span>
            <span class="stage-copy">{{ workflowStageCopy }}</span>
          </div>

          <div
            v-if="canRunWorkflow && (isWorkflowRunning || workflowStage === 'succeeded')"
            class="wf-progress-bar"
          >
            <div
              class="wf-progress-fill"
              :class="workflowStage"
              :style="{ width: workflowProgress + '%' }"
            ></div>
          </div>

          <div v-if="canRunWorkflow && latestEventMessage" class="wf-event-msg">
            <span class="wf-event-dot" :class="workflowStage"></span>
            <span class="wf-event-text">{{ latestEventMessage }}</span>
          </div>
        </div>

        <div class="analysis-stream">
          <!-- ── meta Tab ─────────────────────────────────────────────────── -->
          <section
            v-show="activeTab === 'meta'"
            id="global-overview"
            class="analysis-section analysis-section--overview"
          >
            <div class="section-kicker">{{ ANALYSIS_COPY.overviewKicker }}</div>
            <h3>
              {{
                showCompactHero
                  ? ANALYSIS_COPY.overviewTitleCompact
                  : ANALYSIS_COPY.overviewTitleFull
              }}
            </h3>
            <p>{{ analysisSummary }}</p>
            <div class="overview-quick-actions">
              <button
                v-if="isRealtimeWeatherLayer && uiStore.interactionMode !== 'select'"
                type="button"
                class="weather-mini-btn"
                @click="enterInspectTools"
              >
                {{ ANALYSIS_COPY.toolsQuickInspect }}
              </button>
              <button
                v-if="canRunWorkflow"
                type="button"
                class="weather-mini-btn"
                @click="setActiveTab('tools')"
              >
                {{ ANALYSIS_COPY.toolsQuickBuffer }}
              </button>
              <button
                v-if="hasLayerStyleSection"
                type="button"
                class="weather-mini-btn"
                @click="setActiveTab('style')"
              >
                符号样式
              </button>
            </div>
          </section>

          <section
            v-if="displayLayer.isImported || displayLayer.isImportedRaster"
            v-show="activeTab === 'meta'"
            id="imported-layer"
            class="analysis-section analysis-section--imported"
          >
            <div class="section-kicker">{{ ANALYSIS_COPY.importedSectionKicker }}</div>
            <h3>{{ ANALYSIS_COPY.importedSectionTitle }}</h3>
            <dl class="meta-list imported-meta">
              <div v-if="displayLayer.isImported">
                <dt>{{ ANALYSIS_COPY.metaGeometry }}</dt>
                <dd>{{ displayLayer.importedGeometryType ?? '—' }}</dd>
              </div>
              <div v-if="displayLayer.isImported">
                <dt>{{ ANALYSIS_COPY.metaFeatures }}</dt>
                <dd>{{ displayLayer.importedFeatureCount ?? 0 }}</dd>
              </div>
              <div v-if="displayLayer.isImportedRaster">
                <dt>{{ ANALYSIS_COPY.metaMode }}</dt>
                <dd>{{ ANALYSIS_COPY.importedRasterType }}</dd>
              </div>
              <div v-if="displayLayer.isImportedRaster">
                <dt>{{ ANALYSIS_COPY.metaCrs }}</dt>
                <dd>{{ displayLayer.importedRasterSourceCrs ?? '—' }}</dd>
              </div>
              <div v-if="displayLayer.isImportedRaster && displayLayer.importedRasterNativeStep">
                <dt>{{ ANALYSIS_COPY.metaNativeStep }}</dt>
                <dd>{{ displayLayer.importedRasterNativeStep }}</dd>
              </div>
              <div v-if="displayLayer.isImportedRaster && displayLayer.importedRasterEffectiveTime">
                <dt>{{ ANALYSIS_COPY.metaEffectiveTime }}</dt>
                <dd>{{ displayLayer.importedRasterEffectiveTime }}</dd>
              </div>
              <div
                v-if="
                  displayLayer.isImportedRaster && (displayLayer.importedRasterTimeCount ?? 0) > 0
                "
              >
                <dt>{{ ANALYSIS_COPY.metaTimeSlices }}</dt>
                <dd>{{ displayLayer.importedRasterTimeCount }}</dd>
              </div>
              <div v-if="displayLayer.isImportedRaster">
                <dt>叠加层 ID</dt>
                <dd class="mono">{{ displayLayer.catalogId }}</dd>
              </div>
              <div v-if="displayLayer.importedFileName">
                <dt>{{ ANALYSIS_COPY.metaFile }}</dt>
                <dd>{{ displayLayer.importedFileName }}</dd>
              </div>
              <div>
                <dt>{{ ANALYSIS_COPY.metaBounds }}</dt>
                <dd>
                  {{
                    formatBounds(displayLayer.importedBounds ?? displayLayer.importedRasterBounds)
                  }}
                </dd>
              </div>
              <div>
                <dt>{{ ANALYSIS_COPY.metaSource }}</dt>
                <dd>{{ displayLayer.sourceLabel }}</dd>
              </div>
            </dl>
            <div v-if="displayLayer.isImported" class="imported-export-row">
              <button
                class="imported-export-btn"
                type="button"
                @click="
                  openDataWorkspace({
                    tab: 'attributes',
                    layerInstanceId: displayLayer.instanceId,
                  })
                "
              >
                {{ DATA_COPY.openAttrTable }}
              </button>
              <button
                class="imported-export-btn"
                type="button"
                @click="
                  openDataWorkspace({
                    tab: 'details',
                    layerInstanceId: displayLayer.instanceId,
                  })
                "
              >
                {{ DATA_COPY.openDetails }}
              </button>
              <button class="imported-export-btn" type="button" @click="exportImportedGeoJson">
                {{ LAYERS_COPY.exportGeoJson }}
              </button>
              <button class="imported-export-btn" type="button" @click="exportImportedCsv">
                {{ LAYERS_COPY.exportCsv }}
              </button>
            </div>
            <div v-else-if="displayLayer.isImportedRaster" class="imported-export-row">
              <button
                class="imported-export-btn"
                type="button"
                @click="
                  openDataWorkspace({
                    tab: 'details',
                    layerInstanceId: displayLayer.instanceId,
                  })
                "
              >
                {{ DATA_COPY.openDetails }}
              </button>
              <button
                class="imported-export-btn"
                type="button"
                @click="exportImportedRaster('png')"
              >
                {{ LAYERS_COPY.exportPng }}
              </button>
              <button
                class="imported-export-btn"
                type="button"
                @click="exportImportedRaster('tif')"
              >
                {{ LAYERS_COPY.exportTif }}
              </button>
            </div>
            <p
              v-if="importActionHint"
              class="imported-action-hint"
              :class="{ error: importActionHint.includes('失败') }"
            >
              {{ importActionHint }}
            </p>
          </section>

          <section
            v-if="jobLayer"
            v-show="activeTab === 'meta'"
            id="scheduler-status"
            class="job-report-card job-report-card--summary"
          >
            <div class="job-report-header">
              <div>
                <div class="section-kicker">任务调度</div>
                <span class="job-report-title">任务总览</span>
              </div>
              <span class="job-status-chip" :class="`job-${jobLayer.status}`">
                {{
                  jobLayer.status === 'running'
                    ? `运行中 ${jobLayer.progress}%`
                    : jobLayer.status === 'succeeded'
                      ? '已完成'
                      : jobLayer.status === 'failed'
                        ? '失败'
                        : jobLayer.status
                }}
              </span>
            </div>

            <div class="job-progress-shell">
              <div v-if="jobLayer.status === 'running'" class="job-progress-row">
                <div class="job-progress-bar">
                  <div class="job-progress-fill" :style="{ width: `${jobLayer.progress}%` }"></div>
                </div>
                <span class="job-progress-label">{{ jobLayer.progress }}%</span>
              </div>
              <p class="job-message">{{ jobLayer.message || '作业正在处理中...' }}</p>
              <div v-if="jobLayer.nodeProgress?.length" class="job-node-progress-section">
                <div
                  v-for="np in jobLayer.nodeProgress"
                  :key="np.nodeId"
                  class="job-node-progress-item"
                >
                  <div class="job-node-progress-header">
                    <span>{{ np.nodeLabel }}</span>
                    <span>{{ np.progress }}%</span>
                  </div>
                  <div class="job-node-progress-bar">
                    <div class="job-node-progress-fill" :style="{ width: `${np.progress}%` }"></div>
                  </div>
                  <p v-if="np.message" class="job-node-progress-message">{{ np.message }}</p>
                  <p
                    v-if="
                      np.detail &&
                      (np.detail.chunksTotal ||
                        np.detail.pixelsTotal ||
                        np.detail.blocksTotal ||
                        np.detail.dateStart)
                    "
                    class="job-node-progress-detail"
                  >
                    <template v-if="np.detail.blocksTotal">
                      块 {{ np.detail.blocksDone ?? 0 }}/{{ np.detail.blocksTotal }}
                      <template v-if="np.detail.dateStart && np.detail.dateEnd">
                        · {{ np.detail.dateStart }}–{{ np.detail.dateEnd }}
                      </template>
                    </template>
                    <template v-else-if="np.detail.chunksTotal">
                      数据块 {{ np.detail.chunksDone ?? 0 }}/{{ np.detail.chunksTotal }}
                    </template>
                    <template v-if="np.detail.pixelsTotal">
                      · 像素 {{ np.detail.pixelsDone ?? 0 }}/{{ np.detail.pixelsTotal }}
                    </template>
                    <template v-if="np.detail.phase"> · {{ np.detail.phase }}</template>
                  </p>
                </div>
              </div>
              <ul v-if="jobEventNotes.length" class="job-diagnostic-list">
                <li
                  v-for="(note, idx) in jobEventNotes"
                  :key="`job-note-${idx}`"
                  class="job-diagnostic-item"
                >
                  {{ note }}
                </li>
              </ul>
            </div>

            <div class="job-steps">
              <div class="job-step">1. 提交任务</div>
              <div
                class="job-step"
                :class="{ active: workflowStage === 'queued' || workflowStage === 'running' }"
              >
                2. 等待运行结果
              </div>
              <div class="job-step" :class="{ active: !!resultModel }">3. 读取视图</div>
            </div>
          </section>

          <section
            v-if="jobLayer"
            v-show="activeTab === 'meta'"
            id="report-section"
            class="analysis-section analysis-section--report"
          >
            <div class="section-kicker">报告</div>
            <div class="report-section-head">
              <div>
                <h3>工作流报告</h3>
                <p>
                  {{
                    jobLayer.status === 'running' || jobLayer.status === 'queued'
                      ? '运行中：下方为实时进度与已产出摘要。'
                      : '这里展示该图层当前任务的摘要与结果说明。'
                  }}
                </p>
              </div>
              <a
                v-if="jobLayer.resultUrl"
                class="job-result-link"
                :href="jobLayer.resultUrl"
                target="_blank"
                rel="noreferrer"
              >
                打开结果
              </a>
            </div>
            <p v-if="jobReportSummary" class="job-report-copy">{{ jobReportSummary }}</p>
            <p v-else class="job-report-copy">{{ jobLayer.message || '暂无摘要' }}</p>

            <div v-if="jobLayer.nodeProgress?.length" class="report-block">
              <h4>进度时间线</h4>
              <ul class="report-node-list">
                <li v-for="np in jobLayer.nodeProgress" :key="np.nodeId">
                  <strong>{{ np.nodeLabel || np.nodeId }}</strong>
                  <span>{{ np.stage }} · {{ np.progress }}%</span>
                  <span v-if="np.message" class="report-node-msg">{{ np.message }}</span>
                </li>
              </ul>
            </div>

            <div
              v-if="jobLayer.eventMessages?.length || jobLayer.diagnosticNotes?.length"
              class="report-block"
            >
              <h4>事件 / 诊断</h4>
              <ul class="report-node-list">
                <li
                  v-for="(note, idx) in (jobLayer.eventMessages?.length
                    ? jobLayer.eventMessages
                    : jobLayer.diagnosticNotes
                  )?.slice(0, 12)"
                  :key="`note-${idx}`"
                >
                  {{ note }}
                </li>
              </ul>
            </div>

            <div v-if="displayLayer?.isImportedRaster" class="report-block">
              <h4>导出</h4>
              <div class="weather-layer-btn-row" style="gap: 0.4rem">
                <button type="button" class="weather-mini-btn" @click="exportImportedRaster('png')">
                  PNG
                </button>
                <button type="button" class="weather-mini-btn" @click="exportImportedRaster('tif')">
                  GeoTIFF
                </button>
              </div>
            </div>
          </section>

          <section
            v-show="activeTab === 'meta'"
            :id="`layer-${displayLayer.instanceId || 'default'}`"
            class="analysis-section analysis-section--layer"
          >
            <div class="section-kicker">{{ ANALYSIS_COPY.selectedLayerKicker }}</div>
            <h3>{{ ANALYSIS_COPY.selectedLayerTitle }}</h3>
            <p>
              {{ displayLayer.name }}
              <span v-if="displayLayer.availabilityLabel">
                · {{ displayLayer.availabilityLabel }}</span
              >
            </p>
            <p class="tools-empty-hint" style="margin-top: 0.35rem">
              透明度与符号请到「样式」Tab 调整。
            </p>
          </section>

          <!-- ── tools Tab ────────────────────────────────────────────────── -->
          <section
            v-show="activeTab === 'tools'"
            id="analysis-tools"
            class="analysis-section analysis-section--tools"
          >
            <div class="section-kicker">工具</div>
            <h3>分析工具</h3>
            <div class="weather-layer-btn-row" style="margin-bottom: 0.55rem; gap: 0.4rem">
              <button
                v-if="uiStore.interactionMode !== 'select'"
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
              :current-value-text="
                pointWeatherPrimaryValue !== '--' ? pointWeatherPrimaryValue : undefined
              "
              :current-numeric-value="pointWeatherNumericValue"
            />
          </section>

          <!-- ── visual Tab：工作流图表结果 ─────────────────────────────── -->
          <section
            v-if="hasAnalysisCharts"
            v-show="activeTab === 'visual'"
            id="workflow-charts"
            class="analysis-section"
          >
            <AnalysisResultCharts :charts="analysisCharts" :tables="analysisTables" />
          </section>

          <!-- ── visual Tab：点查图表 ──────────────────────────────────────── -->
          <section
            v-if="hasPointWeatherSection"
            v-show="activeTab === 'visual'"
            id="point-weather"
            class="analysis-section analysis-section--weather"
          >
            <div class="section-kicker">{{ INSPECT_COPY.sectionKicker }}</div>
            <div class="weather-section-head">
              <div>
                <h3>{{ INSPECT_COPY.sectionTitle }}</h3>
                <p v-if="!pointWeather && !pointWeatherLoading">点选地图后显示数值与时序。</p>
                <p v-else>
                  使用工具栏「选择」后点击地图；漫游模式下可
                  <kbd>Shift</kbd>+点击临时查询。
                </p>
              </div>
              <span class="analysis-chip" :class="{ muted: !pointWeather }">
                {{ pointInspectStatusLabel }}
              </span>
            </div>

            <div
              v-if="!selectedMapPoint && !pointWeather && !pointWeatherLoading"
              class="weather-state"
            >
              尚未选点 — 切到「分析工具」进入选择模式后点击地图。
            </div>
            <div v-if="pointWeatherLoading" class="weather-state weather-state-loading">
              正在获取点查…
            </div>
            <div v-else-if="pointWeatherError" class="weather-state weather-state-error">
              {{ pointWeatherError }}
            </div>
            <template v-else-if="pointWeather">
              <div class="weather-primary-card">
                <span>{{ pointWeatherPrimaryLabel }}</span>
                <strong>{{ pointWeatherPrimaryValue }}</strong>
                <p>{{ pointWeather.summary }}</p>
              </div>

              <div class="weather-row-grid">
                <div v-for="row in pointWeatherRows" :key="row.label" class="weather-row-card">
                  <span>{{ row.label }}</span>
                  <strong>{{ row.value }}</strong>
                </div>
              </div>

              <div v-if="pointWeatherHourlyRows.length" class="weather-hourly-strip">
                <article
                  v-for="row in pointWeatherHourlyRows"
                  :key="row.time"
                  class="weather-hourly-card"
                  :class="{ active: row.active }"
                >
                  <span>{{ row.time }}</span>
                  <strong>{{ row.metric }}</strong>
                </article>
              </div>

              <PointTimeSeriesChart
                v-if="pointWeatherHourlyChartRows.length"
                :hourly-rows="pointWeatherHourlyChartRows"
                :title="pointWeatherMetric.label + ' 时序趋势'"
              />
            </template>
          </section>

          <section
            v-if="showMultiOverlayBar"
            v-show="activeTab === 'visual'"
            id="overlay-compare"
            class="analysis-section analysis-section--overlays"
          >
            <div class="section-kicker">叠加对比</div>
            <h3>可见叠加层点值</h3>
            <p>当前选点处可见各叠加层的采样对比（含当前选中层与非天气层）。</p>
            <MultiOverlayBarChart :items="multiOverlayBarItems" />
          </section>

          <section
            v-if="
              showSelectedOverlayTimeSeries ||
              showDemoOverlayTimeSeries ||
              displayLayer.isImportedRaster
            "
            v-show="activeTab === 'visual'"
            id="overlay-point-series"
            class="analysis-section analysis-section--overlays"
          >
            <div class="section-kicker">点时间序列</div>
            <h3>
              {{ displayLayer.name }} ·
              {{ showDemoOverlayTimeSeries ? '默认有效点时序' : '选点时序' }}
            </h3>
            <p>
              {{
                showDemoOverlayTimeSeries
                  ? '展示当前图层一个稳定有效观测点在全部 8 天块上的数值变化；点击地图可切换为自定义选点。'
                  : '同一选点在全部可用 8 天时间块上的数值变化；高亮当前时间轴块。'
              }}
            </p>
            <button
              v-if="!selectedOverlayTimeSeriesRows.length"
              type="button"
              class="weather-mini-btn"
              @click="queryDefaultOverlaySeries"
            >
              加载当前图层 8 天块时序
            </button>
            <PointTimeSeriesChart
              v-if="selectedOverlayTimeSeriesRows.length"
              :hourly-rows="selectedOverlayTimeSeriesRows"
              :title="displayLayer.name + ' 8 天块时序'"
              :unit="overlayStyleMeta?.unit || ''"
            />
          </section>

          <section
            v-if="hasLayerStyleSection"
            v-show="activeTab === 'style'"
            id="layer-style"
            class="analysis-section analysis-section--style"
          >
            <div class="section-kicker">{{ ANALYSIS_COPY.styleSectionKicker }}</div>
            <div class="weather-style-head">
              <div>
                <h3>{{ ANALYSIS_COPY.styleTitle }}</h3>
                <p>
                  {{
                    displayLayer.isImported
                      ? ANALYSIS_COPY.staticImportedVector
                      : displayLayer.isImportedRaster
                        ? ANALYSIS_COPY.staticImportedRaster
                        : hasAdvancedStyleControls
                          ? canEditPalette
                            ? ANALYSIS_COPY.styleHintLinked
                            : ANALYSIS_COPY.styleHintReadonly
                          : ANALYSIS_COPY.styleHintOpacityOnly
                  }}
                </p>
              </div>
              <span v-if="isRealtimeWeatherLayer || canToggleParticleFlow" class="analysis-chip">{{
                windStyleChipLabel
              }}</span>
            </div>

            <div v-if="displayLayer.instanceId" class="layer-opacity-row">
              <span>{{ LAYERS_COPY.opacity }}</span>
              <input
                class="layer-opacity-slider"
                type="range"
                min="0"
                max="100"
                :value="Math.round(displayLayer.opacity * 100)"
                @input="handleLayerOpacityInput"
              />
              <strong>{{ Math.round(displayLayer.opacity * 100) }}%</strong>
            </div>

            <template v-if="styleFieldLabel || styleRangeMeta.hasRange">
              <div class="style-section-label">{{ LAYERS_COPY.sectionAppearance }}</div>
              <div v-if="styleFieldLabel" class="style-field-row">
                <span class="style-field-label">{{ LAYERS_COPY.fieldLabel }}</span>
                <strong>{{ styleFieldLabel }}</strong>
              </div>
            </template>

            <!-- 导入矢量就地样式 -->
            <div v-if="displayLayer.isImported" class="imported-vector-style">
              <label class="layer-style-row">
                <span>{{ LAYERS_COPY.vectorColor }}</span>
                <input
                  type="color"
                  :value="importedVectorStyle.color || '#4fc3f7'"
                  @input="
                    patchImportedVectorStyle({
                      color: ($event.target as HTMLInputElement).value,
                    })
                  "
                />
              </label>
              <label class="layer-style-row">
                <span>{{ LAYERS_COPY.vectorWidth }}</span>
                <input
                  type="range"
                  min="0.5"
                  max="8"
                  step="0.5"
                  :value="importedVectorStyle.width ?? 2"
                  @input="
                    patchImportedVectorStyle({
                      width: Number(($event.target as HTMLInputElement).value),
                    })
                  "
                />
                <strong>{{ importedVectorStyle.width ?? 2 }}</strong>
              </label>
              <label class="layer-style-row">
                <span>{{ LAYERS_COPY.vectorRadius }}</span>
                <input
                  type="range"
                  min="2"
                  max="16"
                  step="1"
                  :value="importedVectorStyle.radius ?? 5"
                  @input="
                    patchImportedVectorStyle({
                      radius: Number(($event.target as HTMLInputElement).value),
                    })
                  "
                />
                <strong>{{ importedVectorStyle.radius ?? 5 }}</strong>
              </label>
              <label class="layer-style-row">
                <span>{{ LAYERS_COPY.vectorFillOpacity }}</span>
                <input
                  type="range"
                  min="0"
                  max="100"
                  :value="Math.round((importedVectorStyle.fillOpacity ?? 0.35) * 100)"
                  @input="
                    patchImportedVectorStyle({
                      fillOpacity: Number(($event.target as HTMLInputElement).value) / 100,
                    })
                  "
                />
                <strong>{{ Math.round((importedVectorStyle.fillOpacity ?? 0.35) * 100) }}%</strong>
              </label>
            </div>

            <!-- 导入栅格：CRS + 只读色带提示 -->
            <dl
              v-if="displayLayer.isImportedRaster"
              class="meta-list"
              style="margin-bottom: 0.55rem"
            >
              <div>
                <dt>{{ ANALYSIS_COPY.metaCrs }}</dt>
                <dd>{{ displayLayer.importedRasterSourceCrs ?? '—' }}</dd>
              </div>
              <div v-if="displayLayer.importedFileName">
                <dt>{{ ANALYSIS_COPY.metaFile }}</dt>
                <dd>{{ displayLayer.importedFileName }}</dd>
              </div>
            </dl>

            <div
              v-if="displayLayer.instanceId && (isRealtimeWeatherLayer || canToggleParticleFlow)"
              class="weather-layer-controls"
            >
              <div v-if="canToggleParticleFlow" class="weather-layer-btn-row wind-mode-layout">
                <div class="wind-display-mode-seg" role="group" aria-label="风场显示模式">
                  <button
                    v-for="mode in ['particle', 'streamline', 'off'] as const"
                    :key="mode"
                    class="wind-mode-seg-btn"
                    :class="{
                      active: currentWindDisplayMode === mode,
                      off: mode === 'off' && currentWindDisplayMode === 'off',
                    }"
                    :data-mode="mode"
                    type="button"
                    :disabled="mode !== 'off' && particleFlowButtonDisabled"
                    :title="
                      mode !== 'off' && particleFlowButtonDisabled
                        ? '当前风场地图产物尚未就绪'
                        : windDisplayModeLabel(mode)
                    "
                    @click="handleSetWindDisplayMode(mode)"
                  >
                    {{ windDisplayModeLabel(mode) }}
                  </button>
                </div>
                <button
                  class="weather-layer-btn weather-visibility-btn"
                  type="button"
                  :title="displayLayer.visible ? '隐藏当前图层' : '显示当前图层'"
                  @click="handleToggleLayerVisibility"
                >
                  <span class="weather-layer-btn-text">{{
                    displayLayer.visible ? '隐藏图层' : '显示图层'
                  }}</span>
                </button>
              </div>
              <button
                v-else
                class="weather-layer-btn weather-visibility-btn"
                type="button"
                :title="displayLayer.visible ? '隐藏当前图层' : '显示当前图层'"
                @click="handleToggleLayerVisibility"
              >
                <span class="weather-layer-btn-text">{{
                  displayLayer.visible ? '隐藏图层' : '显示图层'
                }}</span>
              </button>
              <label v-if="isRealtimeWeatherLayer" class="weather-provider-row">
                <span class="weather-provider-label">天气数据源</span>
                <select
                  v-model="selectedWeatherProvider"
                  class="weather-provider-select"
                  :disabled="weatherProvidersLoading"
                  :title="
                    weatherProvidersError || '自动按优先级选择已启用源；钉选后瓦片与点查均走该源'
                  "
                >
                  <option value="auto">{{ INSPECT_COPY.providerAuto }}</option>
                  <option
                    v-for="opt in weatherProviderOptions"
                    :key="opt.provider_id"
                    :value="opt.provider_id"
                    :disabled="!opt.enabled"
                  >
                    {{ weatherProviderOptionLabel(opt) }}
                  </option>
                </select>
              </label>
              <p
                v-if="isRealtimeWeatherLayer && selectedWeatherProviderHint"
                class="weather-provider-error"
              >
                {{ selectedWeatherProviderHint }}
              </p>
              <p
                v-else-if="isRealtimeWeatherLayer && selectedWeatherProviderSparse"
                class="weather-provider-error"
              >
                点查可用；瓦片将回落 dense 源（Open-Meteo）
              </p>
              <p
                v-if="isRealtimeWeatherLayer && weatherProvidersError"
                class="weather-provider-error"
              >
                {{ weatherProvidersError }}
              </p>
              <div v-if="isRealtimeWeatherLayer" class="weather-layer-btn-row smooth-render-row">
                <span class="smooth-render-label">平滑渲染</span>
                <button
                  class="smooth-toggle-switch"
                  :class="{ active: layersStore.smoothRendering }"
                  type="button"
                  role="switch"
                  :aria-checked="layersStore.smoothRendering"
                  title="开：连续数值面（双线性插值）；关：网格色块"
                  @click="layersStore.setSmoothRendering(!layersStore.smoothRendering)"
                >
                  <span class="smooth-toggle-knob"></span>
                </button>
                <span class="smooth-render-hint">{{
                  layersStore.smoothRendering ? '连续数值面' : '网格色块'
                }}</span>
              </div>
            </div>

            <div v-if="styleRenderHint" class="weather-legend-row">
              <span class="weather-legend-label">图例</span>
              <span class="weather-legend-meta">
                {{ styleRenderHint.primary_metric }} · {{ styleRenderHint.unit_label }}
              </span>
            </div>
            <div
              v-if="styleRenderHint && weatherLegendGradient"
              class="weather-legend-gradient-wrap"
            >
              <div
                class="weather-legend-gradient"
                :style="{ background: weatherLegendGradient }"
              ></div>
              <div class="weather-legend-gradient-ticks">
                <span
                  v-for="stop in weatherLegendStops"
                  :key="`tick-${stop.value}`"
                  class="weather-legend-tick"
                  >{{ stop.label }}</span
                >
              </div>
              <p v-if="legendExplainer" class="weather-legend-explainer">{{ legendExplainer }}</p>
            </div>
            <div v-else-if="styleRenderHint" class="weather-legend-strip">
              <div
                v-for="stop in weatherLegendStops"
                :key="`${stop.value}`"
                class="weather-legend-stop"
              >
                <span class="weather-legend-swatch" :style="{ background: stop.color }"></span>
                <span>{{ stop.label }}</span>
              </div>
            </div>

            <div v-if="styleRangeMeta.hasRange" class="style-range-block">
              <div class="style-section-label">{{ LAYERS_COPY.sectionRange }}</div>
              <div class="style-range-grid">
                <div v-if="styleRangeMeta.unit" class="style-range-cell">
                  <span>{{ LAYERS_COPY.metricUnit }}</span>
                  <strong>{{ styleRangeMeta.unit }}</strong>
                </div>
                <div class="style-range-cell">
                  <span>min</span>
                  <input
                    v-if="canEditPalette"
                    v-model="rangeEditVmin"
                    class="style-range-input"
                    type="number"
                    step="any"
                    title="值域下限"
                  />
                  <strong v-else>{{ styleRangeMeta.vmin }}</strong>
                </div>
                <div class="style-range-cell">
                  <span>max</span>
                  <input
                    v-if="canEditPalette"
                    v-model="rangeEditVmax"
                    class="style-range-input"
                    type="number"
                    step="any"
                    title="值域上限"
                  />
                  <strong v-else>{{ styleRangeMeta.vmax }}</strong>
                </div>
              </div>
              <div v-if="canEditPalette" class="style-nodata-row">
                <span class="style-section-label">无效值 (NaN)</span>
                <select v-model="nodataModeValue" class="style-nodata-select" title="无效像元显示">
                  <option value="transparent">透明</option>
                  <option value="solid">固色填充</option>
                </select>
                <input
                  v-if="nodataModeValue === 'solid'"
                  v-model="nodataColorValue"
                  class="style-nodata-color"
                  type="color"
                  title="NaN 填充色"
                />
              </div>
            </div>

            <div
              v-if="styleRenderHint || canEditPalette"
              class="palette-selector"
              :class="{ 'is-readonly': !canEditPalette }"
            >
              <div
                v-if="paletteDropdownOpen && canEditPalette"
                class="palette-backdrop"
                @click="paletteDropdownOpen = false"
              ></div>
              <button
                class="palette-trigger"
                type="button"
                :disabled="!canEditPalette"
                :title="canEditPalette ? '切换地图配色' : '无源预渲染栅格，不支持前端改色'"
                @click="togglePaletteDropdown"
              >
                <span class="palette-trigger-label">配色方案</span>
                <span class="palette-trigger-preview">
                  <span
                    v-for="(c, i) in paletteOptions.find((p) => p.id === currentPaletteId)
                      ?.colors ?? []"
                    :key="i"
                    class="palette-trigger-dot"
                    :style="{ background: c }"
                  ></span>
                </span>
                <span class="palette-trigger-name">{{
                  paletteOptions.find((p) => p.id === currentPaletteId)?.label ?? '默认'
                }}</span>
                <span
                  v-if="canEditPalette"
                  class="palette-trigger-arrow"
                  :class="{ open: paletteDropdownOpen }"
                  >▾</span
                >
              </button>
              <div v-if="paletteDropdownOpen && canEditPalette" class="palette-dropdown">
                <button
                  v-for="opt in paletteOptions"
                  :key="opt.id"
                  class="palette-option"
                  :class="{ active: paletteIdsEqual(opt.id, currentPaletteId) }"
                  type="button"
                  @click="handleSelectPalette(opt.id)"
                >
                  <span
                    class="palette-option-gradient"
                    :style="{ background: `linear-gradient(90deg, ${opt.colors.join(', ')})` }"
                  ></span>
                  <span class="palette-option-label">{{ opt.label }}</span>
                  <span class="palette-option-type">{{
                    opt.type === 'diverging' ? '发散' : opt.type === 'qualitative' ? '定性' : '递进'
                  }}</span>
                </button>
                <button
                  v-if="displayLayer?.paletteOverride"
                  class="palette-option palette-reset"
                  type="button"
                  @click="handleSelectPalette(weatherRenderHint?.palette ?? '')"
                >
                  <span class="palette-option-label">恢复默认配色</span>
                </button>
              </div>
              <p v-if="!canEditPalette" class="palette-readonly-hint">
                无可读源的预渲染产物，配色只读
              </p>
            </div>

            <div class="weather-style-meta">
              <span v-if="isRealtimeWeatherLayer && tileStats">
                瓦片：已缓存 {{ tileStats.cached }} / 可视 {{ tileStats.visible }} / 加载中
                {{ tileStats.pending }}
              </span>
              <span v-else-if="isRealtimeWeatherLayer || jobLayer">
                {{ hasWeatherLayerAsset ? '地图产物已挂载' : '尚无地图产物' }}
              </span>
            </div>

            <ul v-if="styleRenderHint?.notes?.length" class="weather-note-list">
              <li v-for="note in styleRenderHint.notes" :key="note">{{ note }}</li>
            </ul>
          </section>

          <div
            v-show="activeTab === 'style'"
            v-if="!hasLayerStyleSection"
            class="analysis-sparse-card"
          >
            <p>{{ ANALYSIS_COPY.styleTabEmpty }}</p>
          </div>

          <section
            v-if="visibleHotspots.length > 0"
            v-show="activeTab === 'visual'"
            id="hotspot-section"
            class="analysis-section analysis-section--hotspots"
          >
            <div class="section-kicker">热点</div>
            <h3>点位列表</h3>
            <ul class="hotspot-list">
              <li
                v-for="hotspot in visibleHotspots"
                :id="`hotspot-${hotspot.id}`"
                :key="hotspot.id"
                :class="{ selected: selectedHotspot?.id === hotspot.id }"
                role="button"
                tabindex="0"
                @click="emit('selectHotspot', hotspot.id)"
                @keydown.enter.prevent="emit('selectHotspot', hotspot.id)"
              >
                <span>{{ hotspot.name }}</span>
                <strong>{{ hotspot.value }}</strong>
              </li>
            </ul>
          </section>

          <section
            v-if="resultModel"
            v-show="activeTab === 'visual'"
            id="result-section"
            class="analysis-section analysis-section--result"
          >
            <div class="section-kicker">结果</div>
            <div class="report-section-head">
              <div>
                <h3>{{ resultModel.title }}</h3>
                <p v-if="resultModel.subtitle">{{ resultModel.subtitle }}</p>
              </div>
              <a
                v-if="resultModel.canShowResultLink && resultModel.resultUrl"
                class="job-result-link"
                :href="resultModel.resultUrl"
                target="_blank"
                rel="noreferrer"
              >
                打开结果
              </a>
            </div>
            <dl class="meta-list" style="margin-top: 0.35rem">
              <div v-if="resultModel.statusText">
                <dt>状态</dt>
                <dd>{{ resultModel.statusText }}</dd>
              </div>
              <div v-if="resultModel.progressText">
                <dt>进度</dt>
                <dd>{{ resultModel.progressText }}</dd>
              </div>
              <div v-if="resultModel.category">
                <dt>类别</dt>
                <dd>{{ resultModel.category }}</dd>
              </div>
            </dl>
            <div v-if="resultModel.metricRows.length" class="job-metrics">
              <div v-for="m in resultModel.metricRows" :key="m.label" class="job-metric-item">
                <span class="jm-label">{{ m.label }}</span>
                <strong class="jm-value">{{ m.value }}</strong>
              </div>
            </div>
          </section>

          <div
            v-show="activeTab === 'visual'"
            v-if="!hasVisualTabContent"
            class="analysis-sparse-card analysis-sparse-card--visual"
          >
            <p class="analysis-sparse-title">{{ ANALYSIS_COPY.sparseVisualTitle }}</p>
            <p>{{ sparseVisualHint }}</p>
            <div v-if="isRealtimeWeatherLayer || canRunWorkflow" class="overview-quick-actions">
              <button
                v-if="isRealtimeWeatherLayer && uiStore.interactionMode !== 'select'"
                type="button"
                class="weather-mini-btn"
                @click="enterInspectTools"
              >
                {{ ANALYSIS_COPY.toolsQuickInspect }}
              </button>
              <button type="button" class="weather-mini-btn" @click="setActiveTab('style')">
                符号样式
              </button>
            </div>
          </div>

          <!-- meta：主指标与洞察（去冗后只在此 Tab） -->
          <section
            v-if="hasRealSelection && !showCompactHero"
            v-show="activeTab === 'meta'"
            class="hero-metric"
            :style="{ '--accent-color': displayLayer.accentColor }"
          >
            <span>{{ displayLayer.metricLabel }}</span>
            <strong>{{ displayLayer.metricValue }}</strong>
            <p>{{ displayLayer.trendLabel }}</p>
          </section>

          <div
            v-if="hasRealSelection && !showCompactHero"
            v-show="activeTab === 'meta'"
            class="insight-grid"
          >
            <article class="insight-card">
              <span>更新频率</span>
              <strong>{{ displayLayer.updateLabel }}</strong>
            </article>
            <article class="insight-card">
              <span>可用性</span>
              <strong>{{ displayLayer.availabilityLabel }}</strong>
            </article>
            <article class="insight-card">
              <span>可靠性</span>
              <strong>{{ displayLayer.confidenceLabel }}</strong>
            </article>
            <article class="insight-card">
              <span>观测时间</span>
              <strong>{{ displayLayer.observationTimeLabel }}</strong>
            </article>
          </div>

          <section
            v-if="layerMetadata.length && hasRealSelection"
            v-show="activeTab === 'meta'"
            class="info-card meta-card"
          >
            <div class="info-card-head">
              <span class="info-kicker">元数据</span>
              <span class="info-card-tag" :class="{ real: displayLayer.dataState === 'real' }">
                {{ displayLayer.dataState === 'real' ? '真实' : '目录' }}
              </span>
            </div>
            <dl class="meta-grid">
              <div v-for="row in layerMetadata" :key="row.label" class="meta-grid-row">
                <dt>{{ row.label }}</dt>
                <dd>{{ row.value }}</dd>
              </div>
            </dl>
          </section>

          <section
            v-if="displayLayer.trendLabel && hasRealSelection"
            v-show="activeTab === 'meta'"
            class="info-card trend-card"
            :style="{ '--accent-color': displayLayer.accentColor }"
          >
            <div class="info-card-head">
              <span class="info-kicker">历史对比</span>
              <span class="info-card-tag trend">{{ displayLayer.metricLabel }}</span>
            </div>
            <div class="trend-body">
              <div class="trend-current">
                <span class="trend-current-label">当前</span>
                <strong class="trend-current-value">{{ displayLayer.metricValue }}</strong>
              </div>
              <div class="trend-indicator">
                <span class="trend-arrow" :class="trendDirection">{{ trendArrowSymbol }}</span>
                <span class="trend-text">{{ displayLayer.trendLabel }}</span>
              </div>
            </div>
          </section>
        </div>
      </div>
    </template>
  </aside>
</template>

<style scoped>
.overview-quick-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem;
  margin-top: 0.45rem;
}

.tools-lead {
  margin: 0 0 0.45rem;
  font-size: 0.68rem;
  color: #94a3b8;
  line-height: 1.4;
}

.tools-empty-hint,
.tab-empty-hint {
  margin: 0.35rem 0 0;
  padding: 0.45rem 0.5rem;
  border-radius: 0.45rem;
  border: 1px dashed rgba(148, 163, 184, 0.25);
  background: rgba(15, 23, 42, 0.35);
  font-size: 0.68rem;
  color: #94a3b8;
  line-height: 1.4;
}

.analysis-idle {
  flex: 1 1 auto;
  min-height: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 0.55rem;
  padding: 1.6rem 1.25rem 1.8rem;
  text-align: center;
  position: relative;
  overflow: hidden;
}

.analysis-idle-orb {
  width: 4.5rem;
  height: 4.5rem;
  border-radius: 50%;
  margin-bottom: 0.35rem;
  background:
    radial-gradient(circle at 35% 30%, rgba(125, 211, 252, 0.35), transparent 55%),
    radial-gradient(circle at 70% 65%, rgba(56, 189, 248, 0.12), transparent 60%),
    rgba(15, 23, 42, 0.55);
  border: 1px solid rgba(148, 163, 184, 0.16);
  box-shadow: inset 0 0 24px rgba(56, 189, 248, 0.08);
}

.analysis-idle-kicker {
  margin: 0;
  font-size: 0.62rem;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: rgba(148, 163, 184, 0.85);
}

.analysis-idle-title {
  margin: 0;
  font-size: 1.05rem;
  font-weight: 600;
  letter-spacing: 0.02em;
  color: #e2e8f0;
}

.analysis-idle-lead {
  margin: 0;
  max-width: 16rem;
  font-size: 0.78rem;
  line-height: 1.5;
  color: rgba(148, 163, 184, 0.95);
}

.analysis-idle-steps {
  list-style: none;
  margin: 0.55rem 0 0;
  padding: 0;
  display: grid;
  gap: 0.35rem;
  width: min(100%, 15.5rem);
  text-align: left;
}

.analysis-idle-steps li {
  position: relative;
  padding: 0.38rem 0.55rem 0.38rem 1.55rem;
  border-radius: 0.5rem;
  background: rgba(148, 163, 184, 0.06);
  border: 1px solid rgba(148, 163, 184, 0.1);
  font-size: 0.72rem;
  line-height: 1.4;
  color: rgba(203, 213, 225, 0.88);
}

.analysis-idle-steps li::before {
  content: '';
  position: absolute;
  left: 0.55rem;
  top: 50%;
  width: 0.35rem;
  height: 0.35rem;
  border-radius: 50%;
  transform: translateY(-50%);
  background: rgba(125, 211, 252, 0.55);
}

.analysis-sparse-card {
  margin: 0.15rem 0 0;
  padding: 0.85rem 0.75rem;
  border-radius: 0.62rem;
  border: 1px solid rgba(148, 163, 184, 0.12);
  background: linear-gradient(165deg, rgba(15, 23, 42, 0.45), rgba(8, 15, 28, 0.28));
  color: #94a3b8;
  font-size: 0.72rem;
  line-height: 1.45;
}

.analysis-sparse-card p {
  margin: 0;
}

.analysis-sparse-title {
  margin: 0 0 0.28rem !important;
  font-size: 0.82rem !important;
  font-weight: 600;
  color: #cbd5e1 !important;
}

.analysis-sparse-card--visual .overview-quick-actions {
  margin-top: 0.65rem;
}

.panel {
  --info-card-radius: 0.82rem;
  --panel-radius: 0.88rem;
  --info-card-padding-y: 0.46rem;
  --info-card-padding-x: 0.5rem;
  --info-soft-gap: 0.34rem;
  display: flex;
  flex-direction: column;
  gap: 0;
  width: 100%;
  max-width: 100%;
  height: 100%;
  min-height: 0;
  padding: 0;
  border-radius: var(--panel-radius);
  border: 1px solid rgba(148, 163, 184, 0.15);
  background: linear-gradient(180deg, rgba(13, 21, 36, 0.72), rgba(8, 15, 28, 0.6));
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.03),
    0 12px 26px rgba(1, 8, 16, 0.14);
  overflow: hidden;
  contain: layout style;
}

.panel-sticky-chrome {
  flex: 0 0 auto;
  display: flex;
  flex-direction: column;
  align-items: stretch;
  gap: 0;
  padding: 0;
  border-bottom: 1px solid rgba(148, 163, 184, 0.12);
  background: rgba(8, 15, 28, 0.94);
  backdrop-filter: blur(8px);
  z-index: 5;
  border-top-left-radius: var(--panel-radius);
  border-top-right-radius: var(--panel-radius);
}

.panel-stage-row {
  display: flex;
  justify-content: flex-end;
  padding: 0.18rem 0.5rem 0.28rem;
}

.panel-scroll {
  flex: 1 1 auto;
  min-height: 0;
  overflow-x: hidden;
  overflow-y: auto;
  display: grid;
  gap: 0.48rem;
  padding: 0.42rem 0.42rem 0.5rem;
  align-content: start;
}
.panel,
.panel * {
  box-sizing: border-box;
}
.panel > *,
.panel
  :is(
    .panel-topline,
    .panel-header,
    .workflow-error,
    .workflow-stage-row,
    .meta-list,
    .meta-list > div,
    .analysis-stream,
    .analysis-section,
    .job-report-card,
    .job-report-header,
    .job-progress-shell,
    .job-progress-row,
    .job-steps,
    .job-metrics,
    .job-metric-item,
    .weather-section-head,
    .weather-primary-card,
    .weather-row-grid,
    .weather-row-card,
    .weather-hourly-strip,
    .weather-hourly-card,
    .weather-style-panel,
    .weather-style-head,
    .weather-layer-controls,
    .weather-legend-row,
    .weather-legend-strip,
    .weather-style-meta,
    .hero-metric,
    .insight-grid,
    .insight-card,
    .learning-note,
    .protocol-details,
    .info-card,
    .info-card-head,
    .meta-grid,
    .meta-grid-row,
    .trend-body,
    .trend-current,
    .trend-indicator,
    .overlay-list li,
    .overlay-info,
    .hotspot-list li,
    .report-section-head
  ) {
  min-width: 0;
}
.panel
  :is(
    p,
    span,
    strong,
    dd,
    dt,
    a,
    button,
    .job-message,
    .job-diagnostic-item,
    .trend-text,
    .overlay-name,
    .run-block-hint,
    .error-message,
    .job-report-copy,
    .weather-legend-stop,
    .weather-style-meta span,
    .wf-name,
    .wf-event-text
  ) {
  overflow-wrap: anywhere;
}
.panel :is(.workflow-meta-row, .wf-progress-bar, .wf-event-msg) {
  min-width: 0;
}
.panel-topline {
  display: grid;
  gap: 0.38rem;
  padding: 0.12rem 0.06rem 0.02rem;
  min-width: 0;
}
.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 0.44rem;
  flex-wrap: wrap;
  min-width: 0;
}
.panel-subtitle {
  margin: 0;
  font-size: 0.72rem;
  line-height: 1.35;
  color: rgba(148, 163, 184, 0.95);
}
.panel-subtitle--solo {
  flex: 1 1 8rem;
  min-width: 0;
  font-size: 0.8rem;
  font-weight: 600;
  color: rgba(226, 232, 240, 0.92);
}
.readiness {
  padding: 0.16rem 0.36rem;
  border-radius: 999px;
  background: rgba(90, 162, 255, 0.16);
  color: #cfeaff;
  font-size: 0.58rem;
  flex: 0 1 auto;
  min-width: 0;
  max-width: 100%;
  align-self: flex-start;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.analysis-empty-guide,
.analysis-context-card {
  display: grid;
  gap: 0.35rem;
  padding: 0.42rem 0.1rem 0.1rem;
}

.analysis-empty-lead,
.analysis-context-line {
  margin: 0;
  font-size: 0.78rem;
  line-height: 1.45;
  color: rgba(203, 213, 225, 0.92);
}

.analysis-empty-hints {
  margin: 0;
  padding-left: 1.05rem;
  display: grid;
  gap: 0.2rem;
  font-size: 0.72rem;
  line-height: 1.4;
  color: rgba(148, 163, 184, 0.95);
}
.action-row {
  display: flex;
  justify-content: flex-start;
}
.workflow-error {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  padding: 0.34rem 0.48rem;
  border-radius: 0.62rem;
  background: rgba(255, 80, 80, 0.12);
  border: 1px solid rgba(255, 80, 80, 0.22);
  color: #ff9999;
  font-size: 0.58rem;
}
.error-icon {
  font-size: 0.72rem;
}
.run-block-hint {
  color: #ffd38a;
  font-size: 0.56rem;
  line-height: 1.4;
}
.workflow-stage-row {
  display: flex;
  align-items: center;
  gap: 0.4rem;
}
.stage-pill {
  padding: 0.18rem 0.44rem;
  border-radius: 999px;
  font-size: 0.56rem;
  background: rgba(148, 163, 184, 0.12);
  color: #bfd3e6;
}
.stage-pill.running,
.stage-pill.queued {
  background: rgba(90, 213, 255, 0.14);
  color: #bcefff;
}
.stage-pill.succeeded {
  background: rgba(114, 255, 207, 0.12);
  color: #9ff8cf;
}
.stage-pill.failed {
  background: rgba(255, 80, 80, 0.12);
  color: #ff9999;
}
.stage-pill.submitting {
  background: rgba(255, 196, 120, 0.12);
  color: #ffd38a;
}
.stage-copy {
  color: #7f93a9;
  font-size: 0.58rem;
}
.workflow-meta-row {
  display: flex;
  align-items: center;
  gap: 0.34rem;
  padding: 0.18rem 0.06rem;
  font-size: 0.58rem;
  color: #b6c9da;
  flex-wrap: wrap;
}
.wf-engine-icon {
  font-size: 0.72rem;
  line-height: 1;
}
.wf-engine-label {
  padding: 0.1rem 0.36rem;
  border-radius: 999px;
  background: rgba(90, 162, 255, 0.14);
  color: #d8f3ff;
  font-size: 0.55rem;
}
.wf-name {
  color: #9eb3c8;
  font-size: 0.56rem;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 100%;
}
.wf-progress-bar {
  position: relative;
  height: 4px;
  border-radius: 999px;
  background: rgba(148, 163, 184, 0.14);
  overflow: hidden;
}
.wf-progress-fill {
  position: absolute;
  inset: 0 auto 0 0;
  border-radius: 999px;
  transition: width 0.45s ease;
  background: rgba(148, 163, 184, 0.4);
}
.wf-progress-fill.running,
.wf-progress-fill.queued {
  background: linear-gradient(90deg, rgba(90, 213, 255, 0.55), rgba(90, 213, 255, 0.95));
}
.wf-progress-fill.succeeded {
  background: linear-gradient(90deg, rgba(114, 255, 207, 0.55), rgba(114, 255, 207, 0.95));
}
.wf-progress-fill.failed {
  background: linear-gradient(90deg, rgba(255, 80, 80, 0.55), rgba(255, 80, 80, 0.95));
}
.wf-progress-fill.submitting {
  background: linear-gradient(90deg, rgba(255, 196, 120, 0.55), rgba(255, 196, 120, 0.95));
}
.wf-event-msg {
  display: flex;
  align-items: flex-start;
  gap: 0.32rem;
  padding: 0.18rem 0.06rem;
  font-size: 0.55rem;
  color: #8aa0b6;
  line-height: 1.4;
}
.wf-event-dot {
  flex: 0 0 auto;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  margin-top: 0.22rem;
  background: rgba(148, 163, 184, 0.5);
}
.wf-event-dot.running,
.wf-event-dot.queued {
  background: #5ad5ff;
  box-shadow: 0 0 6px rgba(90, 213, 255, 0.6);
}
.wf-event-dot.succeeded {
  background: #72ffcf;
}
.wf-event-dot.failed {
  background: #ff5050;
}
.wf-event-dot.submitting {
  background: #ffc478;
}
.wf-event-text {
  flex: 1 1 auto;
  min-width: 0;
  overflow-wrap: anywhere;
}
.meta-list {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0.28rem 0.56rem;
}
.meta-list dt {
  color: #7f93a9;
  font-size: 0.56rem;
}
.meta-list dd {
  margin: 0.06rem 0 0;
  color: #eaf3fb;
  font-size: 0.66rem;
}
.analysis-stream {
  display: grid;
  gap: var(--info-soft-gap);
  overflow-x: hidden;
  overflow-y: visible;
  scrollbar-width: thin;
  scrollbar-color: rgba(136, 192, 255, 0.22) rgba(255, 255, 255, 0.05);
}
.analysis-stream::-webkit-scrollbar {
  width: 4px;
}
.analysis-stream::-webkit-scrollbar-thumb {
  background: rgba(136, 192, 255, 0.22);
  border-radius: 999px;
}
.analysis-stream::-webkit-scrollbar-track {
  background: rgba(255, 255, 255, 0.05);
}
.analysis-section,
.job-report-card {
  background: rgba(8, 18, 33, 0.56);
  border: 1px solid rgba(136, 192, 255, 0.1);
  border-radius: var(--info-card-radius);
  padding: var(--info-card-padding-y) var(--info-card-padding-x);
}
.analysis-section--overview {
  background: linear-gradient(180deg, rgba(12, 25, 43, 0.82), rgba(8, 18, 33, 0.62));
  border-color: rgba(103, 212, 255, 0.16);
}
.analysis-section--layer {
  border-color: rgba(136, 192, 255, 0.14);
}
.analysis-section--weather {
  border-color: rgba(103, 212, 255, 0.18);
  background: linear-gradient(180deg, rgba(8, 23, 42, 0.78), rgba(8, 18, 33, 0.62));
}
.analysis-section--hotspots {
  border-color: rgba(114, 255, 207, 0.14);
}
.analysis-section--report {
  border-color: rgba(126, 168, 255, 0.18);
  background: linear-gradient(180deg, rgba(10, 22, 39, 0.72), rgba(8, 18, 33, 0.56));
}
.analysis-section--result {
  border-color: rgba(126, 168, 255, 0.16);
}
.report-section-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 0.5rem;
}
.job-report-copy {
  margin-top: 0.32rem !important;
  color: #d7e6f5 !important;
}
.report-block {
  margin-top: 0.75rem;
  padding-top: 0.55rem;
  border-top: 1px solid rgba(120, 160, 190, 0.18);
}
.report-block h4 {
  margin: 0 0 0.35rem;
  font-size: 0.72rem;
  color: #cfe3f2;
}
.report-node-list {
  margin: 0;
  padding-left: 1.1rem;
  display: grid;
  gap: 0.28rem;
  color: #9eb6c8;
  font-size: 0.68rem;
}
.report-node-msg {
  display: block;
  color: #7f9bb0;
}
.analysis-section h3 {
  margin: 0.1rem 0 0.18rem;
  font-size: 0.68rem;
  color: #f0f7ff;
}
.analysis-section p {
  margin: 0;
  color: #9eb3c8;
  font-size: 0.58rem;
  line-height: 1.45;
}
.section-kicker {
  color: #7f93a9;
  font-size: 0.52rem;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}
.analysis-chip-row {
  display: flex;
  gap: 0.28rem;
  flex-wrap: wrap;
  margin-bottom: 0.2rem;
}
.analysis-chip {
  padding: 0.14rem 0.36rem;
  border-radius: 999px;
  background: rgba(90, 162, 255, 0.14);
  color: #dff1ff;
  font-size: 0.55rem;
}
.analysis-chip.muted {
  background: rgba(148, 163, 184, 0.12);
  color: #b6c9da;
}
.weather-section-head {
  display: flex;
  justify-content: space-between;
  gap: 0.5rem;
  align-items: flex-start;
}
.weather-primary-card {
  display: grid;
  gap: 0.14rem;
  margin-top: 0.34rem;
  padding: 0.4rem 0.44rem;
  border-radius: 0.7rem;
  background: rgba(90, 162, 255, 0.1);
  border: 1px solid rgba(90, 162, 255, 0.16);
}
.weather-primary-card span {
  color: #9bc8e9;
  font-size: 0.54rem;
}
.weather-primary-card strong {
  color: #f4fbff;
  font-size: 0.86rem;
}
.weather-primary-card p {
  color: #c8dff0;
}
.weather-row-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0.26rem;
  margin-top: 0.34rem;
}
.weather-row-card {
  display: grid;
  gap: 0.08rem;
  padding: 0.3rem 0.34rem;
  border-radius: 0.56rem;
  background: rgba(148, 163, 184, 0.08);
  border: 1px solid rgba(148, 163, 184, 0.08);
}
.weather-row-card span {
  color: #7f93a9;
  font-size: 0.54rem;
}
.weather-row-card strong {
  color: #edf6ff;
  font-size: 0.6rem;
}
.weather-hourly-strip {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 0.24rem;
  margin-top: 0.34rem;
}
.weather-hourly-card {
  display: grid;
  gap: 0.08rem;
  padding: 0.28rem 0.24rem;
  border-radius: 0.56rem;
  background: rgba(8, 18, 33, 0.56);
  border: 1px solid rgba(136, 192, 255, 0.1);
  text-align: center;
}
.weather-hourly-card.active {
  border-color: rgba(255, 184, 77, 0.55);
  background: rgba(255, 184, 77, 0.12);
}
.weather-mini-btn {
  border: 1px solid rgba(136, 192, 255, 0.22);
  border-radius: 0.42rem;
  background: rgba(10, 132, 255, 0.12);
  color: #cfeaff;
  font: inherit;
  font-size: 0.55rem;
  padding: 0.22rem 0.45rem;
  cursor: pointer;
}
.weather-mini-btn:hover {
  border-color: rgba(90, 213, 255, 0.45);
}
.weather-mini-meta {
  color: #8aa0b5;
  font-size: 0.52rem;
}
.hotspot-list li {
  cursor: pointer;
}
.hotspot-list li:focus-visible {
  outline: 1px solid rgba(90, 213, 255, 0.55);
}
.weather-hourly-card span {
  color: #7f93a9;
  font-size: 0.52rem;
}
.weather-hourly-card strong {
  color: #eaf3fb;
  font-size: 0.58rem;
}
.weather-state {
  margin-top: 0.34rem;
  padding: 0.34rem 0.42rem;
  border-radius: 0.62rem;
  font-size: 0.58rem;
}
.weather-state-loading {
  background: rgba(90, 162, 255, 0.1);
  color: #cfeaff;
  border: 1px solid rgba(90, 162, 255, 0.14);
}
.weather-state-error {
  background: rgba(255, 80, 80, 0.1);
  color: #ffb3b3;
  border: 1px solid rgba(255, 80, 80, 0.16);
}
.weather-style-panel {
  display: grid;
  gap: 0.28rem;
  margin-top: 0.36rem;
  padding-top: 0.34rem;
  border-top: 1px solid rgba(136, 192, 255, 0.08);
}
.weather-style-head {
  display: flex;
  justify-content: space-between;
  gap: 0.4rem;
  align-items: center;
  color: #eaf3fb;
  font-size: 0.58rem;
}
.weather-layer-controls {
  display: grid;
  gap: 0.24rem;
}
.weather-layer-btn-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0.28rem;
  align-items: stretch;
}
.weather-layer-btn-row.wind-mode-layout {
  grid-template-columns: minmax(0, 1.7fr) minmax(0, 0.9fr);
}
.wind-display-mode-seg {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 0;
  min-height: 1.78rem;
  border: 1px solid rgba(103, 212, 255, 0.28);
  border-radius: 999px;
  overflow: hidden;
  background: rgba(15, 23, 42, 0.5);
}
.wind-mode-seg-btn {
  border: none;
  border-right: 1px solid rgba(103, 212, 255, 0.16);
  background: transparent;
  color: #9eb3c8;
  font: inherit;
  font-size: 0.52rem;
  font-weight: 500;
  letter-spacing: 0.01em;
  padding: 0.28rem 0.18rem;
  cursor: pointer;
  min-width: 0;
  white-space: nowrap;
  transition:
    background 0.16s ease,
    color 0.16s ease,
    box-shadow 0.16s ease;
}
.wind-mode-seg-btn:last-child {
  border-right: none;
}
.wind-mode-seg-btn:hover:not(:disabled):not(.active) {
  background: rgba(29, 78, 216, 0.14);
  color: #e8f3ff;
}
.wind-mode-seg-btn:disabled {
  opacity: 0.48;
  cursor: not-allowed;
  color: #8da1b7;
}
.wind-mode-seg-btn.active {
  background: linear-gradient(135deg, rgba(56, 189, 248, 0.38), rgba(99, 102, 241, 0.3));
  color: #f0f9ff;
  box-shadow: inset 0 0 8px rgba(110, 200, 255, 0.18);
}
.wind-mode-seg-btn.active[data-mode='off'],
.wind-mode-seg-btn.active.off {
  background: rgba(148, 163, 184, 0.38);
  color: #f1f5f9;
  box-shadow: inset 0 0 10px rgba(148, 163, 184, 0.22);
}
.weather-layer-btn {
  box-sizing: border-box;
  width: 100%;
  min-height: 1.78rem;
  border: 1px solid rgba(103, 212, 255, 0.22);
  border-radius: 999px;
  background: rgba(29, 78, 216, 0.14);
  color: #d8f3ff;
  font: inherit;
  font-size: 0.56rem;
  font-weight: 500;
  letter-spacing: 0.01em;
  line-height: 1.15;
  padding: 0.34rem 0.42rem;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 0.22rem;
  min-width: 0;
  white-space: nowrap;
  transition:
    border-color 0.18s ease,
    background 0.18s ease,
    color 0.18s ease,
    box-shadow 0.18s ease;
}
.weather-layer-btn-text {
  overflow: hidden;
  text-overflow: ellipsis;
}
.weather-visibility-btn:hover {
  border-color: rgba(103, 212, 255, 0.42);
  background: rgba(29, 78, 216, 0.22);
  color: #eaf8ff;
}
.weather-provider-row {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 0.36rem;
  align-items: center;
  color: #9eb3c8;
  font-size: 0.56rem;
}
.weather-provider-label {
  color: #dbeeff;
  white-space: nowrap;
}
.weather-provider-select {
  min-width: 0;
  border: 1px solid rgba(103, 212, 255, 0.22);
  border-radius: 0.48rem;
  background: rgba(8, 18, 33, 0.72);
  color: #eaf3fb;
  font-size: 0.56rem;
  padding: 0.26rem 0.4rem;
}
.weather-provider-error {
  margin: 0;
  color: #ffb3b3;
  font-size: 0.52rem;
}
.smooth-render-row {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  margin-top: 0.3rem;
}
.smooth-render-label {
  color: #dbeeff;
  font-size: 0.56rem;
  white-space: nowrap;
}
.smooth-render-hint {
  color: #7f93a9;
  font-size: 0.5rem;
}
.smooth-toggle-switch {
  position: relative;
  width: 2rem;
  height: 1.1rem;
  border: 1px solid rgba(103, 212, 255, 0.28);
  border-radius: 999px;
  background: rgba(8, 18, 33, 0.72);
  cursor: pointer;
  transition:
    background 0.2s ease,
    border-color 0.2s ease;
  flex: none;
}
.smooth-toggle-switch.active {
  background: rgba(10, 132, 255, 0.32);
  border-color: rgba(90, 213, 255, 0.55);
}
.smooth-toggle-knob {
  position: absolute;
  top: 0.14rem;
  left: 0.14rem;
  width: 0.72rem;
  height: 0.72rem;
  border-radius: 50%;
  background: #8aa8bf;
  transition:
    transform 0.18s ease,
    background 0.18s ease;
}
.smooth-toggle-switch.active .smooth-toggle-knob {
  transform: translateX(0.9rem);
  background: #5ad5ff;
  box-shadow: 0 0 6px rgba(90, 213, 255, 0.5);
}
.weather-opacity-row {
  display: grid;
  grid-template-columns: auto 1fr auto;
  gap: 0.3rem;
  align-items: center;
  color: #9eb3c8;
  font-size: 0.56rem;
}
.weather-opacity-slider {
  width: 100%;
}
.layer-opacity-row {
  display: grid;
  grid-template-columns: auto 1fr auto;
  gap: 0.3rem;
  align-items: center;
  margin-top: 0.34rem;
  color: #9eb3c8;
  font-size: 0.56rem;
}
.layer-style-row {
  display: grid;
  grid-template-columns: auto 1fr auto;
  gap: 0.35rem;
  align-items: center;
  margin-top: 0.4rem;
  color: #9eb3c8;
  font-size: 0.56rem;
}
.layer-style-row input[type='color'] {
  width: 2rem;
  height: 1.35rem;
  border: none;
  background: transparent;
  cursor: pointer;
  justify-self: start;
}
.layer-style-row input[type='range'] {
  width: 100%;
  accent-color: var(--accent-color, #38bdf8);
}
.style-section-label {
  margin-top: 0.35rem;
  font-size: 0.62rem;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: #94a3b8;
}
.style-field-row {
  display: flex;
  align-items: center;
  gap: 0.45rem;
  font-size: 0.72rem;
  margin-top: 0.25rem;
}
.style-field-label {
  color: #94a3b8;
  min-width: 2.4rem;
}
.style-field-row strong {
  font-weight: 550;
  color: #e2e8f0;
}
.style-range-block {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
  margin: 0.35rem 0 0.15rem;
}
.style-range-grid {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr;
  gap: 0.35rem;
}
.style-range-cell {
  display: flex;
  flex-direction: column;
  gap: 0.1rem;
  padding: 0.3rem 0.4rem;
  border-radius: 0.4rem;
  background: rgba(148, 163, 184, 0.08);
}
.style-range-cell span {
  color: #94a3b8;
  font-size: 0.62rem;
}
.style-range-cell strong {
  font-weight: 550;
  color: #e2e8f0;
  font-size: 0.72rem;
  font-variant-numeric: tabular-nums;
}
.style-range-input {
  width: 100%;
  border: 1px solid rgba(148, 163, 184, 0.25);
  border-radius: 0.3rem;
  background: rgba(15, 23, 42, 0.55);
  color: #e2e8f0;
  font-size: 0.72rem;
  padding: 0.15rem 0.3rem;
  font-variant-numeric: tabular-nums;
}
.style-nodata-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.4rem;
  margin-top: 0.25rem;
}
.style-nodata-select {
  border: 1px solid rgba(148, 163, 184, 0.25);
  border-radius: 0.3rem;
  background: rgba(15, 23, 42, 0.55);
  color: #e2e8f0;
  font-size: 0.72rem;
  padding: 0.2rem 0.35rem;
}
.style-nodata-color {
  width: 1.6rem;
  height: 1.4rem;
  padding: 0;
  border: none;
  background: transparent;
  cursor: pointer;
}
.imported-vector-style {
  margin-bottom: 0.55rem;
}
.layer-opacity-slider {
  width: 100%;
  -webkit-appearance: none;
  appearance: none;
  height: 1.4rem;
  background: transparent;
  outline: none;
  cursor: pointer;
}
.layer-opacity-slider::-webkit-slider-runnable-track {
  height: 5px;
  border-radius: 999px;
  background: rgba(136, 192, 255, 0.18);
}
.layer-opacity-slider::-moz-range-track {
  height: 5px;
  border-radius: 999px;
  background: rgba(136, 192, 255, 0.18);
}
.layer-opacity-slider::-webkit-slider-thumb {
  -webkit-appearance: none;
  appearance: none;
  width: 0.9rem;
  height: 0.9rem;
  margin-top: -0.4rem;
  border-radius: 50%;
  background: var(--accent-color, #5ad5ff);
  box-shadow: 0 0 6px var(--accent-color, #5ad5ff);
  cursor: pointer;
  transition: transform 0.14s ease;
}
.layer-opacity-slider::-webkit-slider-thumb:hover {
  transform: scale(1.15);
}
.layer-opacity-slider::-moz-range-thumb {
  width: 0.9rem;
  height: 0.9rem;
  border: none;
  border-radius: 50%;
  background: var(--accent-color, #5ad5ff);
  box-shadow: 0 0 6px var(--accent-color, #5ad5ff);
  cursor: pointer;
}
.weather-legend-row {
  display: flex;
  justify-content: space-between;
  gap: 0.4rem;
  color: #9eb3c8;
  font-size: 0.54rem;
}
.weather-legend-label {
  color: #dbeeff;
}
.weather-legend-meta {
  color: #7f93a9;
}
.weather-legend-gradient-wrap {
  display: flex;
  flex-direction: column;
  gap: 0.28rem;
}
.weather-legend-gradient {
  height: 0.72rem;
  border-radius: 0.28rem;
  border: 1px solid rgba(255, 255, 255, 0.1);
  box-shadow: inset 0 0 0 1px rgba(0, 0, 0, 0.12);
}
.weather-legend-gradient-ticks {
  display: flex;
  justify-content: space-between;
  gap: 0.2rem;
  color: #c8dff0;
  font-size: 0.5rem;
}
.weather-legend-explainer {
  margin: 0;
  color: #7f93a9;
  font-size: 0.5rem;
  line-height: 1.4;
}
.weather-legend-tick {
  flex: 1;
  text-align: center;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.weather-legend-tick:first-child {
  text-align: left;
}
.weather-legend-tick:last-child {
  text-align: right;
}
.weather-legend-strip {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0.18rem 0.3rem;
}
.weather-legend-stop {
  display: flex;
  align-items: center;
  gap: 0.24rem;
  color: #c8dff0;
  font-size: 0.54rem;
}
.weather-legend-swatch {
  width: 0.72rem;
  height: 0.72rem;
  border-radius: 0.22rem;
  border: 1px solid rgba(255, 255, 255, 0.08);
  flex-shrink: 0;
}

/* 配色方案选择器 */
.palette-selector {
  position: relative;
  margin-top: 0.2rem;
}
.palette-selector.is-readonly .palette-trigger {
  opacity: 0.72;
  cursor: not-allowed;
}
.palette-readonly-hint {
  margin: 0.28rem 0 0;
  color: #7f93a9;
  font-size: 0.5rem;
  line-height: 1.35;
}
.palette-backdrop {
  position: fixed;
  inset: 0;
  z-index: 19;
  background: transparent;
  cursor: default;
}
.palette-reset {
  color: #5ad5ff;
  font-style: italic;
}
.palette-trigger {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  width: 100%;
  padding: 0.32rem 0.46rem;
  border: 1px solid rgba(136, 192, 255, 0.18);
  border-radius: 0.46rem;
  background: rgba(8, 18, 33, 0.72);
  color: #d8e6f5;
  font: inherit;
  font-size: 0.58rem;
  cursor: pointer;
  text-align: left;
}
.palette-trigger:hover:not(:disabled) {
  border-color: rgba(90, 213, 255, 0.3);
}
.palette-trigger:disabled {
  opacity: 0.72;
  cursor: not-allowed;
}
.palette-trigger-label {
  color: #7f93a9;
  flex-shrink: 0;
}
.palette-trigger-preview {
  display: flex;
  gap: 1px;
  flex-shrink: 0;
}
.palette-trigger-dot {
  width: 0.5rem;
  height: 0.72rem;
  display: inline-block;
}
.palette-trigger-name {
  flex: 1;
  text-align: left;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.palette-trigger-arrow {
  font-size: 0.6rem;
  color: #7f93a9;
  transition: transform 0.2s ease;
}
.palette-trigger-arrow.open {
  transform: rotate(180deg);
}
.palette-dropdown {
  position: absolute;
  top: 100%;
  left: 0;
  right: 0;
  z-index: 20;
  margin-top: 0.2rem;
  padding: 0.24rem;
  border: 1px solid rgba(136, 192, 255, 0.16);
  border-radius: 0.5rem;
  background: rgba(6, 14, 26, 0.96);
  backdrop-filter: blur(12px);
  box-shadow: 0 12px 32px rgba(0, 0, 0, 0.4);
  max-height: 240px;
  overflow-y: auto;
  display: grid;
  gap: 0.16rem;
}
.palette-option {
  display: flex;
  align-items: center;
  gap: 0.3rem;
  padding: 0.22rem 0.3rem;
  border: 1px solid transparent;
  border-radius: 0.36rem;
  background: transparent;
  color: #a8c4d8;
  font: inherit;
  font-size: 0.52rem;
  cursor: pointer;
  text-align: left;
  transition:
    background 0.14s ease,
    border-color 0.14s ease;
}
.palette-option:hover {
  background: rgba(136, 192, 255, 0.08);
}
.palette-option.active {
  border-color: rgba(90, 213, 255, 0.3);
  background: rgba(10, 132, 255, 0.1);
  color: #f0faff;
}
.palette-option-gradient {
  width: 2.4rem;
  height: 0.6rem;
  border-radius: 0.16rem;
  flex-shrink: 0;
  border: 1px solid rgba(255, 255, 255, 0.06);
}
.palette-option-label {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.palette-option-type {
  color: #5a7080;
  font-size: 0.46rem;
  flex-shrink: 0;
}

.weather-style-meta {
  display: flex;
  justify-content: space-between;
  gap: 0.4rem;
  color: #7f93a9;
  font-size: 0.52rem;
  flex-wrap: wrap;
}
.weather-note-list {
  display: grid;
  gap: 0.16rem;
  margin: 0;
  padding-left: 1rem;
  color: #9eb3c8;
  font-size: 0.54rem;
}
.job-report-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 0.4rem;
}
.job-report-title {
  color: #eaf3fb;
  font-size: 0.66rem;
  font-weight: 700;
}
.job-status-chip {
  padding: 0.12rem 0.34rem;
  border-radius: 999px;
  font-size: 0.54rem;
  background: rgba(148, 163, 184, 0.12);
  color: #bfd3e6;
}
.job-report-card--summary {
  background: linear-gradient(180deg, rgba(10, 22, 39, 0.72), rgba(8, 18, 33, 0.56));
}
.job-progress-shell {
  display: grid;
  gap: 0.24rem;
}
.job-progress-row {
  display: flex;
  align-items: center;
  gap: 0.4rem;
}
.job-progress-bar {
  flex: 1;
  height: 0.26rem;
  border-radius: 999px;
  background: rgba(148, 163, 184, 0.14);
  overflow: hidden;
}
.job-progress-fill {
  height: 100%;
  background: linear-gradient(90deg, #5ad5ff, #7ea8ff);
}
.job-progress-label {
  font-size: 12px;
  opacity: 0.85;
  min-width: 36px;
  text-align: right;
}

.job-node-progress-section {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-top: 8px;
}

.job-node-progress-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.job-node-progress-header {
  display: flex;
  justify-content: space-between;
  font-size: 12px;
}

.job-node-progress-bar {
  height: 4px;
  border-radius: 2px;
  background: rgba(255, 255, 255, 0.12);
  overflow: hidden;
}

.job-node-progress-fill {
  height: 100%;
  background: #5b9fd4;
}

.job-node-progress-message,
.job-node-progress-detail {
  margin: 0;
  font-size: 11px;
  opacity: 0.75;
}
.job-message {
  margin: 0;
  color: #c8dff0;
  font-size: 0.58rem;
  line-height: 1.4;
}
.job-diagnostic-list {
  display: grid;
  gap: 0.12rem;
  margin: 0;
  padding-left: 1rem;
  color: #ffcf99;
  font-size: 0.54rem;
}
.job-diagnostic-item {
  line-height: 1.35;
}
.job-steps {
  display: flex;
  flex-direction: column;
  gap: 0.18rem;
}
.job-step {
  padding: 0.18rem 0.34rem;
  border-radius: 0.52rem;
  background: rgba(148, 163, 184, 0.08);
  color: #7f93a9;
  font-size: 0.56rem;
}
.job-step.active {
  background: rgba(90, 213, 255, 0.12);
  color: #bcefff;
}
.job-metrics {
  display: grid;
  gap: 0.28rem;
  grid-template-columns: repeat(2, minmax(0, 1fr));
}
.job-metric-item {
  display: grid;
  gap: 0.06rem;
  padding: 0.28rem 0.34rem;
  border-radius: 0.56rem;
  background: rgba(148, 163, 184, 0.08);
}
.jm-label {
  color: #7f93a9;
  font-size: 0.54rem;
}
.jm-value {
  color: #edf6ff;
  font-size: 0.62rem;
  margin: 0;
}
.hero-metric,
.insight-card,
.learning-note,
.protocol-details {
  border-radius: var(--info-card-radius);
  background: rgba(8, 18, 33, 0.56);
  border: 1px solid rgba(136, 192, 255, 0.1);
  padding: 0.5rem 0.56rem;
}
.hero-metric span,
.insight-card span {
  color: #7f93a9;
  font-size: 0.56rem;
}
.hero-metric strong {
  display: block;
  font-size: 0.96rem;
  color: #f4fbff;
}
.hero-metric p {
  margin: 0.16rem 0 0;
  color: #8ea3b8;
  font-size: 0.56rem;
}
.insight-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0.34rem;
}
.insight-card strong {
  display: block;
  color: #edf6ff;
  font-size: 0.64rem;
  margin-top: 0.12rem;
}
.protocol-details summary {
  cursor: pointer;
  color: #cfeaff;
  font-size: 0.58rem;
}
.protocol-details p {
  margin: 0.18rem 0 0;
  color: #9eb3c8;
  font-size: 0.56rem;
}
.hotspot-list {
  display: grid;
  gap: 0.18rem;
  padding: 0;
  margin: 0;
  list-style: none;
}
.hotspot-list li {
  display: flex;
  justify-content: space-between;
  gap: 0.4rem;
  color: #eaf3fb;
  font-size: 0.58rem;
  padding: 0.22rem 0.32rem;
  border-radius: 0.52rem;
  background: rgba(148, 163, 184, 0.05);
  border: 1px solid rgba(148, 163, 184, 0.08);
}
.hotspot-list li.selected {
  background: rgba(90, 213, 255, 0.16);
  border-color: rgba(90, 213, 255, 0.28);
  box-shadow: 0 0 0 1px rgba(90, 213, 255, 0.08) inset;
  transform: translateX(2px);
}
.hotspot-list li.selected span,
.hotspot-list li.selected strong {
  color: #f4fbff;
}
.job-result-link {
  color: #5ad5ff;
  font-size: 0.58rem;
  text-decoration: none;
}

/* ── 增强信息展示：元数据 / 历史对比 / 叠加分析 ─────────────────────────── */
.info-card {
  display: grid;
  gap: 0.32rem;
  padding: var(--info-card-padding-y) var(--info-card-padding-x);
  border-radius: var(--info-card-radius);
  background: rgba(8, 18, 33, 0.56);
  border: 1px solid rgba(136, 192, 255, 0.1);
}
.info-card-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 0.4rem;
}
.info-kicker {
  color: #7f93a9;
  font-size: 0.52rem;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}
.info-card-tag {
  padding: 0.12rem 0.34rem;
  border-radius: 999px;
  background: rgba(148, 163, 184, 0.12);
  color: #bfd3e6;
  font-size: 0.52rem;
}
.info-card-tag.real {
  background: rgba(114, 255, 207, 0.12);
  color: #9ff8cf;
}
.info-card-tag.trend {
  background: rgba(126, 168, 255, 0.14);
  color: #c8d8ff;
}

/* 元数据网格 */
.meta-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0.22rem 0.5rem;
  margin: 0;
}
.meta-grid-row {
  display: grid;
  gap: 0.04rem;
}
.meta-grid dt {
  color: #7f93a9;
  font-size: 0.52rem;
}
.meta-grid dd {
  margin: 0;
  color: #eaf3fb;
  font-size: 0.6rem;
  word-break: break-word;
}

/* 历史趋势卡片 */
.trend-card {
  border-color: rgba(126, 168, 255, 0.18);
  background: linear-gradient(180deg, rgba(10, 20, 38, 0.72), rgba(8, 18, 33, 0.56));
}
.trend-body {
  display: flex;
  align-items: center;
  gap: 0.56rem;
}
.trend-current {
  display: grid;
  gap: 0.04rem;
  min-width: 4.4rem;
}
.trend-current-label {
  color: #7f93a9;
  font-size: 0.52rem;
}
.trend-current-value {
  color: var(--accent-color, #f4fbff);
  font-size: 0.86rem;
}
.trend-indicator {
  display: flex;
  align-items: center;
  gap: 0.3rem;
  flex: 1;
  padding: 0.2rem 0.34rem;
  border-radius: 0.56rem;
  background: rgba(148, 163, 184, 0.06);
}
.trend-arrow {
  font-size: 0.78rem;
  line-height: 1;
}
.trend-arrow.up {
  color: #ff8aa7;
}
.trend-arrow.down {
  color: #5ad5ff;
}
.trend-arrow.flat {
  color: #9eb3c8;
}
.trend-text {
  color: #c8dff0;
  font-size: 0.56rem;
  line-height: 1.35;
}

/* 叠加图层列表 */
.overlay-list {
  display: grid;
  gap: 0.18rem;
  padding: 0;
  margin: 0;
  list-style: none;
}
.overlay-list li {
  display: flex;
  align-items: center;
  gap: 0.34rem;
  padding: 0.24rem 0.3rem;
  border-radius: 0.56rem;
  background: rgba(148, 163, 184, 0.05);
  border: 1px solid rgba(148, 163, 184, 0.08);
}
.overlay-dot {
  width: 0.5rem;
  height: 0.5rem;
  border-radius: 999px;
  background: var(--layer-accent, #88d8ff);
  box-shadow: 0 0 6px var(--layer-accent, rgba(136, 216, 255, 0.6));
  flex-shrink: 0;
}
.overlay-info {
  display: grid;
  gap: 0.04rem;
  flex: 1;
  min-width: 0;
}
.overlay-name {
  color: #eaf3fb;
  font-size: 0.6rem;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.overlay-category {
  color: #7f93a9;
  font-size: 0.52rem;
  display: flex;
  align-items: center;
  gap: 0.2rem;
  flex-wrap: wrap;
}
.overlay-palette-tag {
  padding: 0.04rem 0.22rem;
  border-radius: 0.28rem;
  background: rgba(126, 168, 255, 0.14);
  color: #c8d8ff;
  font-size: 0.46rem;
}
.overlay-range {
  color: #9eb3c8;
  font-size: 0.5rem;
}
.overlay-time-tag {
  color: #ffd38a;
  font-size: 0.5rem;
  font-variant-numeric: tabular-nums;
}
.overlay-value-col {
  display: grid;
  gap: 0.08rem;
  align-items: end;
  justify-items: end;
  flex-shrink: 0;
}
.overlay-state {
  padding: 0.1rem 0.3rem;
  border-radius: 999px;
  font-size: 0.5rem;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}
.overlay-state.state-ready {
  background: rgba(114, 255, 207, 0.12);
  color: #9ff8cf;
}
.overlay-state.state-partial {
  background: rgba(255, 196, 120, 0.12);
  color: #ffd38a;
}
.overlay-state.state-empty {
  background: rgba(148, 163, 184, 0.12);
  color: #b6c9da;
}
.overlay-point-value {
  color: #eaf3fb;
  font-size: 0.54rem;
  font-variant-numeric: tabular-nums;
  padding: 0.06rem 0.24rem;
  border-radius: 0.32rem;
  background: rgba(90, 162, 255, 0.12);
}
.overlay-point-value.na {
  color: #7f93a9;
  background: rgba(148, 163, 184, 0.08);
}

.imported-meta {
  margin-top: 0.35rem;
}
.imported-meta .mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 0.52rem;
  word-break: break-all;
}
.imported-export-row {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem;
  margin-top: 0.55rem;
}
.imported-export-btn {
  border: 1px solid rgba(126, 224, 168, 0.28);
  border-radius: 0.42rem;
  background: rgba(126, 224, 168, 0.1);
  color: #b8f0d0;
  font: inherit;
  font-size: 0.56rem;
  padding: 0.28rem 0.5rem;
  cursor: pointer;
}
.imported-export-btn:hover {
  background: rgba(126, 224, 168, 0.18);
}

.imported-action-hint {
  margin: 0.4rem 0 0;
  color: #9ff0c4;
  font-size: 0.52rem;
}

.imported-action-hint.error {
  color: #ff9e9e;
}

.dashboard-nav-tabs {
  display: flex;
  width: 100%;
  min-width: 0;
  background: transparent;
  border: none;
  border-radius: 0;
  padding: 0;
  gap: 0;
  margin: 0;
  border-bottom: 1px solid rgba(148, 163, 184, 0.1);
}

.dash-tab {
  flex: 1 1 0;
  min-width: 0;
  background: transparent;
  border: none;
  border-right: 1px solid rgba(148, 163, 184, 0.1);
  color: rgba(226, 232, 240, 0.72);
  font-size: 0.72rem;
  font-weight: 500;
  padding: 0.42rem 0.2rem;
  border-radius: 0;
  cursor: pointer;
  transition:
    color 0.15s ease,
    background 0.15s ease;
  text-align: center;
  white-space: nowrap;
  line-height: 1.25;
}

.dash-tab:last-child {
  border-right: none;
}

.dash-tab:first-child {
  border-top-left-radius: var(--panel-radius);
}

.dash-tab:last-child {
  border-top-right-radius: var(--panel-radius);
}

.dash-tab:hover {
  color: #ffffff;
  background: rgba(255, 255, 255, 0.05);
}

.dash-tab.active {
  color: #7dd3fc;
  background: rgba(56, 189, 248, 0.14);
  font-weight: 600;
  box-shadow: inset 0 -2px 0 #38bdf8;
}

.readiness--inline {
  flex: 0 1 auto;
  max-width: 100%;
  align-self: flex-end;
  padding: 0.12rem 0.32rem;
  font-size: 0.58rem;
}

@media (max-width: 560px) {
  .meta-list,
  .weather-row-grid,
  .job-metrics,
  .meta-grid,
  .insight-grid,
  .weather-hourly-strip {
    grid-template-columns: minmax(0, 1fr);
  }

  .weather-section-head,
  .job-report-header,
  .report-section-head,
  .info-card-head,
  .trend-body {
    grid-template-columns: minmax(0, 1fr);
    display: grid;
  }
}
</style>
