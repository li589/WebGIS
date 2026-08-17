/**
 * 天气点查数据格式化与辅助逻辑。
 *
 * 从 InfoPanel.vue 抽取（原 script 590-876 行 + 1012-1033 行辅助函数）。负责：
 * - 点查主指标解析（pointWeatherMetric / primaryLabel / primaryValue / numericValue）
 * - 点查元数据行与小时表行格式化
 * - 点查状态标签与区块可见性
 * - 通用格式化辅助函数（formatMetric / formatOverlayValue / formatTime / formatHour）
 */
import { computed } from 'vue'
import type { ComputedRef } from 'vue'

import type { ActiveLayerDisplay, WeatherLayerRenderHint } from '../../stores/layers/types'
import type { WeatherPointResponse, OverlayPointValue } from '../../services/runtime-api'
import { useLayerWorkspace } from '../../stores/layers/selectors'
import { useUiStore } from '../../stores/ui'
import { INSPECT_COPY } from '../../ui-copy'

// ── 通用格式化辅助函数（独立导出，供其它模块复用） ────────────────────────────

export function formatMetric(value: number | null | undefined, unit: string) {
  if (typeof value !== 'number' || Number.isNaN(value)) return `-- ${unit}`.trim()
  return `${value.toFixed(1)} ${unit}`.trim()
}

export function formatOverlayValue(v: OverlayPointValue): string {
  if (v.value === null || v.value === undefined) return 'N/A'
  const digits = Math.abs(v.value) >= 100 ? 1 : 3
  return `${v.value.toFixed(digits)} ${v.unit}`.trim()
}

export function formatTime(value: string) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString()
}

export function formatHour(value: string) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return `${String(date.getHours()).padStart(2, '0')}:00`
}

// ── 天气指标中文标签 ──────────────────────────────────────────────────────────

export const WEATHER_METRIC_LABELS: Record<string, string> = {
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

// ── 内部辅助 ──────────────────────────────────────────────────────────────────

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

// ── Composable ────────────────────────────────────────────────────────────────

export function useWeatherPointData(
  displayLayer: ComputedRef<ActiveLayerDisplay>,
  isRealtimeWeatherLayer: ComputedRef<boolean>,
  weatherRenderHint: ComputedRef<WeatherLayerRenderHint | null>,
  pointWeather: ComputedRef<WeatherPointResponse | null>,
  pointWeatherLoading: ComputedRef<boolean>,
  pointWeatherError: ComputedRef<string | null>,
  selectedMapPoint: ComputedRef<{ lng: number; lat: number } | null>,
  inspectHour: ComputedRef<number>,
) {
  const workspace = useLayerWorkspace()
  const uiStore = useUiStore()

  const pointWeatherMetric = computed(() => {
    const metricKey =
      pointWeather.value?.render_hint?.primary_metric ??
      weatherRenderHint.value?.primary_metric ??
      workspace.getLayerPrimaryMetric(displayLayer.value.catalogId) ??
      'temperature_2m'
    const unit =
      pointWeather.value?.render_hint?.unit_label ?? weatherRenderHint.value?.unit_label ?? ''
    return {
      key: metricKey,
      label: WEATHER_METRIC_LABELS[metricKey] ?? '实时指标',
      unit: normalizeWeatherUnit(unit),
    }
  })

  const pointWeatherPrimaryLabel = computed(() => pointWeatherMetric.value.label)

  const pointWeatherPrimaryValue = computed(() => {
    const weather = pointWeather.value
    if (!weather) return '--'
    const hourIdx = Math.max(0, Math.floor(inspectHour.value ?? 0))
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
    const weather = pointWeather.value
    if (!weather) return null
    const hourIdx = Math.max(0, Math.floor(inspectHour.value ?? 0))
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
    const weather = pointWeather.value
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
    const weather = pointWeather.value
    if (!weather) return []
    const activeHour = Math.max(0, Math.floor(inspectHour.value ?? 0))
    return (weather.hourly ?? [])
      .map((entry, index) => {
        const metricValue =
          typeof entry.primary_value === 'number'
            ? entry.primary_value
            : readWeatherMetricValue(entry, pointWeatherMetric.value.key)
        const metric = formatMetric(metricValue, pointWeatherMetric.value.unit)
        return {
          time: formatHour(entry.time),
          metric,
          numericValue: metricValue,
          active: index === activeHour,
        }
      })
      .filter((entry) => entry.metric !== `-- ${pointWeatherMetric.value.unit}`.trim())
  })

  const pointWeatherHourlyChartRows = computed(() => {
    return pointWeatherHourlyRows.value.map((row) => ({
      time: row.time,
      metric: row.metric,
      numericValue: row.numericValue,
      active: row.active,
    }))
  })

  /** 天气点查区块：有查询态或已选点时展示；否则走稀疏空态卡 */
  const hasPointWeatherSection = computed(
    () =>
      isRealtimeWeatherLayer.value &&
      (pointWeatherLoading.value ||
        !!pointWeatherError.value ||
        !!pointWeather.value ||
        !!selectedMapPoint.value),
  )

  const pointInspectStatusLabel = computed(() => {
    if (pointWeatherLoading.value) return INSPECT_COPY.statusQuerying
    if (pointWeatherError.value) return INSPECT_COPY.statusFailed
    if (pointWeather.value) return pointWeather.value.cache_status || INSPECT_COPY.statusReady
    if (uiStore.interactionMode === 'select') return INSPECT_COPY.statusWaitingClick
    return INSPECT_COPY.statusNeedSelectMode
  })

  return {
    pointWeatherMetric,
    pointWeatherPrimaryLabel,
    pointWeatherPrimaryValue,
    pointWeatherNumericValue,
    pointWeatherRows,
    pointWeatherHourlyRows,
    pointWeatherHourlyChartRows,
    pointInspectStatusLabel,
    hasPointWeatherSection,
  }
}
