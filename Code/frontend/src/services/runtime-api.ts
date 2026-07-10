export type ExecutionStatus =
  | 'accepted'
  | 'queued'
  | 'running'
  | 'succeeded'
  | 'failed'
  | 'cancelled'
  | 'retry_pending'

export type WorkflowCommandType =
  | 'analysis'
  | 'layer_preview'
  | 'export'
  | 'refresh_data'
  | 'sync_demo'
  | 'custom'

export type ResultKind = 'json' | 'table' | 'chart' | 'map_layer' | 'log' | 'file' | 'text' | 'diagnostic'
export type EventChannel = 'status' | 'log' | 'data' | 'chart' | 'notification' | 'system'
export type LogLevel = 'debug' | 'info' | 'warning' | 'error'
export interface BoundingBox {
  west: number
  south: number
  east: number
  north: number
  crs?: string
}

export interface SpatialFilter {
  filter_type?: string
  bbox?: BoundingBox
  region_code?: string
  region_name?: string
}

export interface TimeRange {
  start_at: string
  end_at: string
  granularity?: 'hour' | 'day' | 'month'
}

export interface ClientIdentity {
  client_id?: string
  session_id?: string
  page?: string
  view_id?: string
  user_agent?: string
}

export interface RuntimeMapContext {
  active_layer_id?: string
  basemap_mode?: string
  map_mode?: '2d' | '3d'
  viewport_bbox?: BoundingBox
}

export interface WorkflowSubmitRequest {
  command_type: WorkflowCommandType
  command_label?: string
  layer_id?: string
  priority?: 'low' | 'normal' | 'high' | 'critical'
  resource_profile?: 'light' | 'standard' | 'heavy' | 'batch'
  realtime_preferred?: boolean
  queue_tag?: string
  spatial_filter?: SpatialFilter
  time_range?: TimeRange
  parameters?: Record<string, unknown>
  algorithm_request?: Record<string, unknown>
  gee_request?: Record<string, unknown>
  weather_request?: Record<string, unknown>
  config_overrides?: Record<string, unknown>
  requested_outputs?: Array<ResultKind | string>
  client?: ClientIdentity
  map_context?: RuntimeMapContext
  correlation_id?: string
  retry_policy?: { max_attempts?: number; initial_backoff_seconds?: number }
  retry_attempt?: number
}

export interface WorkflowAcceptedResponse {
  run_id: string
  status: ExecutionStatus
  status_url: string
  events_url: string
  created_at: string
  message: string
}

export interface WorkflowResultReference {
  result_id: string
  result_kind: ResultKind
  title: string
  mime_type: string
  inline_data?: Record<string, unknown>
  resource_url?: string
  resource_backend?: string
  resource_key?: string
  resource_size_bytes?: number
  updated_at: string
}

export interface WorkflowEvent {
  event_id: string
  run_id: string
  channel: EventChannel
  level: LogLevel
  message: string
  created_at: string
  progress?: number | null
  payload: Record<string, unknown>
}

export interface WorkflowEventsResponse {
  run_id: string
  items: WorkflowEvent[]
}

export interface WorkflowAnalysisResultDto {
  workflow_entry_name?: string
  layer_id?: string
  requested_hour?: number | null
  metric_label?: string | null
  metric_value?: string | number | null
  metric_unit?: string | null
  hotspot_count?: number | null
  availability_state?: string | null
  data_state_mode?: string | null
  result_category?: 'analysis' | string
  results?: Record<string, string | null>
}

export interface WorkflowProviderResultDto {
  workflow_entry_name?: string
  layer_id?: string
  provider_key?: string | null
  summary?: string | null
  metric_label?: string | null
  metric_unit?: string | null
  metric_value?: string | number | null
  status_label?: string | null
  confidence_label?: string | null
  hotspot_count?: number | null
  series_point_count?: number | null
  result_category?: 'provider' | string
  metadata?: Record<string, unknown>
}

export interface WorkflowDownloadResultDto {
  workflow_entry_name?: string
  layer_id?: string
  requested_hour?: number | null
  download_ticket_id?: string | null
  execution_status?: string | null
  job_state?: Record<string, unknown>
  follow_up_policy?: string | null
  source_mode?: string | null
  refresh_policy?: string | null
  cache_status?: string | null
  cache_key?: string | null
  manifest_result_id?: string | null
  result_category?: 'download' | string
}

export type WorkflowResultDto = WorkflowAnalysisResultDto | WorkflowProviderResultDto | WorkflowDownloadResultDto | Record<string, unknown>

