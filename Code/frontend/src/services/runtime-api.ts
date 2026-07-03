export type ExecutionStatus =
  | 'accepted'
  | 'queued'
  | 'running'
  | 'succeeded'
  | 'failed'
  | 'cancelled'

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
  spatial_filter?: SpatialFilter
  time_range?: TimeRange
  parameters?: Record<string, unknown>
  config_overrides?: Record<string, unknown>
  requested_outputs?: Array<ResultKind | string>
  client?: ClientIdentity
  map_context?: RuntimeMapContext
  correlation_id?: string
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

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${getApiBaseUrl()}${path}`, {
    headers: {
      'Content-Type': 'application/json',
      ...(init?.headers ?? {}),
    },
    ...init,
  })

  if (!response.ok) {
    throw new Error(`Request failed: ${response.status} ${path}`)
  }

  return (await response.json()) as T
}

export function submitWorkflow(payload: WorkflowSubmitRequest) {
  return requestJson<WorkflowAcceptedResponse>('/workflow-runs', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
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
