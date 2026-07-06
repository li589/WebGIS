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
export type RuntimeConfigScope = 'frontend' | 'backend' | 'provider' | 'workflow' | 'system'
export type FrontendCommandType = 'preload' | 'clear_cache' | 'cleanup' | 'cancel_run' | 'reload_catalog' | 'custom'
export type ServiceHealth = 'ok' | 'busy' | 'degraded' | 'offline'

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

export interface WorkflowEvent {
  event_id: string
  run_id: string
  channel: EventChannel
  level: 'debug' | 'info' | 'warning' | 'error'
  message: string
  created_at: string
  progress?: number
  payload: Record<string, unknown>
}

export interface WorkflowEventsResponse {
  run_id: string
  items: WorkflowEvent[]
}

export interface RuntimeConfigPatch {
  scope: RuntimeConfigScope
  key: string
  value: unknown
  description?: string
}

export interface RuntimeConfigUpdateRequest {
  items: RuntimeConfigPatch[]
  client?: ClientIdentity
}

export interface RuntimeConfigUpdateResponse {
  accepted: boolean
  updated_at: string
  applied_count: number
  message: string
  config_snapshot: Record<string, Record<string, unknown>>
}

export interface BackendServiceStatus {
  service_name: string
  health: ServiceHealth
  message: string
  updated_at: string
  details: Record<string, unknown>
}

export interface RuntimeStatusResponse {
  overall_health: ServiceHealth
  service_name: string
  environment: string
  updated_at: string
  active_run_count: number
  config_snapshot: Record<string, Record<string, unknown>>
  services: BackendServiceStatus[]
}

export interface FrontendCommandRequest {
  command_type: FrontendCommandType
  target?: string
  payload?: Record<string, unknown>
  client?: ClientIdentity
  correlation_id?: string
}

export interface FrontendCommandResponse {
  accepted: boolean
  command_type: FrontendCommandType
  target?: string
  created_at: string
  message: string
  next_action?: string
}

function getApiBaseUrl() {
  return import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, '') ?? 'http://127.0.0.1:8000'
}

export function resolveApiUrl(pathOrUrl: string) {
  if (/^https?:\/\//i.test(pathOrUrl)) return pathOrUrl
  const normalizedPath = pathOrUrl.startsWith('/') ? pathOrUrl : `/${pathOrUrl}`
  return `${getApiBaseUrl()}${normalizedPath}`
}

async function requestJson<T>(path: string, init?: RequestInit & { timeoutMs?: number }): Promise<T> {
  // 修复：headers 合并顺序错误。原代码先构造 headers 再展开 ...init，
  // 导致 init.headers 整体替换而非合并。改为先提取 headers 单独合并。
  const { headers: initHeaders, timeoutMs, ...restInit } = init ?? {}
  const mergedHeaders: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(initHeaders as Record<string, string> | undefined),
  }

  // 修复：添加超时控制，避免请求挂起
  const controller = new AbortController()
  const timeoutId = window.setTimeout(
    () => controller.abort(),
    timeoutMs ?? 30000,
  )

  try {
    const response = await fetch(resolveApiUrl(path), {
      ...restInit,
      headers: mergedHeaders,
      signal: restInit.signal ?? controller.signal,
    })

    if (!response.ok) {
      // 修复：解析结构化错误体，而非丢弃
      let errorDetail = ''
      try {
        const errorBody = await response.json()
        errorDetail = errorBody?.user_message || errorBody?.error || errorBody?.detail || JSON.stringify(errorBody)
      } catch {
        errorDetail = await response.text().catch(() => '')
      }
      throw new Error(`Request failed: ${response.status} ${path}${errorDetail ? ` - ${errorDetail}` : ''}`)
    }

    return (await response.json()) as T
  } finally {
    window.clearTimeout(timeoutId)
  }
}

export function submitWorkflow(payload: WorkflowSubmitRequest) {
  return requestJson<WorkflowAcceptedResponse>('/workflow-runs', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function fetchLayerCatalog() {
  return requestJson<RuntimeLayerCatalogResponse>('/layers')
}

export function getWorkflowRun(runId: string) {
  return requestJson<WorkflowRunStatusResponse>(`/workflow-runs/${runId}`)
}

export function getWorkflowRunView(runId: string) {
  return requestJson<WorkflowRunViewResponse>(`/workflow-runs/${runId}/view`)
}

export function listWorkflowEvents(runId: string) {
  return requestJson<WorkflowEventsResponse>(`/workflow-runs/${runId}/events`)
}

export function updateRuntimeConfig(payload: RuntimeConfigUpdateRequest) {
  return requestJson<RuntimeConfigUpdateResponse>('/runtime/config', {
    method: 'PATCH',
    body: JSON.stringify(payload),
  })
}

export function getRuntimeStatus() {
  return requestJson<RuntimeStatusResponse>('/runtime/status')
}

export function getWeatherPoint(params: {
  layer_id: string
  latitude: number
  longitude: number
  model?: string
  forecast_hours?: number
  place_name?: string
}) {
  const search = new URLSearchParams({
    layer_id: params.layer_id,
    latitude: String(params.latitude),
    longitude: String(params.longitude),
  })
  if (params.model) search.set('model', params.model)
  if (typeof params.forecast_hours === 'number') search.set('forecast_hours', String(params.forecast_hours))
  if (params.place_name) search.set('place_name', params.place_name)
  return requestJson<WeatherPointResponse>(`/weather/point?${search.toString()}`)
}

export function submitFrontendCommand(payload: FrontendCommandRequest) {
  return requestJson<FrontendCommandResponse>('/frontend/commands', {
    method: 'POST',
    body: JSON.stringify(payload),
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
