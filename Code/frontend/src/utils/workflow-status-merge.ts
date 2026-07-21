import type { WorkflowSummary } from '../stores/layers/types'
import type { WeatherWorkflowContribution } from '../stores/weather-tile-manager'

/** 合并业务 job 摘要与天气瓦片合成态（同口径用于工具栏 / 状态面板） */
export function mergeWorkflowSummaryWithWeather(
  base: WorkflowSummary,
  contribution: WeatherWorkflowContribution,
): WorkflowSummary {
  const running = base.running + contribution.running
  const queued = base.queued + contribution.queued
  const retryPending = base.retryPending + contribution.retryPending
  const failed = base.failed + contribution.failed
  const cancelled = base.cancelled + contribution.cancelled
  const succeeded = base.succeeded + contribution.succeeded
  const weatherCount = contribution.items.length
  const total = base.total + weatherCount

  const active = running + queued + retryPending
  let overall: WorkflowSummary['overall'] = base.overall
  let tone: WorkflowSummary['tone'] = base.tone

  if (total === 0) {
    return {
      total: 0,
      running: 0,
      queued: 0,
      succeeded: 0,
      failed: 0,
      cancelled: 0,
      retryPending: 0,
      overall: 'idle',
      tone: 'idle',
      hasError: false,
    }
  }

  if (active > 0) {
    overall = 'active'
    tone = 'active'
  } else if (failed > 0 && succeeded > 0) {
    overall = 'mixed'
    tone = 'warning'
  } else if (failed > 0) {
    overall = 'failed'
    tone = 'error'
  } else if (succeeded > 0) {
    overall = 'succeeded'
    tone = 'success'
  } else if (cancelled > 0) {
    overall = 'idle'
    tone = 'idle'
  }

  return {
    total,
    running,
    queued,
    succeeded,
    failed,
    cancelled,
    retryPending,
    overall,
    tone,
    hasError: base.hasError || failed > 0,
  }
}
