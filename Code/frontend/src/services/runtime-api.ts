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
