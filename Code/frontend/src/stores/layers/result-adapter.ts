import { getWorkflowRunView, resolveApiUrl } from '../../services/runtime-api'
import type { WeatherLayerRenderHint, WorkflowResultReference, WorkflowRunStatusResponse, WorkflowRunViewResponse } from '../../services/runtime-api'
import type { JobLayerItem, JobLayerMapLayerPayload } from './types'

function asRecord(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === 'object' ? (value as Record<string, unknown>) : null
}

function formatMetricValue(value: unknown, unit = '') {
  if (typeof value === 'number') {
    return `${Number.isInteger(value) ? value : value.toFixed(2)}${unit}`
  }
  if (typeof value === 'string') {
    return `${value}${unit}`
  }
  return unit ? `--${unit}` : '--'
}

function extractResultUrl(resultRefs: WorkflowResultReference[] | undefined) {
  return resultRefs?.find((item) => item.resource_url)?.resource_url ?? undefined
}

function extractWorkflowEntryName(run: WorkflowRunStatusResponse) {
  const dto = run.result_dto
  const entryName = dto && typeof dto === 'object' ? dto.workflow_entry_name : undefined
  return typeof entryName === 'string' && entryName.trim() ? entryName : undefined
}

function extractReportSummary(resultRefs: WorkflowResultReference[] | undefined, fallbackMessage: string) {
  const textResult = resultRefs?.find((item) => item.result_kind === 'text')
  const textPayload = asRecord(textResult?.inline_data)
  const text = textPayload?.text
  return typeof text === 'string' && text.trim() ? text : fallbackMessage
}

function extractMetrics(run: WorkflowRunStatusResponse) {
  const metrics: Array<{ label: string; value: string }> = []
  const jsonResult = run.result_refs?.find((item) => item.result_kind === 'json')
  const jsonPayload = asRecord(jsonResult?.inline_data)
  const analysis = asRecord(jsonPayload?.analysis)

  if (analysis) {
    metrics.push({
      label: String(analysis.metric_label ?? '核心指标'),
      value: formatMetricValue(analysis.metric_value, String(analysis.metric_unit ?? '')),
    })
    if (typeof analysis.hotspot_count === 'number') {
      metrics.push({
        label: '热点数',
        value: String(analysis.hotspot_count),
      })
    }
  }

  const queueName = run.executor_metadata?.queue_name
  if (typeof queueName === 'string' && queueName.trim()) {
    metrics.push({
      label: '队列',
      value: queueName,
    })
  }

  return metrics
}

function extractDiagnosticNotes(run: WorkflowRunStatusResponse) {
  const missingDatasets: string[] = []
  const candidateSources = new Map<string, string[]>()
  let layerStatus: string | undefined
  let errorMessage: string | undefined

  for (const item of run.diagnostics ?? []) {
    if (typeof item !== 'string' || !item.trim()) continue
    if (item.startsWith('validation_layer_status=')) {
      layerStatus = item.slice('validation_layer_status='.length)
      continue
    }
    if (item.startsWith('validation_dataset_missing=')) {
      missingDatasets.push(item.slice('validation_dataset_missing='.length))
      continue
    }
    if (item.startsWith('validation_dataset_candidates.')) {
      const separatorIndex = item.indexOf('=')
      if (separatorIndex > 0) {
        const key = item.slice('validation_dataset_candidates.'.length, separatorIndex)
        const values = item
          .slice(separatorIndex + 1)
          .split('|')
          .map((value) => value.trim())
          .filter(Boolean)
        if (values.length) candidateSources.set(key, values)
      }
      continue
    }
    if (!errorMessage && item.startsWith('error_message=')) {
      errorMessage = item.slice('error_message='.length)
    }
  }

  const notes: string[] = []
  if (missingDatasets.length) {
    notes.push(`缺少默认数据集：${missingDatasets.join('、')}`)
    for (const datasetName of missingDatasets) {
      const candidates = candidateSources.get(datasetName)
      if (candidates?.length) {
        notes.push(`${datasetName} 候选源：${candidates.join(' / ')}`)
      }
    }
  }
  if (layerStatus === 'placeholder') {
    notes.push('图层仍处于占位状态，默认数据源尚未接入')
  } else if (layerStatus) {
    notes.push(`图层状态：${layerStatus}`)
  }
  if (!notes.length && errorMessage) {
    notes.push(errorMessage)
  }
  return notes
}

