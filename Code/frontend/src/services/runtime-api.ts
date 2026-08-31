// 所有 API 契约类型从 openapi-typescript 自动生成的 `api-contracts.ts` 中 re-export。
// 手写 interface 已删除，统一由后端 OpenAPI schema 驱动。
// 消费方仍可从本模块导入这些类型名（如 `WorkflowSubmitRequest`、`LayerDescriptor`）。
export * from '../types/api-reexports'

import type {
  WorkflowAcceptedResponse,
  WorkflowEventsResponse,
  WorkflowRunStatusResponse,
  WorkflowRunViewResponse,
  LayerCatalogResponse,
  LayerCategoryResponse,
  LayerLifecycleResponse,
  LayerOnlineSyncResponse,
  WeatherPointResponse,
  WorkflowSubmitRequest,
  WorkflowTemplateListResponse,
  WorkflowTemplateRunResponse,
} from '../types/api-reexports'
// Sprint 3.6: requestJson / resolveApiUrl 已抽取到 _http.ts 统一维护
import { requestJson, resolveApiUrl } from './_http'

// 向后兼容：workflow-definition-api.ts / weather-tile-api.ts 等模块从此处导入 resolveApiUrl
export { resolveApiUrl }

export function submitWorkflow(payload: WorkflowSubmitRequest) {
  return requestJson<WorkflowAcceptedResponse>('/workflow-runs', {
    method: 'POST',
    body: JSON.stringify(payload),
    timeoutMs: 120000,
  })
}

/** 统一图层资产工作流：检查烘焙资产，陈旧/缺失则后台重烘。 */
export function submitOverlayAssetWorkflow(layerId: string, forceRebake = false) {
  const suffix = forceRebake ? '?force_rebake=true' : ''
  return requestJson<WorkflowAcceptedResponse>(
    `/overlay-asset-workflows/${encodeURIComponent(layerId)}${suffix}`,
    {
      method: 'POST',
      body: '{}',
      timeoutMs: 120000,
    },
  )
}

/** 图层平台子系统 P0：图层生命周期聚合查询（资产 + 最近 run + 时间轴）。 */
export function fetchLayerLifecycle(layerId: string) {
  return requestJson<LayerLifecycleResponse>(
    `/layers/${encodeURIComponent(layerId)}/lifecycle`,
    { silent: true, timeoutMs: 30000 },
  )
}

/** 图层平台子系统 P1：在线源同步统一入口（workflow_kind=online_sync）。 */
export function syncLayerAssetOnline(
  layerId: string,
  options?: { timeKey?: string; isPrefetch?: boolean; priority?: 'low' | 'normal' },
) {
  return requestJson<LayerOnlineSyncResponse>(
    `/layer-assets/${encodeURIComponent(layerId)}/sync`,
    {
      method: 'POST',
      body: JSON.stringify({
        time_key: options?.timeKey ?? null,
        is_prefetch: options?.isPrefetch ?? false,
        priority: options?.priority ?? 'normal',
      }),
      timeoutMs: 120000,
    },
  )
}

/** 图层平台子系统 P1：课题组工作流模板列表。 */
export function fetchWorkflowTemplates() {
  return requestJson<WorkflowTemplateListResponse>('/workflows/templates', {
    timeoutMs: 30000,
  })
}

/** 图层平台子系统 P1：模板一键运行（完成后自动上图）。 */
export function runWorkflowTemplate(
  workflowId: string,
  options?: {
    parameters?: Record<string, unknown>
    timeRange?: { start_at: string; end_at: string }
    resourceProfile?: string
    autoDisplay?: boolean
  },
) {
  return requestJson<WorkflowTemplateRunResponse>(
    `/workflows/templates/${encodeURIComponent(workflowId)}/runs`,
    {
      method: 'POST',
      body: JSON.stringify({
        parameters: options?.parameters ?? {},
        time_range: options?.timeRange ?? null,
        resource_profile: options?.resourceProfile ?? null,
        auto_display: options?.autoDisplay ?? null,
      }),
      timeoutMs: 120000,
    },
  )
}

export function fetchLayerCatalog() {
  return requestJson<LayerCatalogResponse>('/layers', {
    timeoutMs: 120000,
  })
}

/** X1: 从后端获取图层分类定义（含 UI 样式 accentColor / chipTone）。 */
export function fetchLayerCategories() {
  return requestJson<LayerCategoryResponse>('/layers/categories', {
    timeoutMs: 30000,
  })
}

export function getWorkflowRun(runId: string) {
  // 轮询请求：silent=true 跳过 loading 动效，避免频繁闪烁
  return requestJson<WorkflowRunStatusResponse>(`/workflow-runs/${runId}`, { silent: true })
}

/** 列出后端活跃工作流 run（非终态），供启动恢复与跨会话状态同步。 */
export function listActiveWorkflowRuns() {
  return requestJson<WorkflowRunStatusResponse[]>('/workflow-runs?active_only=true', {
    silent: true,
  })
}

