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

/** 时间轴类型：hourly（小时）| block（8天块）| date（日期）| unknown */
export type TimeAxisType = 'hourly' | 'block' | 'date' | 'unknown'

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

/** 量纲分组：将单位归一化为可比较的量纲 key */
export function normalizeUnitKey(unit: string): string {
  const u = unit.trim().toLowerCase()
  if (!u) return '无单位'
  // 亮温类（K 用于卫星亮温，优先匹配）
  if (u === 'k' || u === '亮温' || u === 'brightness' || u === 'brightness_temperature')
    return '亮温'
  // 温度类
  if (u === '°c' || u === 'c' || u === '摄氏度') return '温度'
  // 风速类
  if (u === 'm/s' || u === 'ms' || u === 'km/h' || u === 'kph') return '风速'
  // 降水类
  if (u === 'mm' || u === 'mm/h' || u === '降水量' || u === 'precipitation') return '降水'
  // 湿度类
  if (u === '%' || u === 'rh' || u === '湿度') return '湿度'
  // 气压类
  if (u === 'hpa' || u === 'pa' || u === 'mb' || u === '气压') return '气压'
  // 能见度类
  if (u === 'm' || u === 'km' || u === '能见度') return '能见度'
  // NDVI / 植被指数
  if (u === 'ndvi' || u === 'index' || u === '指数') return '植被指数'
  return u
}

