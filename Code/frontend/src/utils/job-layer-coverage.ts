/**
 * 工作流 job ↔ 活跃层 / 计算组的覆盖元数据解析（时间轴、提交路径共用）。
 */
import type {
  ActiveLayer,
  ActiveRunLayerGroup,
  JobLayerItem,
  JobStatus,
} from '../stores/layers/types'
import { formatTimeStep, parseTimeStep, type TimeStep } from './temporal-interval'
import {
  coerceExpectedTimeRange,
  resolveExpectedNativeStep,
  type ExpectedTimeRange,
} from './run-timeline-availability'

const ACTIVE_JOB_STATUSES: ReadonlySet<JobStatus> = new Set(['queued', 'running', 'retry_pending'])

export function formatNativeStepValue(
  raw: string | TimeStep | null | undefined,
): string | undefined {
  if (!raw) return undefined
  if (typeof raw === 'string') {
    const s = raw.trim()
    return s || undefined
  }
  return formatTimeStep(raw)
}

/** 为选中层解析关联 JobLayer（含 runGroup.runId 回查） */
export function resolveJobLayerForActiveLayer(
  layer: ActiveLayer | null | undefined,
  jobLayers: readonly JobLayerItem[],
  runGroups: readonly ActiveRunLayerGroup[],
): JobLayerItem | undefined {
  if (!layer) return undefined
  if (layer.jobLayer) return layer.jobLayer
  const byCatalog = jobLayers.find((j) => j.catalogId && j.catalogId === layer.catalogId)
  if (byCatalog) return byCatalog
  if (!layer.runGroupId) return undefined
  const group = runGroups.find((g) => g.groupId === layer.runGroupId)
  if (!group?.runId) return undefined
  return jobLayers.find((j) => j.jobId === group.runId)
}

export function resolveRunGroupForActiveLayer(
  layer: ActiveLayer | null | undefined,
  runGroups: readonly ActiveRunLayerGroup[],
): ActiveRunLayerGroup | undefined {
  if (!layer?.runGroupId) return undefined
  return runGroups.find((g) => g.groupId === layer.runGroupId)
}

export function isJobActivelyRunning(job: JobLayerItem | undefined): boolean {
  return Boolean(job && ACTIVE_JOB_STATUSES.has(job.status))
}

/** 是否应用「预期覆盖」时间轴（运行中 / 失败 / 已有部分产物） */
export function shouldUseExpectedTimelineAxis(options: {
  expected?: ExpectedTimeRange | null
  job?: JobLayerItem
  runGroup?: ActiveRunLayerGroup
  readyTimeCount: number
}): boolean {
  if (!options.expected) return false
  if (isJobActivelyRunning(options.job) || options.runGroup?.status === 'computing') return true
  if (options.job?.status === 'failed' || options.runGroup?.status === 'failed') return true
  return options.readyTimeCount > 0
}

export function resolveTimelineNativeStep(options: {
  job?: JobLayerItem
  layer?: ActiveLayer | null
  fallback?: string
}): string {
  return (
    options.job?.expectedNativeStep ||
    formatNativeStepValue(options.layer?.importedRaster?.nativeStep) ||
    options.fallback ||
    '1d'
  )
}

/** 从提交 options / 已构建 payload 汇总预期覆盖，供 jobLayer 写入 */
export function buildExpectedCoverageForSubmit(options: {
  timeRange?: Record<string, unknown> | null
  payloadTimeRange?: Record<string, unknown> | null
  algorithmParams?: Record<string, unknown> | null
  catalogNativeStep?: string | null
  workflowId?: string | null
  previous?: Pick<JobLayerItem, 'expectedTimeRange' | 'expectedNativeStep'> | null
}): {
  expectedTimeRange?: ExpectedTimeRange
  expectedNativeStep: string
} {
  const expectedTimeRange =
    coerceExpectedTimeRange(options.timeRange) ||
    coerceExpectedTimeRange(options.payloadTimeRange) ||
    options.previous?.expectedTimeRange
  const expectedNativeStep =
    resolveExpectedNativeStep({
      algorithmParams: options.algorithmParams,
      catalogNativeStep: options.catalogNativeStep,
      workflowId: options.workflowId,
    }) ||
    options.previous?.expectedNativeStep ||
    '1d'
  return { expectedTimeRange, expectedNativeStep }
}

/** 已进入 time_list 的 inFlight 键剔除，避免黄格粘滞 */
export function pruneInFlightTimeKeys(
  inFlight: string[] | undefined,
  readyTimeList: string[] | undefined,
): string[] | undefined {
  if (!inFlight?.length) return inFlight
  if (!readyTimeList?.length) return inFlight
  const ready = new Set(readyTimeList.map((k) => String(k).trim()).filter(Boolean))
  const next = inFlight.filter((k) => {
    const key = String(k).trim()
    if (!key) return false
    if (ready.has(key)) return false
    // 块键 20251203_20251210 与单日就绪并存时：若起止任一已在 ready 列表仍保留黄格直到整块就绪
    return true
  })
  return next.length === inFlight.length ? inFlight : next
}

export function parseTimeStepOrDefault(raw: string | TimeStep | null | undefined): TimeStep {
  return parseTimeStep(raw) ?? { value: 1, unit: 'day' }
}