/**
 * 列出最近成功的终态 run（按创建时间倒序），用于启动时自动恢复
 * 已成功工作流的产物图层（无需本地跟踪记录）。
 */
export function listRecentSucceededRuns(limit = 20) {
  return requestJson<WorkflowRunStatusResponse[]>(
    `/workflow-runs?active_only=false&status=succeeded&limit=${limit}`,
    { silent: true },
  )
}

export function getWorkflowEvents(
  runId: string,
  options?: {
    afterEventId?: string
    limit?: number
  },
) {
  const search = new URLSearchParams()
  if (options?.afterEventId) search.set('after_event_id', options.afterEventId)
  if (typeof options?.limit === 'number') search.set('limit', String(options.limit))
  const suffix = search.toString() ? `?${search.toString()}` : ''
  // 轮询请求：silent=true
  return requestJson<WorkflowEventsResponse>(`/workflow-runs/${runId}/events${suffix}`, {
    silent: true,
  })
}

export function getWorkflowRunView(runId: string) {
  // 轮询请求：silent=true
  return requestJson<WorkflowRunViewResponse>(`/workflow-runs/${runId}/view`, { silent: true })
}

export function materializeWorkflowMapLayers(
  runId: string,
  options?: { silent?: boolean },
) {
  // 默认 silent：渐进物化与失败竞态下的 409（retry_pending/failed）属预期，
  // 勿写入「Request failed」用户日志；显式 silent:false 仅用于调试。
  return requestJson<{
    run_id: string
    layers: Array<{
      overlay_layer_id: string
      title?: string
      product_tag?: string
      bounds?: [number, number, number, number] | (number | null)[] | null
      source_crs?: string | null
      cog_preview_url?: string | null
      time_list?: string[]
      default_time?: string | null
      native_step?: string | null
    }>
    count?: number
    message?: string
  }>(`/workflow-runs/${runId}/materialize-map-layers`, {
    method: 'POST',
    body: '{}',
    timeoutMs: 300000,
    silent: options?.silent !== false,
  })
}

export function getWeatherPoint(params: {
  layer_id: string
  latitude: number
  longitude: number
  model?: string
  forecast_hours?: number
  place_name?: string
  provider?: string
  signal?: AbortSignal
}) {
  const search = new URLSearchParams({
    layer_id: params.layer_id,
    latitude: String(params.latitude),
    longitude: String(params.longitude),
  })
  if (params.model) search.set('model', params.model)
  if (typeof params.forecast_hours === 'number')
    search.set('forecast_hours', String(params.forecast_hours))
  if (params.place_name) search.set('place_name', params.place_name)
  if (params.provider && params.provider !== 'auto') search.set('provider', params.provider)
  return requestJson<WeatherPointResponse>(`/weather/point?${search.toString()}`, {
    signal: params.signal,
  })
}

export interface WeatherProviderForLayer {
  provider_id: string
  display_name: string
  enabled: boolean
  priority: number
  provider_type: string
  /** dense = native multi-point grid; sparse = commercial point-sampled */
  grid_mode?: 'dense' | 'sparse' | string
  /** Commercial coverage quality for this layer */
  data_quality?: 'observed' | 'extrapolated' | 'sparse' | string
  /** Short Chinese hint for UI (外推 / 稀疏 / 近地面) */
  hint?: string
}

export function getWeatherProvidersForLayer(
  layerId: string,
  options?: { includeDisabled?: boolean; signal?: AbortSignal },
) {
  const search = new URLSearchParams()
  if (options?.includeDisabled) search.set('include_disabled', 'true')
  const suffix = search.toString() ? `?${search.toString()}` : ''
  return requestJson<{ layer_id: string; providers: WeatherProviderForLayer[] }>(
    `/weather/providers-for-layer/${encodeURIComponent(layerId)}${suffix}`,
    { signal: options?.signal },
  )
}

/** 本地 Open-Meteo 数据覆盖范围（与瓦片 hour 索引对齐） */
export interface WeatherCoverage {
  model: string
  source: string
  data_start_iso: string
  data_end_iso: string
  hour_count: number
  /** temperature 非空时次数量 */
  valid_hour_count?: number
  /** 与 tile hour 对齐的完整 ISO 时次（可含空值） */
  times?: string[]
  /** 非空温度时次；时间轴着色优先使用 */
  valid_times?: string[]
  max_tile_hour?: number
  probe_ts: number
}

/**
 * 查询本地 Open-Meteo 数据覆盖范围。
 *
 * 用于前端时间轴限制可选时段，避免显示"有数据但瓦片空白"。
 * 本地容器未启动时抛错；调用方应捕获并降级。
 */
export function getWeatherCoverage(model?: string, signal?: AbortSignal) {
  const search = new URLSearchParams()
  if (model) search.set('model', model)
  const suffix = search.toString() ? `?${search.toString()}` : ''
  return requestJson<WeatherCoverage>(`/weather/coverage${suffix}`, {
    signal,
    timeoutMs: 8000,
    silent: true,
  })
}

