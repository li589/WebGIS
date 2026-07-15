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
