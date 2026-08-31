import { getWorkflowRunView, resolveApiUrl } from '../../services/runtime-api'
import type {
  WeatherLayerRenderHint,
  WorkflowResultReference,
  WorkflowRunStatusResponse,
  WorkflowRunViewResponse,
} from '../../services/runtime-api'
import type { JobLayerItem, JobLayerMapLayerPayload } from './types'
import type { ActiveLayer, ActiveLayerDisplay, RuntimeLayerLibraryItem } from './types'
import { mergeProductTag } from './layer-naming'
import { asRecord, extractLayerHotspots, formatClockLabel } from './catalog-builders'
import {
  extractFailureCategory,
  extractWorkflowTechLogs,
  localizeWorkflowDiagnostics,
  localizeWorkflowErrorMessage,
} from '../../utils/workflow-error-messages'
import { resolveJobLayerDisplayName } from '../../utils/workflow-run-display-name'

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

/** 工作流内部 entry id 不得泄漏到图层库运行条目名。 */
function isTechnicalWorkflowEntryName(name: string | undefined): boolean {
  if (!name) return false
  return /^(?:omega[-_]sf[-_]fenkuai|omega[-_]avg[-_]daily|static_local_read|analysis_|preprocess_|fusion_|stats_)/i.test(
    name,
  )
}

function extractReportSummary(
  resultRefs: WorkflowResultReference[] | undefined,
  fallbackMessage: string,
) {
  const textResult = resultRefs?.find((item) => item.result_kind === 'text')
  const textPayload = asRecord(textResult?.inline_data)
  const text = textPayload?.text
  return typeof text === 'string' && text.trim() ? text : fallbackMessage
}

function asNumberOrNull(value: unknown): number | null {
  if (typeof value === 'number' && Number.isFinite(value)) return value
  if (typeof value === 'string' && value.trim() && Number.isFinite(Number(value))) {
    return Number(value)
  }
  return null
}

async function fetchChunkItems(
  resourceUrl: string,
): Promise<Array<{ label?: unknown; value?: unknown }>> {
  try {
    const url = resolveApiUrl(resourceUrl)
    const resp = await fetch(url)
    if (!resp.ok) return []
    const body = (await resp.json()) as { items?: unknown }
    if (!Array.isArray(body.items)) return []
    return body.items.filter((item): item is { label?: unknown; value?: unknown } => {
      return item !== null && typeof item === 'object'
    })
  } catch {
    return []
  }
}

async function extractAnalysisCharts(resultRefs: WorkflowResultReference[] | undefined) {
  const charts: NonNullable<JobLayerItem['analysisCharts']> = []
  for (const item of resultRefs ?? []) {
    if (item.result_kind !== 'chart') continue
    const payload = asRecord(item.inline_data)
    if (!payload) continue

    // Chunked manifests: assemble series from stored chunk items
    if (payload.chunked === true && Array.isArray(payload.chunks)) {
      const xs: Array<string | number> = []
      const ys: Array<number | null> = []
      for (const chunk of payload.chunks) {
        const rec = asRecord(chunk)
        const url = typeof rec?.resource_url === 'string' ? rec.resource_url : ''
        if (!url) continue
        const items = await fetchChunkItems(url)
        for (const row of items) {
          const label = row.label
          xs.push(typeof label === 'string' || typeof label === 'number' ? label : xs.length)
          ys.push(asNumberOrNull(row.value))
        }
      }
      if (!xs.length && !ys.length) continue
      charts.push({
        id: item.result_id,
        title: item.title || String(payload.title || 'Chart'),
        chartType: String(payload.chart_type || 'line'),
        xLabel: String(payload.x_label || ''),
        yLabel: String(payload.y_label || ''),
        unit: String(payload.unit || ''),
        series: [
          {
            name: typeof payload.series_name === 'string' ? payload.series_name : 'series',
            x: xs,
            y: ys,
          },
        ],
      })
      continue
    }

    const seriesRaw = Array.isArray(payload.series) ? payload.series : null
    let series: Array<{ name: string; x: Array<string | number>; y: Array<number | null> }> = []
    if (seriesRaw && seriesRaw.length) {
      series = seriesRaw
        .map((s) => {
          const rec = asRecord(s)
          if (!rec) return null
          const x = Array.isArray(rec.x) ? (rec.x as Array<string | number>) : []
          const y = Array.isArray(rec.y) ? (rec.y as unknown[]).map((v) => asNumberOrNull(v)) : []
          return {
            name: typeof rec.name === 'string' ? rec.name : 'series',
            x,
            y,
          }
        })
        .filter((s): s is NonNullable<typeof s> => s !== null)
    } else {
      const x = Array.isArray(payload.x) ? (payload.x as Array<string | number>) : []
      const y = Array.isArray(payload.y)
        ? (payload.y as unknown[]).map((v) => asNumberOrNull(v))
        : []
      if (x.length || y.length) {
        series = [
          {
            name: typeof payload.series_name === 'string' ? payload.series_name : 'series',
            x,
            y,
          },
        ]
      }
    }
    if (!series.length) continue
    charts.push({
      id: item.result_id,
      title: item.title || String(payload.title || 'Chart'),
      chartType: String(payload.chart_type || 'line'),
      xLabel: String(payload.x_label || ''),
      yLabel: String(payload.y_label || ''),
      unit: String(payload.unit || ''),
      series,
    })
  }
  return charts
}