export interface WorkflowRunStatusResponse {
  run_id: string
  command_type: WorkflowCommandType
  command_label?: string
  layer_id?: string
  priority?: 'low' | 'normal' | 'high' | 'critical'
  resource_profile?: 'light' | 'standard' | 'heavy' | 'batch'
  realtime_preferred?: boolean
  queue_tag?: string
  status: ExecutionStatus
  progress: number
  message: string
  created_at: string
  updated_at: string
  spatial_filter?: SpatialFilter
  time_range?: TimeRange
  requested_outputs: Array<ResultKind | string>
  client: ClientIdentity
  map_context: RuntimeMapContext
  config_overrides: Record<string, unknown>
  executor_metadata: Record<string, unknown>
  result_refs: WorkflowResultReference[]
  result_dto?: WorkflowResultDto | null
  diagnostics: string[]
}

export interface WorkflowRunViewSummaryRow {
  label: string
  value: string
}

export interface WorkflowRunViewResponse {
  run_id: string
  category: string
  title: string
  subtitle: string
  status_text: string
  progress_text: string
  summary?: string | null
  metric_rows: WorkflowRunViewSummaryRow[]
  result_url?: string | null
  artifact_refs: WorkflowResultReference[]
  can_show_link: boolean
  updated_at: string
}

export interface RuntimeLayerDescriptor {
  layer_id: string
  dataset_key: string
  display_name: string
  description: string
  category: string
  source_type: string
  render_type: string
  supported_map_modes: string[]
  supports_time?: boolean
  is_realtime?: boolean
  default_visible?: boolean
  status: string
  module_name?: string | null
  engine?: string | null
  workflow_name?: string | null
  workflow_id?: string | null
  workflow_definition?: Record<string, unknown> | null
  default_task_type?: string | null
  default_data_access_sources?: Record<string, string[]>
  run_readiness?: string
  run_readiness_summary?: string | null
  run_readiness_notes?: string[]
}

export interface RuntimeLayerCatalogResponse {
  items: RuntimeLayerDescriptor[]
}

export interface WeatherLayerRenderHint {
  layer_id: string
  paint_mode: string
  palette: string
  primary_metric: string
  unit_label: string
  opacity: number
  legend_ticks: Array<number | string>
  notes: string[]
}

export interface WeatherPointCurrent {
  temperature_2m?: number | null
  apparent_temperature?: number | null
  precipitation?: number | null
  rain?: number | null
  weather_code?: number | null
  cloud_cover?: number | null
  pressure_msl?: number | null
  wind_speed_10m?: number | null
  wind_direction_10m?: number | null
  wind_gusts_10m?: number | null
  // 多高度风场/温度（80m/120m/180m）
  wind_speed_80m?: number | null
  wind_direction_80m?: number | null
  wind_speed_120m?: number | null
  wind_direction_120m?: number | null
  wind_speed_180m?: number | null
  wind_direction_180m?: number | null
  temperature_80m?: number | null
  temperature_120m?: number | null
  temperature_180m?: number | null
  // 湿度与露点
  relative_humidity_2m?: number | null
  dew_point_2m?: number | null
  // 能见度
  visibility?: number | null
  // 气压层变量（850hPa/500hPa/200hPa）
  wind_speed_850hPa?: number | null
  wind_direction_850hPa?: number | null
  temperature_850hPa?: number | null
  wind_speed_500hPa?: number | null
  wind_direction_500hPa?: number | null
  temperature_500hPa?: number | null
  wind_speed_200hPa?: number | null
  wind_direction_200hPa?: number | null
  temperature_200hPa?: number | null
}

export interface WeatherPointHourlyEntry {
  time: string
  temperature_2m?: number | null
  precipitation?: number | null
  wind_speed_10m?: number | null
  primary_metric?: string | null
  primary_value?: number | null
}

export interface WeatherPointResponse {
  provider: string
  model: string
  resolved_model?: string | null
  layer_id: string
  latitude: number
  longitude: number
  place_name?: string | null
  timezone?: string | null
  fetched_at: string
  observation_time?: string | null
  cache_status: string
  summary: string
  current: WeatherPointCurrent
  hourly: WeatherPointHourlyEntry[]
  render_hint: WeatherLayerRenderHint
  diagnostics: string[]
}

const DEBUG_RUNTIME_API_URL = 'http://127.0.0.1:7777/event'
const DEBUG_RUNTIME_SESSION_ID = 'runtime-api-pending'
const DEBUG_RUNTIME_RUN_ID = 'post-fix'
const RUNTIME_API_DEBUG_ENABLED = import.meta.env.VITE_RUNTIME_API_DEBUG === '1'

function shouldReportRuntimeDebug(path: string) {
  if (!RUNTIME_API_DEBUG_ENABLED) return false
  return path.startsWith('/runtime/api-config')
    || path === '/workflow-runs'
    || /^\/workflow-runs\/[^/]+(?:\/events|\/view)?(?:\?.*)?$/.test(path)
}

function getRuntimeDebugHypothesisId(path: string) {
  if (path.startsWith('/runtime/api-config')) return 'A'
  if (path === '/workflow-runs') return 'B'
  return 'E'
}

