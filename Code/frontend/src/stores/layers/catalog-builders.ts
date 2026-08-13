/**
 * 图层目录构建器与 hotspot 提取器（X1/D2 渐进拆分第一步）。
 *
 * 从 layers/index.ts（god store）抽出的模块级纯函数：
 * 不依赖 store 闭包，仅依赖 catalog 静态表与类型定义。
 * index.ts 经 re-export 保持既有引用兼容。
 */
import type { LayerDescriptor, WorkflowEvent } from '../../services/runtime-api'
import { formatWorkflowEventLine } from '../../utils/workflow-event-label'
import { LAYER_CATEGORIES, LAYER_LIBRARY } from './catalog'
import { isWeatherEngineCatalogId } from './weather-session'
import type {
  ActiveLayer,
  JobLayerItem,
  JobStatus,
  LayerCatalogItem,
  LayerHotspot,
  RuntimeLayerLibraryItem,
} from './types'

const MAX_EVENT_MESSAGE_COUNT = 5

export function getCatalogDisplayName(catalogId: string) {
  return LAYER_LIBRARY.find((item) => item.catalogId === catalogId)?.name ?? catalogId
}

export function isBlockedRunReadiness(readiness?: string | null) {
  return readiness === 'blocked'
}

export function asRecord(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === 'object' ? (value as Record<string, unknown>) : null
}

export function asNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

export function isRecognizedJobStatus(status: unknown): status is JobStatus {
  return (
    typeof status === 'string' &&
    ['running', 'succeeded', 'failed', 'queued', 'cancelled', 'retry_pending'].includes(status)
  )
}

export function isTerminalStatus(status: string) {
  // retry_pending 是非终态（等待重试），不应包含在此处
  return status === 'succeeded' || status === 'failed' || status === 'cancelled'
}

export function formatHotspotValue(value: unknown, unit?: unknown) {
  const unitLabel = typeof unit === 'string' ? unit : ''
  if (typeof value === 'number') {
    const text = Number.isInteger(value) ? String(value) : value.toFixed(2)
    return `${text}${unitLabel}`
  }
  if (typeof value === 'string' && value.trim()) {
    return `${value}${unitLabel}`
  }
  return '--'
}

export function buildHotspotFromFeature(
  feature: Record<string, unknown> | null,
  fallbackId: string,
  fallbackName: string,
  fallbackValue: string,
): LayerHotspot | null {
  const geometry = asRecord(feature?.geometry)
  const coordinates = Array.isArray(geometry?.coordinates) ? geometry.coordinates : null
  const lng = coordinates && coordinates.length >= 2 ? asNumber(coordinates[0]) : null
  const lat = coordinates && coordinates.length >= 2 ? asNumber(coordinates[1]) : null
  if (lng === null || lat === null) {
    return null
  }

  const properties = asRecord(feature?.properties)
  const pointValue = formatHotspotValue(properties?.value, properties?.unit)
  return {
    id: typeof properties?.id === 'string' && properties.id.trim() ? properties.id : fallbackId,
    name:
      (typeof properties?.place_name === 'string' && properties.place_name.trim()) ||
      (typeof properties?.name === 'string' && properties.name.trim()) ||
      fallbackName,
    lng,
    lat,
    value: pointValue !== '--' ? pointValue : fallbackValue,
  }
}

export function extractLayerHotspots(
  layer: ActiveLayer,
  item: RuntimeLayerLibraryItem,
  metricValue: string,
): LayerHotspot[] {
  const jobLayer = layer.jobLayer
  if (!jobLayer) return []

  const pointFeature = asRecord(jobLayer.mapLayerPayload?.pointFeature)
  const pointHotspot = buildHotspotFromFeature(
    pointFeature,
    `${layer.catalogId}-primary`,
    item.name,
    metricValue,
  )
  if (pointHotspot) {
    return [pointHotspot]
  }

  const resultDto = asRecord(jobLayer.resultDto)
  const metadata = asRecord(resultDto?.metadata)
  const latitude = asNumber(metadata?.latitude)
  const longitude = asNumber(metadata?.longitude)
  if (latitude === null || longitude === null) {
    return []
  }

  return [
    {
      id: `${layer.catalogId}-metadata`,
      name: (typeof metadata?.place_name === 'string' && metadata.place_name.trim()) || item.name,
      lng: longitude,
      lat: latitude,
      value: metricValue,
    },
  ]
}

export function mergeRecentEventMessages(
  existing: string[] | undefined,
  incoming: WorkflowEvent[],
) {
  const merged = [...(existing ?? [])]
  for (const event of incoming) {
    const text = formatWorkflowEventLine(event.channel, event.message)
    if (merged[merged.length - 1] !== text) {
      merged.push(text)
    }
  }
  return merged.slice(-MAX_EVENT_MESSAGE_COUNT)
}

export function hasRenderableMapLayerAsset(jobLayer: JobLayerItem | null | undefined) {
  const assets = jobLayer?.mapLayerPayload?.layerAssets
  return Boolean(
    assets?.geojsonData ||
    assets?.geojsonUrl ||
    assets?.cogUrl ||
    assets?.cogPreviewUrl ||
    assets?.overlayLayerId,
  )
}

