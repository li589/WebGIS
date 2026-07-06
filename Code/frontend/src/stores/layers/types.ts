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
  /** 唯一标识，与 demoLayerCatalog id 对齐 */
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

// ─── Job layer item (作业生产数据) ───────────────────────────────────────────

export type JobStatus = 'running' | 'succeeded' | 'failed' | 'queued' | 'cancelled'

import type { WeatherLayerRenderHint, WorkflowResultDto, WorkflowRunViewResponse } from '../../services/runtime-api'

export interface JobLayerMapAssets {
  geojsonUrl?: string
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
}

// ─── Active layer (已添加图层) ────────────────────────────────────────────────

export interface ActiveLayer {
  /** 实例 ID (uuid)，用于列表 key 和唯一性 */
  instanceId: string
  catalogId: string
  /** 当前选中的数据源 ID，为空使用 catalog 默认源 */
  sourceId: string
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
  /** 数据状态：demo | real */
  dataState: 'demo' | 'real'
}

// ─── Layer sidebar view mode ──────────────────────────────────────────────────

export type LayerSidebarView = 'empty' | 'library' | 'active'

// ─── Derived types (从 demo-data 适配) ────────────────────────────────────────

export type AvailabilityState = 'empty' | 'partial' | 'ready'

export interface ActiveLayerDisplay {
  instanceId: string
  catalogId: string
  name: string
  category: string
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
  hotspots: Array<{
    id: string
    name: string
    lng: number
    lat: number
    value: string
  }>
  isAdminBoundary: boolean
  jobLayer?: JobLayerItem
  visible: boolean
  opacity: number
  order: number
  dataState: 'demo' | 'real'
}