function extractMapLayerPayload(resultRefs: WorkflowResultReference[] | undefined): JobLayerMapLayerPayload | undefined {
  const mapLayerResult = resultRefs?.find((item) => item.result_kind === 'map_layer')
  const payload = asRecord(mapLayerResult?.inline_data)
  if (!payload) {
    return undefined
  }
  const layerAssets = asRecord(payload.layer_assets)
  const renderHint = asRecord(payload.render_hint) as WeatherLayerRenderHint | null
  return {
    renderHint: renderHint ?? undefined,
    pointFeature: asRecord(payload.point_feature) ?? undefined,
    layerAssets: layerAssets
      ? {
          geojsonUrl: typeof layerAssets.geojson_url === 'string' ? layerAssets.geojson_url : undefined,
          cogUrl: typeof layerAssets.cog_url === 'string' ? layerAssets.cog_url : undefined,
          cogPreviewUrl: typeof layerAssets.cog_preview_url === 'string' ? layerAssets.cog_preview_url : undefined,
          cogBbox:
            asRecord(layerAssets.cog_bbox) && typeof asRecord(layerAssets.cog_bbox)?.west === 'number'
              ? {
                  west: Number(asRecord(layerAssets.cog_bbox)?.west),
                  south: Number(asRecord(layerAssets.cog_bbox)?.south),
                  east: Number(asRecord(layerAssets.cog_bbox)?.east),
                  north: Number(asRecord(layerAssets.cog_bbox)?.north),
                  crs: typeof asRecord(layerAssets.cog_bbox)?.crs === 'string' ? String(asRecord(layerAssets.cog_bbox)?.crs) : undefined,
                }
              : undefined,
        }
      : undefined,
  }
}

async function fetchGeojsonData(geojsonUrl: string): Promise<Record<string, unknown> | undefined> {
  const controller = new AbortController()
  const timeoutId = window.setTimeout(() => controller.abort(), 20000)
  try {
    const response = await fetch(resolveApiUrl(geojsonUrl), {
      signal: controller.signal,
    })
    if (!response.ok) return undefined
    const payload = await response.json()
    return payload && typeof payload === 'object' ? payload as Record<string, unknown> : undefined
  } catch {
    return undefined
  } finally {
    window.clearTimeout(timeoutId)
  }
}

function shouldFetchWorkflowRunView(run: WorkflowRunStatusResponse) {
  return run.status === 'succeeded' || run.status === 'failed' || run.status === 'cancelled'
}

interface BuildJobLayerOptions {
  previousJobLayer?: JobLayerItem
}

export async function buildJobLayer(
  run: WorkflowRunStatusResponse,
  catalogName: string,
  options: BuildJobLayerOptions = {},
): Promise<JobLayerItem> {
  const status = run.status === 'accepted' ? 'queued' : run.status
  const entryName = extractWorkflowEntryName(run)
  const diagnosticNotes = extractDiagnosticNotes(run)
  const previousJobLayer = options.previousJobLayer
  const resultView: WorkflowRunViewResponse | null = shouldFetchWorkflowRunView(run)
    ? await getWorkflowRunView(run.run_id).catch(() => previousJobLayer?.resultView ?? null)
    : (previousJobLayer?.resultView ?? null)
  const resultUrl = resultView?.result_url ?? previousJobLayer?.resultUrl ?? extractResultUrl(run.result_refs)
  const reportSummary =
    resultView?.summary ?? previousJobLayer?.reportSummary ?? extractReportSummary(run.result_refs, diagnosticNotes[0] ?? run.message)
  const mapLayerPayload = extractMapLayerPayload(run.result_refs) ?? previousJobLayer?.mapLayerPayload
  if (mapLayerPayload?.layerAssets?.geojsonUrl && !mapLayerPayload.layerAssets.geojsonData) {
    const geojsonData = await fetchGeojsonData(mapLayerPayload.layerAssets.geojsonUrl)
    if (geojsonData) {
      mapLayerPayload.layerAssets = {
        ...mapLayerPayload.layerAssets,
        geojsonData,
      }
    }
  }
  return {
    jobId: run.run_id,
    name: entryName ?? catalogName,
    commandType: run.command_type,
    status,
    progress: run.progress,
    createdAt: run.created_at,
    updatedAt: run.updated_at,
    message: run.message,
    metrics: extractMetrics(run),
    reportSummary,
    resultDto: run.result_dto ?? undefined,
    resultView: resultView ?? undefined,
    resultUrl: resultUrl ?? undefined,
    mapLayerPayload,
    diagnostics: run.diagnostics ?? [],
    diagnosticNotes,
  }
}
