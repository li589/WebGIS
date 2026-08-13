/**
 * 统一图层图表数据 composable。
 *
 * 将天气点查数据（WeatherPointResponse.hourly）与栅格 overlay 时序数据
 * （OverlayPointValue[]）归一化为统一的图表数据模型，支持：
 * - 多图层点值对比（柱状图）
 * - 多图层时间序列对比（折线图）
 * - 按数据类型分类显示（天气 / 栅格）
 * - 组合显示（全部图层在同一图表）
 */
import { computed, type ComputedRef } from 'vue'
import type { WeatherPointResponse, OverlayPointValue } from '../../services/runtime-api'
import type { OverlayTimeState } from '../map/overlay-image-module'
import { useLayerWorkspace } from '../../stores/layers/selectors'
import { formatOverlayValue } from './useWeatherPointData'
import type { MultiLayerSeries } from './MultiLayerTimeSeriesChart.vue'
import type { OverlayBarItem } from './MultiOverlayBarChart.vue'

// ── 统一数据模型 ──────────────────────────────────────────────────────────────

export type LayerDataCategory = 'weather' | 'raster' | 'vector'

export interface UnifiedLayerInfo {
  layerId: string
  name: string
  category: LayerDataCategory
  unit: string
  accentColor?: string
  /** 是否为时序数据（有时间维度） */
  hasTimeSeries: boolean
}

export interface UnifiedPointValue {
  layerId: string
  name: string
  category: LayerDataCategory
  value: number | null
  valueText: string
  unit: string
  accentColor?: string
}

// ── 辅助函数 ──────────────────────────────────────────────────────────────────

function formatHourLabel(time: string): string {
  const date = new Date(time)
  if (Number.isNaN(date.getTime())) return time
  return `${String(date.getHours()).padStart(2, '0')}:00`
}

function formatOverlayTimeLabel(time: string): string {
  // 8 天块格式: 20240101_20240108 → 01-01 → 01-08
  if (/^\d{8}_\d{8}$/.test(time)) {
    const [start, end] = time.split('_')
    const fmt = (d: string) => `${d.slice(4, 6)}-${d.slice(6, 8)}`
    return `${fmt(start)} → ${fmt(end)}`
  }
  // ISO 日期: 取 MM-DD
  if (/^\d{4}-\d{2}-\d{2}/.test(time)) {
    return time.slice(5, 10)
  }
  return time
}

// ── Composable ────────────────────────────────────────────────────────────────

