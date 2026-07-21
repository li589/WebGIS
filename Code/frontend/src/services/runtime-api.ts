// 所有 API 契约类型从 openapi-typescript 自动生成的 `api-contracts.ts` 中 re-export。
// 手写 interface 已删除，统一由后端 OpenAPI schema 驱动。
// 消费方仍可从本模块导入这些类型名（如 `WorkflowSubmitRequest`、`RuntimeLayerDescriptor`）。
export * from '../types/api-reexports'

import type {
  WorkflowAcceptedResponse,
  WorkflowEventsResponse,
  WorkflowRunStatusResponse,
  WorkflowRunViewResponse,
  RuntimeLayerCatalogResponse,
  WeatherPointResponse,
  WorkflowSubmitRequest,
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

export function fetchLayerCatalog() {
  return requestJson<RuntimeLayerCatalogResponse>('/layers', {
    timeoutMs: 120000,
  })
}

export function getWorkflowRun(runId: string) {
  // 轮询请求：silent=true 跳过 loading 动效，避免频繁闪烁
  return requestJson<WorkflowRunStatusResponse>(`/workflow-runs/${runId}`, { silent: true })
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
  return requestJson<WorkflowEventsResponse>(`/workflow-runs/${runId}/events${suffix}`, { silent: true })
}

export function getWorkflowRunView(runId: string) {
  // 轮询请求：silent=true
  return requestJson<WorkflowRunViewResponse>(`/workflow-runs/${runId}/view`, { silent: true })
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
  if (typeof params.forecast_hours === 'number') search.set('forecast_hours', String(params.forecast_hours))
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

/** 手动触发 Open-Meteo 数据同步（异步任务；派发应秒级返回） */
export function triggerWeatherSync() {
  return requestJson<WeatherSyncTriggerResponse>('/weather/sync/trigger', {
    method: 'POST',
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
