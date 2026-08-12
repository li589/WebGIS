/**
 * InfoPanel GIS analysis API (thin wrapper over /analysis/*).
 * Types are local until OpenAPI regen picks up Analysis* contracts.
 */
import { requestJson } from './_http'

export interface AnalysisToolParamField {
  key: string
  type: string
  title: string
  description?: string | null
  default?: unknown
  min?: number | null
  max?: number | null
  unit?: string | null
  options?: string[] | null
}

export interface AnalysisToolDescriptor {
  tool_id: string
  title: string
  description: string
  category: string
  input_kinds: string[]
  param_schema: AnalysisToolParamField[]
  workflow_template_id: string
  outputs: string[]
  resource_profile: string
  concurrency_key: string
  enabled: boolean
  disabled_reason?: string | null
}

export interface AnalysisToolListResponse {
  layer_id?: string | null
  layer_kind: string
  items: AnalysisToolDescriptor[]
}

export interface AnalysisRunRequestBody {
  tool_id: string
  layer_id: string
  overlay_layer_id?: string | null
  zones_overlay_layer_id?: string | null
  zones_geojson_path?: string | null
  geojson_path?: string | null
  map_point?: { lng: number; lat: number } | null
  bbox?: { west: number; south: number; east: number; north: number; crs?: string } | null
  params?: Record<string, unknown>
  show_on_map?: boolean
}

export interface AnalysisAcceptedResponse {
  run_id: string
  status: string
  status_url: string
  events_url: string
  created_at: string
  message: string
}

export function fetchAnalysisTools(query: {
  layer_id?: string
  source_type?: string
  overlay_layer_id?: string
  has_vector?: boolean
  has_raster?: boolean
  is_weather?: boolean
  is_point_only?: boolean
}) {
  const params = new URLSearchParams()
  if (query.layer_id) params.set('layer_id', query.layer_id)
  if (query.source_type) params.set('source_type', query.source_type)
  if (query.overlay_layer_id) params.set('overlay_layer_id', query.overlay_layer_id)
  if (query.has_vector) params.set('has_vector', 'true')
  if (query.has_raster) params.set('has_raster', 'true')
  if (query.is_weather) params.set('is_weather', 'true')
  if (query.is_point_only) params.set('is_point_only', 'true')
  const qs = params.toString()
  return requestJson<AnalysisToolListResponse>(`/analysis/tools${qs ? `?${qs}` : ''}`, {
    silent: true,
  })
}

export function submitAnalysisRun(body: AnalysisRunRequestBody) {
  return requestJson<AnalysisAcceptedResponse>('/analysis/runs', {
    method: 'POST',
    body: JSON.stringify(body),
    timeoutMs: 120000,
  })
}
