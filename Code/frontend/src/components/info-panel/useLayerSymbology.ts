/**
 * 图层符号化 / 调色板 / 值域 / 风场控件。
 *
 * 从 InfoPanel.vue 抽取（原 script 210-456 行）。负责：
 * - 解析天气 renderHint / overlay 符号化元数据（styleSymbology / overlayStyleMeta）
 * - 调色板选择与下拉、值域编辑、nodata 显示
 * - 风场三态控件（粒子流 / 流量场 / 网格）
 * - 图例 stops / gradient / explainer
 */
import { computed, ref, watch } from 'vue'
import type { ComputedRef } from 'vue'

import type { ActiveLayerDisplay } from '../../stores/layers/types'
import type { WeatherPointResponse } from '../../services/runtime-api'
import { useLayerWorkspace, useLayerViewport } from '../../stores/layers/selectors'
import { useWeatherTileManager } from '../../stores/weather-tile-manager'
import { useOverlaySymbologyStore } from '../../stores/overlay-symbology'
import {
  WEATHER_PALETTE_OPTIONS,
  buildWeatherLegendGradient,
  buildWeatherLegendStops,
  hasRenderableSymbology,
  isMapLinkedPalette,
  paletteIdsEqual,
  resolveCanonicalPaletteIdStrict,
} from '../map/layer-symbology'
import {
  resolveEffectiveLayerSymbology,
  buildLegendExplainer,
} from '../map/effective-layer-symbology'
import { windDisplayModeLabel, type WindDisplayMode } from '../map/wind-display-mode'
import type { OverlayTimeState } from '../map/overlay-image-module'

/** 单位标签归一化：后端不同来源可能用 degC / C 等，统一为展示符号 */
const UNIT_NORMALIZE_MAP: Record<string, string> = {
  degC: '°C',
  degF: '°F',
  C: '°C',
  F: '°F',
  'm/s2': 'm/s²',
}

function normalizeUnit(raw: string | null | undefined): string {
  if (!raw) return ''
  const trimmed = raw.trim()
  return UNIT_NORMALIZE_MAP[trimmed] ?? trimmed
}

export function useLayerSymbology(
  displayLayer: ComputedRef<ActiveLayerDisplay>,
  isRealtimeWeatherLayer: ComputedRef<boolean>,
  overlayTimeStates: ComputedRef<OverlayTimeState[]>,
  pointWeather: ComputedRef<WeatherPointResponse | null>,
) {
  const workspace = useLayerWorkspace()
  const viewport = useLayerViewport()
  const weatherTileManager = useWeatherTileManager()
  const overlaySymbologyStore = useOverlaySymbologyStore()

  /** jobLayer 派生（与 InfoPanel 原定义一致） */
  const jobLayer = computed(() => displayLayer.value?.jobLayer)

  const weatherRenderHint = computed(
    () =>
      displayLayer.value?.renderHint ??
      jobLayer.value?.mapLayerPayload?.renderHint ??
      pointWeather.value?.render_hint ??
      null,
  )

  /** 侧栏同源 overlay meta + 可选 overlayTimeStates 兜底 */
  const overlayStyleMeta = computed(() => {
    void overlaySymbologyStore.version
    const overlayId =
      displayLayer.value.importedRasterOverlayLayerId ?? displayLayer.value.catalogId
    const fromStore = overlaySymbologyStore.getMeta(overlayId)
    if (fromStore?.palette) return fromStore
    const states = overlayTimeStates.value ?? []
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
      vminOverride: displayLayer.value.vminOverride,
      vmaxOverride: displayLayer.value.vmaxOverride,
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
    const unit = normalizeUnit(hint?.unit_label || meta?.unit || '')
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
    // 严格版：后端专属科学色带（brg/plasma/terrain 等）不兜底成 thermal-orange，
    // 选择器如实不高亮（2026-08-24 三联报障 C）
    resolveCanonicalPaletteIdStrict(
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
      workspace.setLayerRangeOverride(displayLayer.value.instanceId, {
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
      workspace.setLayerRangeOverride(displayLayer.value.instanceId, {
        vmax: n != null && Number.isFinite(n) ? n : null,
      })
    },
  })

  /** 科学量（SM/ω 等）允许任意小数；勿用整数步进，否则像只能调整数 */
  const rangeInputStep = computed(() => 'any')

  const nodataModeValue = computed({
    get: () => displayLayer.value.nodataMode ?? 'transparent',
    set: (mode: 'transparent' | 'solid') => {
      if (!displayLayer.value?.instanceId || !canEditPalette.value) return
      workspace.setLayerNodataDisplay(displayLayer.value.instanceId, {
        mode,
        color: mode === 'solid' ? displayLayer.value.nodataColor || '#808080' : null,
      })
    },
  })

  const nodataColorValue = computed({
    get: () => displayLayer.value.nodataColor || '#808080',
    set: (color: string) => {
      if (!displayLayer.value?.instanceId || !canEditPalette.value) return
      workspace.setLayerNodataDisplay(displayLayer.value.instanceId, {
        mode: 'solid',
        color,
      })
    },
  })

  function handleSelectPalette(paletteId: string) {
    if (!canEditPalette.value) return
    // 严格版默认判定：层注册色带（如 brg/viridis）不在前端可选集时不与
    // 任何选项相等——用户显式选择一律写入覆盖（2026-08-24 三联报障 C：
    // 旧兜底映射曾把"选热力橙红"误判为"恢复默认"存 null 吞掉）
    const defaultId = resolveCanonicalPaletteIdStrict(
      displayLayer.value?.defaultPalette ?? overlayStyleMeta.value?.palette ?? '',
    )
    const target = paletteIdsEqual(paletteId, defaultId) ? null : paletteId
    if (displayLayer.value?.instanceId) {
      workspace.setLayerPaletteOverride(displayLayer.value.instanceId, target)
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

  const canToggleParticleFlow = computed(() =>
    workspace.supportsParticleFlow(displayLayer.value.catalogId),
  )
  /** 该层是否持有风场三态控件归属（含「网格」色底态） */
  const ownsWindDisplay = computed(
    () => viewport.particleFlowCatalogId.value === displayLayer.value.catalogId,
  )
  const currentWindDisplayMode = computed<WindDisplayMode>(() => {
    if (!ownsWindDisplay.value) return 'off'
    return viewport.windDisplayMode.value
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
    viewport.setWindDisplayMode(displayLayer.value.catalogId, mode)
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

  /** 图例区域的归一化单位标签 */
  const normalizedUnitLabel = computed(() => normalizeUnit(styleRenderHint.value?.unit_label))

  return {
    weatherRenderHint,
    overlayStyleMeta,
    styleSymbology,
    styleRenderHint,
    normalizedUnitLabel,
    styleFieldLabel,
    styleRangeMeta,
    weatherLegendStops,
    weatherLegendGradient,
    currentPaletteId,
    paletteOptions,
    paletteDropdownOpen,
    canEditPalette,
    rangeEditVmin,
    rangeEditVmax,
    rangeInputStep,
    nodataModeValue,
    nodataColorValue,
    handleSelectPalette,
    togglePaletteDropdown,
    tileStats,
    hasWeatherLayerAsset,
    canToggleParticleFlow,
    ownsWindDisplay,
    currentWindDisplayMode,
    legendExplainer,
    handleSetWindDisplayMode,
    particleFlowButtonDisabled,
    windStyleChipLabel,
    hasLayerStyleSection,
    hasAdvancedStyleControls,
  }
}