/** 检测时间标签的时间轴类型 */
export function detectTimeAxisType(timeLabels: string[]): TimeAxisType {
  if (timeLabels.length === 0) return 'unknown'
  const sample = timeLabels[0]
  // hourly: "08:00" 格式
  if (/^\d{2}:\d{2}$/.test(sample)) return 'hourly'
  // block: "01-01 → 01-08" 格式
  if (/^\d{2}-\d{2}\s*→\s*\d{2}-\d{2}$/.test(sample)) return 'block'
  // date: "01-01" 格式
  if (/^\d{2}-\d{2}$/.test(sample)) return 'date'
  // ISO date: "2024-01-01" 格式
  if (/^\d{4}-\d{2}-\d{2}/.test(sample)) return 'date'
  return 'unknown'
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

    const infos: UnifiedLayerInfo[] = []
    const seen = new Set<string>()

    // 渠道一：导入栅格 / 工作流物化层（显式挂 overlayLayerId）
    // 渠道二：目录 overlay / 运行时注册层——以 catalogId 为 overlay layer id 上图，
    // 经 overlayTimeStates 或点查结果注册后同样可取值，须纳入点值对比
    for (const l of workspace.activeLayersDisplay.value) {
      if (!l.visible) continue
      const overlayId = l.importedRasterOverlayLayerId ?? l.catalogId
      if (!overlayId || seen.has(overlayId)) continue
      const state = stateMap.get(overlayId)
      const value = valueMap.get(overlayId)
      if (!l.importedRasterOverlayLayerId && !state && !value) continue
      seen.add(overlayId)
      infos.push({
        layerId: overlayId,
        name: l.name || l.catalogId,
        category: 'raster' as const,
        unit: value?.unit || state?.unit || '',
        accentColor: l.accentColor,
        hasTimeSeries: state?.category === 'time-series' && (state.timeList?.length ?? 0) > 0,
      })
    }

    return infos
  })

  /** 矢量图层信息列表（导入矢量 / 行政边界等非栅格非天气图层） */
  const vectorLayerInfos = computed<UnifiedLayerInfo[]>(() => {
    return workspace.activeLayersDisplay.value
      .filter(
        (l) =>
          l.visible &&
          !l.importedRasterOverlayLayerId &&
          (l.isImported || l.isAdminBoundary) &&
          !l.renderHint,
      )
      .map((l) => ({
        layerId: l.catalogId,
        name: l.name || l.catalogId,
        category: 'vector' as const,
        unit: l.metricLabel || '',
        accentColor: l.accentColor,
        hasTimeSeries: false,
      }))
  })

  /** 所有可用图层信息（天气 + 栅格 + 矢量） */
  const allLayerInfos = computed<UnifiedLayerInfo[]>(() => {
    const list: UnifiedLayerInfo[] = []
    if (weatherLayerInfo.value) list.push(weatherLayerInfo.value)
    list.push(...rasterLayerInfos.value)
    list.push(...vectorLayerInfos.value)
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

    // 矢量图层（展示图层元信息，无点查数值）
    for (const info of vectorLayerInfos.value) {
      list.push({
        layerId: info.layerId,
        name: info.name,
        category: 'vector',
        value: null,
        valueText: '矢量图层',
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

  // ── D1: 量纲感知分组 ────────────────────────────────────────────────────────

  /** 按量纲（归一化单位）分组的时间序列 */
  const timeSeriesByUnit = computed<Record<string, MultiLayerSeries[]>>(() => {
    const groups: Record<string, MultiLayerSeries[]> = {}
    for (const s of allTimeSeries.value) {
      const key = normalizeUnitKey(s.unit ?? '')
      if (!groups[key]) groups[key] = []
      groups[key].push(s)
    }
    return groups
  })

  /** 按量纲分组的点值 */
  const pointValuesByUnit = computed<Record<string, UnifiedPointValue[]>>(() => {
    const groups: Record<string, UnifiedPointValue[]> = {}
    for (const v of unifiedPointValues.value) {
      if (v.value === null) continue // 跳过无数值的条目（如矢量图层）
      const key = normalizeUnitKey(v.unit)
      if (!groups[key]) groups[key] = []
      groups[key].push(v)
    }
    return groups
  })

  /** 量纲分组 key 列表（按出现顺序） */
  const unitGroupKeys = computed<string[]>(() => {
    const seen = new Set<string>()
    const keys: string[] = []
    for (const v of unifiedPointValues.value) {
      if (v.value === null) continue
      const key = normalizeUnitKey(v.unit)
      if (!seen.has(key)) {
        seen.add(key)
        keys.push(key)
      }
    }
    return keys
  })

  /** 是否存在多种量纲需要分组显示 */
  const hasMultipleUnits = computed(() => unitGroupKeys.value.length > 1)

  // ── D2: 时间轴类型分离 ─────────────────────────────────────────────────────

  /** 按时间轴类型分组的时间序列 */
  const timeSeriesByTimeAxisType = computed<Record<TimeAxisType, MultiLayerSeries[]>>(() => {
    const groups: Record<TimeAxisType, MultiLayerSeries[]> = {
      hourly: [],
      block: [],
      date: [],
      unknown: [],
    }
    for (const s of allTimeSeries.value) {
      const labels = s.data.map((p) => p.time)
      const axisType = detectTimeAxisType(labels)
      groups[axisType].push(s)
    }
    return groups
  })

  /** 时间轴类型中文标签 */
  const timeAxisTypeLabels: Record<TimeAxisType, string> = {
    hourly: '逐小时',
    block: '周期块',
    date: '逐日',
    unknown: '其他',
  }

  /** 存在数据的时间轴类型列表 */
  const activeTimeAxisTypes = computed<TimeAxisType[]>(() => {
    const groups = timeSeriesByTimeAxisType.value
    return (Object.keys(groups) as TimeAxisType[]).filter((t) => groups[t].length > 0)
  })

  /** 是否存在多种时间轴类型需要分离显示 */
  const hasMultipleTimeAxisTypes = computed(() => activeTimeAxisTypes.value.length > 1)

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
    vectorLayerInfos,
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
    // D1: 量纲感知分组
    timeSeriesByUnit,
    pointValuesByUnit,
    unitGroupKeys,
    hasMultipleUnits,
    // D2: 时间轴类型分离
    timeSeriesByTimeAxisType,
    timeAxisTypeLabels,
    activeTimeAxisTypes,
    hasMultipleTimeAxisTypes,
    // 可见性
    hasUnifiedData,
    hasMultiLayerTimeSeries,
    hasPointComparison,
  }
}