export function useUnifiedChartData(
  pointWeather: ComputedRef<WeatherPointResponse | null>,
  overlayPointValues: ComputedRef<OverlayPointValue[]>,
  allOverlayTimeSeries: ComputedRef<Record<string, OverlayPointValue[]>>,
  overlayTimeStates: ComputedRef<OverlayTimeState[]>,
  selectedMapPoint: ComputedRef<{ lng: number; lat: number } | null>,
) {
  const workspace = useLayerWorkspace()

  // ── 图层信息列表 ──────────────────────────────────────────────────────────

  /** 天气图层信息（来自 pointWeather） */
  const weatherLayerInfo = computed<UnifiedLayerInfo | null>(() => {
    const weather = pointWeather.value
    if (!weather) return null
    const unit = weather.render_hint?.unit_label ?? ''
    const activeLayer = workspace.activeLayersDisplay.value.find(
      (l) => l.catalogId === weather.layer_id,
    )
    return {
      layerId: weather.layer_id,
      name: activeLayer?.name ?? weather.layer_id,
      category: 'weather' as const,
      unit: unit === 'C' ? '°C' : unit,
      accentColor: activeLayer?.accentColor,
      hasTimeSeries: !!(weather.hourly && weather.hourly.length > 0),
    }
  })

  /** 栅格 overlay 图层信息列表 */
  const rasterLayerInfos = computed<UnifiedLayerInfo[]>(() => {
    const stateMap = new Map((overlayTimeStates.value ?? []).map((s) => [s.layerId, s]))
    const valueMap = new Map((overlayPointValues.value ?? []).map((v) => [v.layer_id, v]))

    return workspace.activeLayersDisplay.value
      .filter((l) => l.visible && Boolean(l.importedRasterOverlayLayerId))
      .map((l) => {
        const overlayId = l.importedRasterOverlayLayerId ?? l.catalogId
        const state = stateMap.get(overlayId)
        const value = valueMap.get(overlayId)
        return {
          layerId: overlayId,
          name: l.name || l.catalogId,
          category: 'raster' as const,
          unit: value?.unit || state?.unit || '',
          accentColor: l.accentColor,
          hasTimeSeries: state?.category === 'time-series' && (state.timeList?.length ?? 0) > 0,
        }
      })
  })

  /** 所有可用图层信息（天气 + 栅格） */
  const allLayerInfos = computed<UnifiedLayerInfo[]>(() => {
    const list: UnifiedLayerInfo[] = []
    if (weatherLayerInfo.value) list.push(weatherLayerInfo.value)
    list.push(...rasterLayerInfos.value)
    return list
  })

  // ── 统一点值（用于柱状图对比） ──────────────────────────────────────────────

  const unifiedPointValues = computed<UnifiedPointValue[]>(() => {
    if (!selectedMapPoint.value) return []
    const list: UnifiedPointValue[] = []

    // 天气图层当前值
    if (weatherLayerInfo.value && pointWeather.value) {
      const weather = pointWeather.value
      const metric = weather.render_hint?.primary_metric ?? 'temperature_2m'
      const unit = weather.render_hint?.unit_label ?? ''
      const normalizedUnit = unit === 'C' ? '°C' : unit

      // 从 current 或 hourly[0] 提取当前值
      let currentValue: number | null = null
      if (weather.current) {
        const record = weather.current as Record<string, unknown>
        const v = record[metric]
        currentValue = typeof v === 'number' && Number.isFinite(v) ? v : null
      }
      if (currentValue === null && weather.hourly && weather.hourly.length > 0) {
        currentValue =
          typeof weather.hourly[0].primary_value === 'number'
            ? weather.hourly[0].primary_value
            : null
      }

      list.push({
        layerId: weatherLayerInfo.value.layerId,
        name: weatherLayerInfo.value.name,
        category: 'weather',
        value: currentValue,
        valueText:
          currentValue !== null ? `${currentValue.toFixed(1)} ${normalizedUnit}`.trim() : 'N/A',
        unit: normalizedUnit,
        accentColor: weatherLayerInfo.value.accentColor,
      })
    }

    // 栅格 overlay 图层当前值
    const valueMap = new Map((overlayPointValues.value ?? []).map((v) => [v.layer_id, v]))
    for (const info of rasterLayerInfos.value) {
      const pt = valueMap.get(info.layerId)
      const val = pt?.value ?? null
      list.push({
        layerId: info.layerId,
        name: info.name,
        category: 'raster',
        value: val,
        valueText: pt && pt.value !== null ? formatOverlayValue(pt) : 'N/A',
        unit: info.unit,
        accentColor: info.accentColor,
      })
    }

    return list
  })

  /** 柱状图条目（兼容现有 MultiOverlayBarChart 组件格式） */
  const unifiedBarItems = computed<OverlayBarItem[]>(() => {
    return unifiedPointValues.value.map((v) => ({
      layerId: v.layerId,
      name: v.name,
      category: v.category,
      valueText: v.valueText,
      numericValue: v.value,
      unit: v.unit,
      accentColor: v.accentColor,
    }))
  })

  // ── 统一时间序列（用于多图层折线图） ──────────────────────────────────────

  /** 天气图层时序数据（归一化） */
  const weatherTimeSeries = computed<MultiLayerSeries | null>(() => {
    const weather = pointWeather.value
    if (!weather?.hourly?.length) return null
    const info = weatherLayerInfo.value
    if (!info) return null
    const metric = weather.render_hint?.primary_metric ?? 'temperature_2m'

    const data = weather.hourly
      .map((entry) => {
        const value =
          typeof entry.primary_value === 'number'
            ? entry.primary_value
            : (() => {
                const record = entry as Record<string, unknown>
                const v = record[metric]
                return typeof v === 'number' && Number.isFinite(v) ? v : null
              })()
        return {
          time: formatHourLabel(entry.time),
          value,
        }
      })
      .filter((p) => p.value !== null)

    if (data.length === 0) return null

    return {
      id: info.layerId,
      name: info.name,
      color: info.accentColor,
      unit: info.unit,
      data,
    }
  })

  /** 栅格 overlay 图层时序数据列表（归一化） */
  const rasterTimeSeries = computed<MultiLayerSeries[]>(() => {
    const seriesMap = allOverlayTimeSeries.value ?? {}
    const result: MultiLayerSeries[] = []

    for (const info of rasterLayerInfos.value) {
      if (!info.hasTimeSeries) continue
      const rawSeries = seriesMap[info.layerId]
      if (!rawSeries || rawSeries.length === 0) continue

      const data = rawSeries
        .filter((item) => item.time)
        .map((item) => ({
          time: formatOverlayTimeLabel(item.time!),
          value: typeof item.value === 'number' && Number.isFinite(item.value) ? item.value : null,
        }))

      if (data.length === 0) continue

      result.push({
        id: info.layerId,
        name: info.name,
        color: info.accentColor,
        unit: info.unit,
        data,
      })
    }

    return result
  })

  /** 所有图层时序数据（组合） */
  const allTimeSeries = computed<MultiLayerSeries[]>(() => {
    const list: MultiLayerSeries[] = []
    if (weatherTimeSeries.value) list.push(weatherTimeSeries.value)
    list.push(...rasterTimeSeries.value)
    return list
  })

  // ── 按分类分组 ──────────────────────────────────────────────────────────────

  /** 按数据类型分组的时序数据 */
  const timeSeriesByCategory = computed<Record<LayerDataCategory, MultiLayerSeries[]>>(() => ({
    weather: weatherTimeSeries.value ? [weatherTimeSeries.value] : [],
    raster: rasterTimeSeries.value,
    vector: [],
  }))

  /** 按数据类型分组的点值 */
  const pointValuesByCategory = computed<Record<LayerDataCategory, UnifiedPointValue[]>>(() => {
    const groups: Record<LayerDataCategory, UnifiedPointValue[]> = {
      weather: [],
      raster: [],
      vector: [],
    }
    for (const v of unifiedPointValues.value) {
      groups[v.category].push(v)
    }
    return groups
  })

  // ── 可见性判断 ──────────────────────────────────────────────────────────────

  /** 是否有统一数据可展示（选点后且有任意图层数据） */
  const hasUnifiedData = computed(
    () =>
      !!selectedMapPoint.value &&
      (unifiedPointValues.value.length > 0 || allTimeSeries.value.length > 0),
  )

  /** 是否有多图层时序可对比 */
  const hasMultiLayerTimeSeries = computed(() => allTimeSeries.value.length > 0)

  /** 是否有点值可对比 */
  const hasPointComparison = computed(() => unifiedPointValues.value.length > 0)

  return {
    // 图层信息
    weatherLayerInfo,
    rasterLayerInfos,
    allLayerInfos,
    // 点值
    unifiedPointValues,
    unifiedBarItems,
    pointValuesByCategory,
    // 时序
    weatherTimeSeries,
    rasterTimeSeries,
    allTimeSeries,
    timeSeriesByCategory,
    // 可见性
    hasUnifiedData,
    hasMultiLayerTimeSeries,
    hasPointComparison,
  }
}
