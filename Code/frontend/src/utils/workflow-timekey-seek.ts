import { parseInstant, timeStepToLegacyGranularity, type TimeStep } from './temporal-interval'

export type WorkflowTimelineSeekTarget = {
  date: Date
  hour: number
  granularity: 'hour' | 'day' | 'month' | 'year' | 'static'
  sliceLabel: string
}

/** 运行中 node_progress → 时间轴 seek 提示（DashboardView 消费） */
export type WorkflowProgressTimeSeekHint = {
  runId: string
  catalogId: string
  timeKey: string
  sliceLabel: string
  at: string
}

/** 将 node_progress.detail.timeKey / dateStart[-dateEnd] 解析为主时间轴定位目标。 */
export function timelineTargetFromWorkflowTimeKey(
  timeKey: string,
  dateEnd?: string,
): WorkflowTimelineSeekTarget | null {
  const raw = String(timeKey || '').trim()
  if (!raw) return null

  const rangeMatch = raw.match(/^(\d{8})_(\d{8})$/)
  if (rangeMatch) {
    const start = parseInstant(rangeMatch[1]!)
    if (!start) return null
    return {
      date: start,
      hour: 0,
      granularity: 'day',
      sliceLabel: raw,
    }
  }

  const start = parseInstant(raw)
  if (!start) return null

  const startCompact = raw.replace(/-/g, '').slice(0, 8)
  let sliceLabel = /^\d{8}$/.test(startCompact) ? startCompact : raw
  const endRaw = String(dateEnd || '')
    .trim()
    .replace(/-/g, '')
    .slice(0, 8)
  if (endRaw && endRaw !== sliceLabel) {
    sliceLabel = `${sliceLabel}_${endRaw}`
  }

  const nativeStep: TimeStep =
    sliceLabel.includes('_') && sliceLabel.length >= 17
      ? { value: 8, unit: 'day' }
      : { value: 1, unit: 'day' }

  return {
    date: start,
    hour: 0,
    granularity: timeStepToLegacyGranularity(nativeStep),
    sliceLabel,
  }
}

/** 在图层 time_list 中找与 seek 标签最匹配的项（精确或前缀）。 */
export function matchSliceLabelInTimeList(
  timeList: string[] | undefined,
  sliceLabel: string,
): string | null {
  if (!timeList?.length || !sliceLabel) return null
  if (timeList.includes(sliceLabel)) return sliceLabel
  const prefix = sliceLabel.slice(0, 8)
  const byPrefix = timeList.find(
    (t) => t === prefix || t.startsWith(`${prefix}_`) || t.startsWith(prefix),
  )
  return byPrefix ?? null
}