const STATIC_LIBRARY_BY_ID = new Map(LAYER_LIBRARY.map((item) => [item.catalogId, item]))
/** 目录分类 → 展示顺序索引（layerLibrary 排序使用，需导出供 store 消费） */
export const CATEGORY_INDEX_BY_ID = new Map(
  LAYER_CATEGORIES.map((category, index) => [category.id, index]),
)

export function getStaticLayerLibraryItem(catalogId: string) {
  return STATIC_LIBRARY_BY_ID.get(catalogId)
}

export function formatClockLabel(value?: string | null) {
  if (!value) return '--'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return `${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`
}

/** BE/历史中文类别 → FE LAYER_CATEGORIES.id（英文） */
const CATEGORY_ALIASES: Record<string, string> = {
  气象场: 'weather',
  气候产品: 'climate',
}

export function resolveCategory(descriptor: LayerDescriptor, fallbackCategory?: string) {
  const raw = descriptor.category || fallbackCategory
  const category = raw ? (CATEGORY_ALIASES[raw] ?? raw) : undefined
  if (category && CATEGORY_INDEX_BY_ID.has(category)) {
    return category
  }
  return fallbackCategory ?? 'research-group'
}

export function buildUpdateLabel(
  descriptor: LayerDescriptor,
  fallback?: Pick<LayerCatalogItem, 'updateLabel'> | null,
) {
  if (fallback?.updateLabel) return fallback.updateLabel
  if (descriptor.status === 'sample') return '实验工作流'
  if (descriptor.is_realtime) return '实时更新'
  if (descriptor.supports_time) return '按时间维度'
  if (descriptor.status === 'placeholder') return '占位图层'
  return descriptor.engine ? '按工作流运行' : '按需加载'
}

export function buildSourceLabel(
  descriptor: LayerDescriptor,
  fallback?: Pick<LayerCatalogItem, 'sourceLabel'> | null,
) {
  if (fallback?.sourceLabel) return fallback.sourceLabel
  const sourceType = descriptor.source_type || 'runtime'
  const engine = descriptor.engine ? ` · ${descriptor.engine}` : ''
  return `${sourceType}${engine}`
}

export function buildRuntimeLayerLibraryItem(descriptor: LayerDescriptor): RuntimeLayerLibraryItem {
  const fallback = getStaticLayerLibraryItem(descriptor.layer_id)
  const category = resolveCategory(descriptor, fallback?.category)
  const categoryMeta = LAYER_CATEGORIES.find((item) => item.id === category)
  const descriptorSub =
    typeof (descriptor as { sub_category?: string | null }).sub_category === 'string'
      ? (descriptor as { sub_category?: string }).sub_category
      : undefined
  const subCategory =
    (descriptorSub as RuntimeLayerLibraryItem['subCategory'] | undefined) ?? fallback?.subCategory

  // X1: 优先使用后端 presentation 下发的 UI 呈现字段，静态 LAYER_LIBRARY 仅作兜底
  const pres = descriptor.presentation
  const hasPres = pres && typeof pres === 'object'
  const presValue = <T>(v: T | null | undefined): T | undefined => (v != null ? v : undefined)

  return {
    catalogId: descriptor.layer_id,
    name: descriptor.display_name,
    category,
    subCategory,
    description: descriptor.description,
    metricLabel:
      (hasPres ? presValue(pres.metric_label) : undefined) ?? fallback?.metricLabel ?? '主指标',
    metricUnit: (hasPres ? presValue(pres.metric_unit) : undefined) ?? fallback?.metricUnit ?? '',
    metricPrecision:
      (hasPres ? presValue(pres.metric_precision) : undefined) ?? fallback?.metricPrecision ?? 1,
    updateLabel:
      (hasPres ? presValue(pres.update_label) : undefined) ??
      buildUpdateLabel(descriptor, fallback ?? null),
    sourceLabel:
      (hasPres ? presValue(pres.source_label) : undefined) ??
      buildSourceLabel(descriptor, fallback ?? null),
    accentColor:
      (hasPres ? presValue(pres.accent_color) : undefined) ??
      fallback?.accentColor ??
      categoryMeta?.accentColor ??
      '#67d4ff',
    accentGlow:
      (hasPres ? presValue(pres.accent_glow) : undefined) ??
      fallback?.accentGlow ??
      'rgba(103, 212, 255, 0.28)',
    chipTone:
      (hasPres ? presValue(pres.chip_tone) : undefined) ??
      fallback?.chipTone ??
      categoryMeta?.chipTone ??
      'rgba(103, 212, 255, 0.16)',
    sources: fallback?.sources ?? [],
    isAdminBoundary: fallback?.isAdminBoundary,
    engine: descriptor.engine,
    sourceType: descriptor.source_type,
    renderType: descriptor.render_type,
    workflowName: descriptor.workflow_name,
    runReadiness: descriptor.run_readiness ?? 'ready',
    runReadinessSummary: descriptor.run_readiness_summary,
    runReadinessNotes: descriptor.run_readiness_notes ?? [],
    backendStatus: descriptor.status,
    defaultVisible: descriptor.default_visible,
    supportsTime: descriptor.supports_time,
  }
}