/** Phase 2: Open-Meteo 同步任务触发响应 */
export interface WeatherSyncTriggerResponse {
  status: string
  task_id: string
  message: string
  /** celery | local_thread */
  mode?: string
  /** Domains used for this sync (env default or one-shot override) */
  domains?: string
}

/** Phase 2: Open-Meteo 同步任务状态 */
export interface WeatherSyncStatus {
  task_id: string
  state: string // PENDING | STARTED | SUCCESS | FAILURE | RETRY
  info: unknown
  mode?: string
  error?: string
  finished_at?: string | null
}

/** 手动触发 Open-Meteo 数据同步（异步任务；派发应秒级返回）。
 *  ``domains`` 为一次性覆盖，不改 ``OPEN_METEO_SYNC_DOMAINS``。
 */
export function triggerWeatherSync(options?: { domains?: string }) {
  const body = options?.domains && options.domains.trim() ? { domains: options.domains.trim() } : {}
  return requestJson<WeatherSyncTriggerResponse>('/weather/sync/trigger', {
    method: 'POST',
    body: JSON.stringify(body),
    timeoutMs: 15000,
    silent: true,
  })
}

/** 查询同步任务状态（轮询用） */
export function getWeatherSyncStatus(taskId: string, signal?: AbortSignal) {
  return requestJson<WeatherSyncStatus>(
    `/weather/sync/status?task_id=${encodeURIComponent(taskId)}`,
    { signal, silent: true, timeoutMs: 8000 },
  )
}

export interface WeatherSyncOverview {
  local_reachable: boolean
  /** Docker CLI + compose file ready for sync */
  sync_service_available?: boolean
  domains: string[]
  variables?: string[]
  models_meta?: Array<{
    id: string
    label: string
    region: string
    update_interval: string
    native_resolution?: string
    forecast_horizon?: string
  }>
  data_mode?: 'forecast' | string
  spatial?: {
    scope: string
    native_resolution: string
    regions?: string[]
    resolutions?: string[]
  }
  temporal?: {
    kind: string
    probe_forecast_days: number
    tile_hour_cap: number
    runtime_forecast_days: number
    cron: { minute: string; hour: string; timezone: string }
    last_success_at?: string | null
  }
  coverage?: {
    model?: string
    data_start_iso?: string
    data_end_iso?: string
    hour_count?: number
    valid_hour_count?: number
    max_tile_hour?: number
  } | null
  coverage_error?: string | null
  sync_in_progress?: boolean
  enabled: boolean
  cron: { minute: string; hour: string; timezone: string }
  compose_project?: string
  compose_dir?: string
  compose_file_exists?: boolean
  docker_cli_available?: boolean
  last_success_at?: string | null
  last_failure_at?: string | null
  last_message?: string
  last_ok?: boolean | null
  last_finished_at?: string | null
  compose_hint?: string
}

export function getWeatherSyncOverview(signal?: AbortSignal) {
  return requestJson<WeatherSyncOverview>('/weather/sync/overview', {
    signal,
    silent: true,
    timeoutMs: 8000,
  })
}

export interface OverlayPointValue {
  layer_id: string
  value: number | null
  unit: string
  time: string | null
  lng: number
  lat: number
  error?: string
}

export function getOverlayValue(
  layerId: string,
  lng: number,
  lat: number,
  time?: string | null,
  signal?: AbortSignal,
): Promise<OverlayPointValue> {
  const search = new URLSearchParams({
    lng: String(lng),
    lat: String(lat),
  })
  if (time) search.set('time', time)
  return requestJson<OverlayPointValue>(`/overlay-value/${layerId}?${search.toString()}`, {
    signal,
  })
}

export function cancelWorkflowRun(runId: string) {
  return requestJson<WorkflowRunStatusResponse>(`/workflow-runs/${runId}/cancel`, {
    method: 'POST',
  })
}

export function retryWorkflowRun(runId: string) {
  return requestJson<WorkflowAcceptedResponse>(`/workflow-runs/${runId}/retry`, {
    method: 'POST',
  })
}

// ─── 节点产物缓存管理（cleanup router） ─────────────────────────────────────

export interface NodeCacheEntry {
  name: string
  path: string
  size_bytes: number
  file_count: number
  modified_at: string | null
}

export interface NodeCacheListResponse {
  entries: NodeCacheEntry[]
  total_bytes: number
}

export interface NodeCacheCleanupResponse {
  deleted: string[]
  failed: string[]
  freed_bytes: number
}

/** 列出工作流节点产物缓存（每个算法模块的目录/大小/文件数）。 */
export function listNodeCaches() {
  return requestJson<NodeCacheListResponse>('/cleanup/node-caches', {
    silent: true,
    sensitiveGet: true,
    timeoutMs: 60000,
  })
}

/** 清理工作流节点产物缓存；names 缺省表示全部。 */
export function cleanupNodeCaches(names?: string[]) {
  return requestJson<NodeCacheCleanupResponse>('/cleanup/node-caches', {
    method: 'POST',
    body: JSON.stringify({ names: names ?? null }),
    timeoutMs: 300000,
  })
}
