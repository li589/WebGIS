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
import { withWriteAuthHeaders } from './backend-auth'
import { useUiLoadingStore } from '../stores/ui-loading'

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

async function requestJson<T>(path: string, init?: RequestInit & { timeoutMs?: number; silent?: boolean }): Promise<T> {
  const { headers: initHeaders, timeoutMs, silent, ...restInit } = init ?? {}
  const method = (restInit.method ?? 'GET').toString()
  const mergedHeaders: Record<string, string> = withWriteAuthHeaders(
    {
      'Content-Type': 'application/json',
      ...(initHeaders as Record<string, string> | undefined),
    },
    method,
  )

  const controller = new AbortController()
  const timeoutId = window.setTimeout(
    () => controller.abort(),
    timeoutMs ?? 30000,
  )

  // 全局 loading 管理：非 silent 请求触发 loading 动效
  // 300ms 延迟显示机制确保短请求不闪烁（在 store 内部实现）
  const loading = useUiLoadingStore()
  if (!silent) {
    loading.show()
  }

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

    const body = (await response.json()) as T
    return body
  } finally {
    window.clearTimeout(timeoutId)
    // 对应 try 前的 loading.show()，非 silent 请求完成后隐藏 loading
    if (!silent) {
      loading.hide()
    }
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