export function buildCatalogFallbackItem(
  item: RuntimeLayerLibraryItem | null,
  catalogId: string,
): RuntimeLayerLibraryItem {
  if (item) return item
  const fallback = getStaticLayerLibraryItem(catalogId)
  if (fallback) {
    return {
      ...fallback,
      description: `${fallback.name} 课题组数据信息尚未返回。`,
      runReadiness: 'unknown',
      runReadinessSummary: '课题组数据加载中',
      runReadinessNotes: [],
      backendStatus: null,
      engine: null,
      sourceType: null,
      renderType: null,
      workflowName: null,
      defaultVisible: undefined,
      supportsTime: undefined,
    }
  }

  return {
    catalogId,
    name: catalogId,
    category: 'research-group',
    description: '课题组数据尚未收录该图层。',
    metricLabel: '主指标',
    metricUnit: '',
    metricPrecision: 1,
    updateLabel: '待识别',
    sourceLabel: '课题组数据',
    accentColor: '#5a6a80',
    accentGlow: 'rgba(90, 106, 128, 0.3)',
    chipTone: 'rgba(90, 106, 128, 0.16)',
    sources: [],
    runReadiness: 'unknown',
    runReadinessSummary: '课题组数据加载中',
    runReadinessNotes: [],
    backendStatus: null,
    engine: null,
    sourceType: null,
    renderType: null,
    workflowName: null,
    defaultVisible: undefined,
    supportsTime: undefined,
  }
}

export function buildAvailabilityState(
  layer: ActiveLayer,
  item: RuntimeLayerLibraryItem,
  jobLayer?: JobLayerItem,
) {
  if (jobLayer) {
    if (jobLayer.status === 'succeeded') {
      return {
        state: 'ready' as const,
        label: '完整数据',
        description: jobLayer.reportSummary ?? jobLayer.message ?? '工作流结果已生成。',
      }
    }
    if (jobLayer.status === 'running') {
      return {
        state: 'partial' as const,
        label: '运行中',
        description: jobLayer.message || '正在生成最新结果。',
      }
    }
    if (jobLayer.status === 'queued' || jobLayer.status === 'retry_pending') {
      return {
        state: 'partial' as const,
        label: jobLayer.status === 'queued' ? '排队中' : '等待重试',
        description: jobLayer.message || '任务已提交，等待后端调度。',
      }
    }
    if (jobLayer.status === 'failed') {
      return {
        state: 'empty' as const,
        label: '数据异常',
        description: jobLayer.diagnosticNotes?.[0] ?? jobLayer.message ?? '工作流执行失败。',
      }
    }
    if (jobLayer.status === 'cancelled') {
      return {
        state: 'empty' as const,
        label: '已取消',
        description: jobLayer.message || '工作流已取消。',
      }
    }
  }

  if (isBlockedRunReadiness(item.runReadiness)) {
    return {
      state: 'empty' as const,
      label: '数据未就绪',
      description: item.runReadinessSummary ?? item.runReadinessNotes[0] ?? '默认数据源尚未就绪。',
    }
  }

  // 天气瓦片层：不依赖 workflow job，禁止回落到「待运行」
  if (isWeatherEngineCatalogId(layer.catalogId, null)) {
    return {
      state: 'partial' as const,
      label: '可查看',
      description: item.runReadinessSummary ?? '天气瓦片层，显示后由 tile manager 加载。',
    }
  }

  // 已有真实结果 / 导入产物 / 地图载荷：禁止仍显示「待运行」
  const hasMapPayload = Boolean(jobLayer?.mapLayerPayload)
  const hasImportedData =
    layer.dataState === 'imported' || Boolean(layer.importedRaster) || Boolean(layer.importedVector)
  if (layer.dataState === 'real' || hasMapPayload || hasImportedData) {
    return {
      state: hasImportedData || hasMapPayload ? ('ready' as const) : ('partial' as const),
      label: hasImportedData || hasMapPayload ? '完整数据' : '等待结果',
      description:
        item.runReadinessSummary ??
        (hasImportedData || hasMapPayload
          ? '图层数据已就绪。'
          : '图层已有运行结果，等待刷新或重新运行。'),
    }
  }

  if (item.backendStatus === 'sample') {
    return {
      state: 'partial' as const,
      label: '实验可运行',
      description:
        item.runReadinessSummary ??
        item.runReadinessNotes[0] ??
        '当前为实验 provider 链路，可用于算法联调与验收。',
    }
  }

  if (item.backendStatus === 'placeholder') {
    return {
      state: 'partial' as const,
      label: '占位图层',
      description: item.description || '该图层当前仍为占位产物，待数据源接入。',
    }
  }

  return {
    state: 'empty' as const,
    label: '待运行',
    description: item.runReadinessSummary ?? '图层已加入工作区，可按需运行工作流。',
  }
}