// #region debug-point B:runtime-api-report-helper
function reportRuntimeDebug(path: string, location: string, msg: string, data: Record<string, unknown>) {
  fetch(DEBUG_RUNTIME_API_URL, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      sessionId: DEBUG_RUNTIME_SESSION_ID,
      runId: DEBUG_RUNTIME_RUN_ID,
      hypothesisId: getRuntimeDebugHypothesisId(path),
      location,
      msg,
      data,
      ts: Date.now(),
    }),
  }).catch(() => {})
}
// #endregion

function getApiBaseUrl() {
  // 开发模式走 Vite proxy（相对路径），避免 CORS 问题
  if (import.meta.env.DEV) return ''
  return import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, '') ?? ''
}

export function resolveApiUrl(pathOrUrl: string) {
  if (/^https?:\/\//i.test(pathOrUrl)) return pathOrUrl
  const normalizedPath = pathOrUrl.startsWith('/') ? pathOrUrl : `/${pathOrUrl}`
  return `${getApiBaseUrl()}${normalizedPath}`
}

async function requestJson<T>(path: string, init?: RequestInit & { timeoutMs?: number }): Promise<T> {
  const { headers: initHeaders, timeoutMs, ...restInit } = init ?? {}
  const mergedHeaders: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(initHeaders as Record<string, string> | undefined),
  }

  const controller = new AbortController()
  const timeoutId = window.setTimeout(
    () => controller.abort(),
    timeoutMs ?? 30000,
  )
  const shouldDebug = shouldReportRuntimeDebug(path)

  try {
    // #region debug-point B:request-json-start
    if (shouldDebug) {
      reportRuntimeDebug(path, 'runtime-api.requestJson.start', '[DEBUG] request start', {
        path,
        method: restInit.method ?? 'GET',
        timeoutMs: timeoutMs ?? 30000,
        hasExternalSignal: Boolean(restInit.signal),
      })
    }
    // #endregion
    const response = await fetch(resolveApiUrl(path), {
      ...restInit,
      headers: mergedHeaders,
      signal: restInit.signal ?? controller.signal,
    })

    // #region debug-point B:request-json-response
    if (shouldDebug) {
      reportRuntimeDebug(path, 'runtime-api.requestJson.response', '[DEBUG] request response received', {
        path,
        method: restInit.method ?? 'GET',
        status: response.status,
        ok: response.ok,
      })
    }
    // #endregion

    if (!response.ok) {
      // 修复：解析结构化错误体，而非丢弃
      let errorDetail = ''
      try {
        const errorBody = await response.json()
        errorDetail = errorBody?.user_message || errorBody?.error || errorBody?.detail || JSON.stringify(errorBody)
      } catch {
        errorDetail = await response.text().catch(() => '')
      }
      // #region debug-point A:request-json-error-response
      if (shouldDebug) {
        reportRuntimeDebug(path, 'runtime-api.requestJson.error_response', '[DEBUG] request error response', {
          path,
          method: restInit.method ?? 'GET',
          status: response.status,
          detail: errorDetail,
        })
      }
      // #endregion
      throw new Error(`Request failed: ${response.status} ${path}${errorDetail ? ` - ${errorDetail}` : ''}`)
    }

    const body = (await response.json()) as T
    // #region debug-point B:request-json-success
    if (shouldDebug) {
      reportRuntimeDebug(path, 'runtime-api.requestJson.success', '[DEBUG] request json parsed', {
        path,
        method: restInit.method ?? 'GET',
        bodyType: Array.isArray(body) ? 'array' : typeof body,
        topLevelKeys: body && typeof body === 'object' && !Array.isArray(body)
          ? Object.keys(body as Record<string, unknown>).slice(0, 8)
          : [],
      })
    }
    // #endregion
    return body
  } catch (error) {
    // #region debug-point C:request-json-catch
    if (shouldDebug) {
      reportRuntimeDebug(path, 'runtime-api.requestJson.catch', '[DEBUG] request threw', {
        path,
        method: restInit.method ?? 'GET',
        errorName: error instanceof Error ? error.name : typeof error,
        errorMessage: error instanceof Error ? error.message : String(error),
      })
    }
    // #endregion
    throw error
  } finally {
    window.clearTimeout(timeoutId)
  }
}

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
  return requestJson<WorkflowRunStatusResponse>(`/workflow-runs/${runId}`)
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
  return requestJson<WorkflowEventsResponse>(`/workflow-runs/${runId}/events${suffix}`)
}

export function getWorkflowRunView(runId: string) {
  return requestJson<WorkflowRunViewResponse>(`/workflow-runs/${runId}/view`)
}

export function getWeatherPoint(params: {
  layer_id: string
  latitude: number
  longitude: number
  model?: string
  forecast_hours?: number
  place_name?: string
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
  return requestJson<WeatherPointResponse>(`/weather/point?${search.toString()}`, {
    signal: params.signal,
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