function extractAnalysisTables(resultRefs: WorkflowResultReference[] | undefined) {
  const tables: NonNullable<JobLayerItem['analysisTables']> = []
  for (const item of resultRefs ?? []) {
    if (item.result_kind !== 'table') continue
    const payload = asRecord(item.inline_data)
    if (!payload) continue
    const columns = Array.isArray(payload.columns)
      ? (payload.columns as unknown[]).map((c) => String(c))
      : []
    const rows = Array.isArray(payload.rows) ? (payload.rows as unknown[][]) : []
    if (!columns.length && !rows.length) continue
    tables.push({
      id: item.result_id,
      title: item.title || String(payload.title || 'Table'),
      columns,
      rows,
    })
  }
  return tables
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
    notes.push(localizeWorkflowErrorMessage(errorMessage))
  }
  return notes
}

function extractMapLayerPayload(
  resultRefs: WorkflowResultReference[] | undefined,
): JobLayerMapLayerPayload | undefined {
  const mapLayerResults = (resultRefs ?? []).filter((item) => item.result_kind === 'map_layer')
  if (!mapLayerResults.length) return undefined

  // Prefer a ref that already carries paintable assets (COG / overlay).
  const preferred =
    mapLayerResults.find((item) => {
      const payload = asRecord(item.inline_data)
      const assets = asRecord(payload?.layer_assets)
      return Boolean(
        assets?.cog_preview_url ||
        assets?.cog_url ||
        assets?.geojson_url ||
        assets?.overlay_layer_id,
      )
    }) ?? mapLayerResults[0]

  const payload = asRecord(preferred.inline_data)
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
          geojsonUrl:
            typeof layerAssets.geojson_url === 'string' ? layerAssets.geojson_url : undefined,
          cogUrl: typeof layerAssets.cog_url === 'string' ? layerAssets.cog_url : undefined,
          cogPreviewUrl:
            typeof layerAssets.cog_preview_url === 'string'
              ? layerAssets.cog_preview_url
              : undefined,
          overlayLayerId:
            typeof layerAssets.overlay_layer_id === 'string'
              ? layerAssets.overlay_layer_id
              : undefined,
          productTag:
            typeof layerAssets.product_tag === 'string' ? layerAssets.product_tag : undefined,
          cogBbox:
            asRecord(layerAssets.cog_bbox) &&
            typeof asRecord(layerAssets.cog_bbox)?.west === 'number'
              ? {
                  west: Number(asRecord(layerAssets.cog_bbox)?.west),
                  south: Number(asRecord(layerAssets.cog_bbox)?.south),
                  east: Number(asRecord(layerAssets.cog_bbox)?.east),
                  north: Number(asRecord(layerAssets.cog_bbox)?.north),
                  crs:
                    typeof asRecord(layerAssets.cog_bbox)?.crs === 'string'
                      ? String(asRecord(layerAssets.cog_bbox)?.crs)
                      : undefined,
                }
              : undefined,
        }
      : undefined,
  }
}

