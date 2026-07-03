import { getWorkflowRunView } from '../../services/runtime-api'
import type { WorkflowResultReference, WorkflowRunStatusResponse, WorkflowRunViewResponse } from '../../services/runtime-api'
import type { JobLayerItem } from './types'

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

function extractResultUrl(resultRefs: WorkflowResultReference[]) {
  return resultRefs.find((item) => item.resource_url)?.resource_url
}

function extractWorkflowEntryName(run: WorkflowRunStatusResponse) {
  const dto = run.result_dto
  const entryName = dto && typeof dto === 'object' ? dto.workflow_entry_name : undefined
  return typeof entryName === 'string' && entryName.trim() ? entryName : undefined
}

function extractReportSummary(resultRefs: WorkflowResultReference[], fallbackMessage: string) {
  const textResult = resultRefs.find((item) => item.result_kind === 'text')
  const textPayload = asRecord(textResult?.inline_data)
  const text = textPayload?.text
  return typeof text === 'string' && text.trim() ? text : fallbackMessage
}

function extractMetrics(run: WorkflowRunStatusResponse) {
  const metrics: Array<{ label: string; value: string }> = []
  const jsonResult = run.result_refs.find((item) => item.result_kind === 'json')
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

export async function buildJobLayer(run: WorkflowRunStatusResponse, catalogName: string): Promise<JobLayerItem> {
  const status = run.status === 'accepted' ? 'queued' : run.status
  const entryName = extractWorkflowEntryName(run)
  const resultView: WorkflowRunViewResponse | null = await getWorkflowRunView(run.run_id).catch(() => null)
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
    reportSummary: resultView?.summary ?? extractReportSummary(run.result_refs, run.message),
    resultDto: run.result_dto ?? undefined,
    resultView: resultView ?? undefined,
    resultUrl: resultView?.result_url ?? extractResultUrl(run.result_refs),
  }
}
