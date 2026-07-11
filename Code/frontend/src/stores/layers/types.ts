// ─── Layer category & source ─────────────────────────────────────────────────

export interface LayerCategory {
  id: string
  name: string
  icon: string
  accentColor: string
  chipTone: string
}

export interface LayerSource {
  id: string
  name: string
  description: string
  /** URL 模板，{x}/{y}/{z} 占位符，可包含参数如 {time} */
  urlTemplate: string
  /** 附加 URL 参数 */
  urlParams?: Record<string, string>
  /** 需要认证 (API Key) */
  needsAuth: boolean
  /** 需要后端坐标转换 */
  needsBackendTransform: boolean
  /** 坐标系 */
  coordSys: 'EPSG:3857' | 'GCJ-02' | 'BD-09'
  /** 数据更新频率描述 */
  updateFrequency: string
  attribution?: string
}

// ─── Layer catalog item (图层库条目) ─────────────────────────────────────────

export interface LayerCatalogItem {
  /** 唯一标识，与后端 layer_id 对齐 */
  catalogId: string
  name: string
  category: string
  metricLabel: string
  metricUnit: string
  metricPrecision: number
  updateLabel: string
  sourceLabel: string
  accentColor: string
  accentGlow: string
  chipTone: string
  /** 可选数据源列表，为空则使用默认源 */
  sources: LayerSource[]
  /** 是否内置行政区边界图层 */
  isAdminBoundary?: boolean
}

export interface RuntimeLayerLibraryItem extends LayerCatalogItem {
  description: string
  engine?: string | null
  sourceType?: string | null
  renderType?: string | null
  workflowName?: string | null
  runReadiness: string
  runReadinessSummary?: string | null
  runReadinessNotes: string[]
  backendStatus?: string | null
  defaultVisible?: boolean
  supportsTime?: boolean
}

// ─── Job layer item (作业生产数据) ───────────────────────────────────────────

export type JobStatus = 'running' | 'succeeded' | 'failed' | 'queued' | 'cancelled' | 'retry_pending'

// ─── Workflow summary (全局工作流状态汇总) ──────────────────────────────────

export interface WorkflowSummary {
  total: number
  running: number
  queued: number
  succeeded: number
  failed: number
  cancelled: number
  retryPending: number
  /** 整体状态：idle | active | succeeded | failed | mixed */
  overall: 'idle' | 'active' | 'succeeded' | 'failed' | 'mixed'
  /** 用于按钮配色的状态键 */
  tone: 'idle' | 'active' | 'success' | 'warning' | 'error'
  hasError: boolean
}

import type { WeatherLayerRenderHint, WorkflowResultDto, WorkflowRunViewResponse } from '../../services/runtime-api'

export type { WeatherLayerRenderHint }

export interface JobLayerMapAssets {
  geojsonUrl?: string
  geojsonData?: Record<string, unknown>
  cogUrl?: string
  cogPreviewUrl?: string
  cogBbox?: {
    west: number
    south: number
    east: number
    north: number
    crs?: string
  }
}

export interface JobLayerMapLayerPayload {
  renderHint?: WeatherLayerRenderHint
  pointFeature?: Record<string, unknown>
  layerAssets?: JobLayerMapAssets
}

export interface JobLayerItem {
  /** 作业 ID (run_id) */
  jobId: string
  /** 作业标签/名称 */
  name: string
  commandType: string
  status: JobStatus
  /** 0-100 */
  progress: number
  createdAt: string
  updatedAt: string
  message: string
  /** 简要指标 */
  metrics?: Array<{ label: string; value: string }>
  /** 报告文本摘要 */
  reportSummary?: string
  /** 统一结果视图 */
  resultDto?: WorkflowResultDto
  /** UI 视图模型 */
  resultView?: WorkflowRunViewResponse
  /** 结果引用链接 */
  resultUrl?: string
  /** map_layer 产物中的附加地图资产 */
  mapLayerPayload?: JobLayerMapLayerPayload
  /** 原始诊断信息 */
  diagnostics?: string[]
  /** 面向 UI 的诊断摘要 */
  diagnosticNotes?: string[]
  /** 最近一次已消费的事件游标 */
  lastEventId?: string
  /** 最近一次事件时间 */
  lastEventAt?: string
  /** 最近的增量事件消息，用于运行中展示持续产出 */
  eventMessages?: string[]
}

// ─── Active layer (已添加图层) ────────────────────────────────────────────────

export interface ActiveLayer {
  /** 实例 ID (uuid)，用于列表 key 和唯一性 */
  instanceId: string
  catalogId: string
  /** 是否可见 */
  visible: boolean
  /** 透明度 0-1 */
  opacity: number
  /** 叠加顺序，数字越大越在上层 */
  order: number
  /** 是否为行政区边界图层 */
  isAdminBoundary: boolean
  /** 若来自作业，则关联作业信息 */
  jobLayer?: JobLayerItem
  /** 数据状态：catalog | real */
  dataState: 'catalog' | 'real'
}

// ─── Layer sidebar view mode ──────────────────────────────────────────────────

export type LayerSidebarView = 'empty' | 'library' | 'active'

// ─── Derived types ────────────────────────────────────────────────────────────

export type AvailabilityState = 'empty' | 'partial' | 'ready'

export interface LayerHotspot {
  id: string
  name: string
  lng: number
  lat: number
  value: string
}

export interface ActiveLayerDisplay {
  instanceId: string
  catalogId: string
  name: string
  category: string
  description?: string
  engine?: string | null
  supportsTime?: boolean
  runReadiness?: string
  runReadinessSummary?: string | null
  summary: string
  metricLabel: string
  metricValue: string
  trendLabel: string
  statusLabel: string
  updateLabel: string
  sourceLabel: string
  confidenceLabel: string
  accentColor: string
  accentGlow: string
  chipTone: string
  availabilityState: AvailabilityState
  availabilityLabel: string
  availabilityDescription: string
  observationTimeLabel: string
  missingFieldsLabel: string
  hotspots: LayerHotspot[]
  isAdminBoundary: boolean
  jobLayer?: JobLayerItem
  visible: boolean
  opacity: number
  order: number
  dataState: 'catalog' | 'real'
  /** 天气图层默认渲染提示（tile manager 路径下使用） */
  renderHint?: WeatherLayerRenderHint
}