/** Collect imported-overlay map layers emitted by algorithm workflows. */
export function extractOverlayImportsFromResultRefs(
  resultRefs: WorkflowResultReference[] | undefined,
): Array<{
  overlayLayerId: string
  title: string
  productTag?: string
  bounds?: [number, number, number, number]
  sourceCrs?: string
}> {
  const out: Array<{
    overlayLayerId: string
    title: string
    productTag?: string
    bounds?: [number, number, number, number]
    sourceCrs?: string
  }> = []
  for (const item of resultRefs ?? []) {
    if (item.result_kind !== 'map_layer') continue
    const payload = asRecord(item.inline_data)
    const assets = asRecord(payload?.layer_assets)
    const overlayId =
      typeof assets?.overlay_layer_id === 'string' ? assets.overlay_layer_id.trim() : ''
    if (!overlayId) continue
    const bbox = asRecord(assets?.cog_bbox)
    const bounds =
      bbox &&
      typeof bbox.west === 'number' &&
      typeof bbox.south === 'number' &&
      typeof bbox.east === 'number' &&
      typeof bbox.north === 'number'
        ? ([Number(bbox.west), Number(bbox.south), Number(bbox.east), Number(bbox.north)] as [
            number,
            number,
            number,
            number,
          ])
        : undefined
    out.push({
      overlayLayerId: overlayId,
      title: item.title || overlayId,
      productTag: typeof assets?.product_tag === 'string' ? assets.product_tag : undefined,
      bounds,
      sourceCrs: typeof bbox?.crs === 'string' ? bbox.crs : undefined,
    })
  }
  return out
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
    return payload && typeof payload === 'object' ? (payload as Record<string, unknown>) : undefined
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
  const rawDiagnostics = run.diagnostics ?? []
  const diagnosticNotes = [
    ...extractDiagnosticNotes(run),
    ...localizeWorkflowDiagnostics(
      rawDiagnostics.filter(
        (item) =>
          typeof item === 'string' &&
          item.trim() &&
          !item.startsWith('validation_') &&
          !item.startsWith('error_message=') &&
          !item.startsWith('reason=') && // 与主 message 重复
          !item.startsWith('bake_log='),
      ),
    ),
  ].filter((note, index, arr) => {
    if (!note) return false
    // 勿与主消息重复
    if (run.message && note === run.message.trim()) return false
    return arr.indexOf(note) === index
  })
  const techLogs = extractWorkflowTechLogs(rawDiagnostics)
  const previousJobLayer = options.previousJobLayer
  const resultView: WorkflowRunViewResponse | null = shouldFetchWorkflowRunView(run)
    ? await getWorkflowRunView(run.run_id).catch(() => previousJobLayer?.resultView ?? null)
    : (previousJobLayer?.resultView ?? null)
  const resultUrl =
    resultView?.result_url ?? previousJobLayer?.resultUrl ?? extractResultUrl(run.result_refs)
  const reportSummary =
    resultView?.summary ??
    previousJobLayer?.reportSummary ??
    extractReportSummary(run.result_refs, diagnosticNotes[0] ?? run.message)
  const mapLayerPayload =
    extractMapLayerPayload(run.result_refs) ?? previousJobLayer?.mapLayerPayload
  if (mapLayerPayload?.layerAssets?.geojsonUrl && !mapLayerPayload.layerAssets.geojsonData) {
    const geojsonData = await fetchGeojsonData(mapLayerPayload.layerAssets.geojsonUrl)
    if (geojsonData) {
      mapLayerPayload.layerAssets = {
        ...mapLayerPayload.layerAssets,
        geojsonData,
      }
    }
  }
  const localizedMessage = localizeWorkflowErrorMessage(run.message)
  const failureCategory = extractFailureCategory({
    diagnostics: rawDiagnostics,
    message: run.message,
  })
  const analysisCharts = await extractAnalysisCharts(run.result_refs)
  const analysisTables = extractAnalysisTables(run.result_refs)
  return {
    jobId: run.run_id,
    name: resolveJobLayerDisplayName(run, catalogName, {
      previousName: previousJobLayer?.name,
      entryName,
    }),
    commandType: run.command_type,
    commandLabel: run.command_label ?? undefined,
    status,
    progress: run.progress,
    createdAt: run.created_at,
    updatedAt: run.updated_at,
    message: localizedMessage,
    metrics: extractMetrics(run),
    reportSummary,
    resultDto: run.result_dto ?? undefined,
    resultView: resultView ?? undefined,
    resultUrl: resultUrl ?? undefined,
    analysisCharts: analysisCharts.length > 0 ? analysisCharts : previousJobLayer?.analysisCharts,
    analysisTables: analysisTables.length > 0 ? analysisTables : previousJobLayer?.analysisTables,
    mapLayerPayload,
    diagnostics: run.diagnostics ?? [],
    diagnosticNotes,
    techLogs: techLogs.length ? techLogs : previousJobLayer?.techLogs,
    failureCategory: failureCategory ?? previousJobLayer?.failureCategory,
    retryOfRunId:
      typeof run.executor_metadata?.retry_of_run_id === 'string'
        ? run.executor_metadata.retry_of_run_id
        : undefined,
    expectedTimeRange: previousJobLayer?.expectedTimeRange,
    expectedNativeStep: previousJobLayer?.expectedNativeStep,
    inFlightTimeKeys: previousJobLayer?.inFlightTimeKeys,
    failedTimeKeys: previousJobLayer?.failedTimeKeys,
    progressiveOverlayCount: previousJobLayer?.progressiveOverlayCount,
    progressiveOverlayError: previousJobLayer?.progressiveOverlayError,
    progressiveOverlayAt: previousJobLayer?.progressiveOverlayAt,
    catalogId: previousJobLayer?.catalogId,
  }
}

/** 产品标签归一：查表归并（OMEGA_BLOCK/PIXEL→OMEGA 等，规则见
 * layer-naming.PRODUCT_TAG_MERGE_RULES——P2-A 表化，2026-08-24） */
export function normalizeProductTag(raw: string | null | undefined): string {
  const tag = String(raw || '')
    .trim()
    .toUpperCase()
    // R4：技术前缀剥两类——map_layer 产物（Algorithm Map Layer）与 file 产物（Algorithm Output），
    // 否则未识别 title 会作为 tag 原样泄漏成图层名（productTagLabel 未知 tag 透传）
    .replace(/^ALGORITHM (?:MAP LAYER|OUTPUT):\s*/i, '')
  if (!tag) return ''
  return mergeProductTag(tag)
}

/** 从 jobLayer 提取真实数据显示数据 */
export function buildRealLayerDisplay(
  layer: ActiveLayer,
  item: RuntimeLayerLibraryItem,
): Partial<ActiveLayerDisplay> {
  const jobLayer = layer.jobLayer
  if (!jobLayer) return {}

  const primaryMetric = jobLayer.metrics?.find((m) => m.label !== '队列')
  const metricValue = primaryMetric?.value ?? '--'
  const renderHint = jobLayer.mapLayerPayload?.renderHint
  const resultDto = asRecord(jobLayer.resultDto)
  const providerKey = typeof resultDto?.provider_key === 'string' ? resultDto.provider_key : null
  const resultCategory =
    typeof resultDto?.result_category === 'string' ? resultDto.result_category : null
  const providerSummary = typeof resultDto?.summary === 'string' ? resultDto.summary : null
  const providerStatusLabel =
    typeof resultDto?.status_label === 'string' ? resultDto.status_label : null
  const providerConfidenceLabel =
    typeof resultDto?.confidence_label === 'string' ? resultDto.confidence_label : null
  const isSampleProvider =
    item.backendStatus === 'sample' ||
    (resultCategory === 'provider' && providerKey?.startsWith('lab_output'))
  let confidenceLabel = '以工作流结果为准'
  if (renderHint?.notes?.length) {
    confidenceLabel = renderHint.notes[0]
  } else if (providerConfidenceLabel) {
    confidenceLabel = providerConfidenceLabel
  } else if (jobLayer.diagnosticNotes?.length) {
    confidenceLabel = jobLayer.diagnosticNotes[0]
  }

  return {
    metricValue,
    summary:
      providerSummary ??
      jobLayer.resultView?.summary ??
      jobLayer.reportSummary ??
      jobLayer.message ??
      item.description,
    statusLabel:
      jobLayer.status === 'succeeded'
        ? isSampleProvider
          ? (providerStatusLabel ?? '实验结果')
          : '真实数据'
        : jobLayer.status === 'failed'
          ? '数据异常'
          : jobLayer.status === 'cancelled'
            ? '任务已取消'
            : '任务处理中',
    trendLabel:
      jobLayer.status === 'succeeded'
        ? isSampleProvider
          ? '实验 provider 已执行，可用于联调验收'
          : '最新工作流结果已接入'
        : jobLayer.status === 'failed'
          ? '最近一次运行失败'
          : '等待工作流返回结果',
    sourceLabel:
      isSampleProvider && providerKey ? `实验 Provider · ${providerKey}` : item.sourceLabel,
    confidenceLabel,
    availabilityState:
      jobLayer.status === 'succeeded'
        ? 'ready'
        : jobLayer.status === 'failed'
          ? 'empty'
          : 'partial',
    availabilityLabel:
      jobLayer.status === 'succeeded'
        ? '完整数据'
        : jobLayer.status === 'failed'
          ? '数据异常'
          : '加载中',
    availabilityDescription:
      jobLayer.status === 'succeeded'
        ? isSampleProvider
          ? '实验 provider 已生成结果，可用于联调与界面验收。'
          : jobLayer.message || '工作流结果已生成。'
        : jobLayer.status === 'failed'
          ? (jobLayer.diagnosticNotes?.[0] ?? '数据加载失败')
          : jobLayer.message || '正在加载工作流结果...',
    observationTimeLabel:
      jobLayer.reportSummary?.match(/\d{2}:\d{2}/)?.[0] ?? formatClockLabel(jobLayer.updatedAt),
    missingFieldsLabel:
      jobLayer.status === 'succeeded'
        ? '无缺失字段'
        : (jobLayer.diagnosticNotes?.join(' / ') ?? '待加载'),
    hotspots: extractLayerHotspots(layer, item, metricValue),
  }
}
