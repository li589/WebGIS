/**
 * temporal-mode.ts — 标签驱动的时间模式识别与时段对齐工具。
 *
 * 杜绝硬编码图层 ID：
 * - temporal:range / temporal:monthly / temporal:multi-day-block 标明需设定时间段而非单点；
 * - temporal:instant 标明时间点模式（如逐小时天气）；
 * - 未显式打标时，优雅回退到 native_step (8d/16d/1M) 或 time_granularity。
 */

export type TemporalSelectionMode = 'range' | 'instant'

export type TemporalRangeSubtype = 'monthly' | 'multi-day-block' | 'yearly' | 'custom'

export interface LayerTemporalModeInfo {
  mode: TemporalSelectionMode
  subtype?: TemporalRangeSubtype
  stepDays?: number
  label: string
}

export interface AlignedTimeRange {
  start_at: string
  end_at: string
  granularity: string
  timeKey: string
  displayLabel: string
}

/**
 * 解析图层的时间选择模式（时段型 vs 时间点型）。
 */
export function resolveLayerTemporalMode(
  descriptor?: {
    tags?: string[] | null
    time_granularity?: string | null
    native_step?: string | null
    online_temporal?: { native_step?: string | null } | null
  } | null,
): LayerTemporalModeInfo {
  if (!descriptor) {
    return { mode: 'instant', label: '时间点' }
  }

  const tags = (descriptor.tags || []).map((t) => String(t).trim().toLowerCase())
  const rawStep = descriptor.native_step || descriptor.online_temporal?.native_step || ''
  const stepStr = String(rawStep).trim().toLowerCase()
  const gran = String(descriptor.time_granularity || '')
    .trim()
    .toLowerCase()

  // 1. 显式 Tag 优先
  if (tags.includes('temporal:instant')) {
    return { mode: 'instant', label: '时间点' }
  }

  if (tags.includes('temporal:monthly') || tags.includes('temporal:month')) {
    return { mode: 'range', subtype: 'monthly', stepDays: 30, label: '整月时段' }
  }

  if (tags.includes('temporal:8d-block') || tags.includes('temporal:8d')) {
    return { mode: 'range', subtype: 'multi-day-block', stepDays: 8, label: '8天块时段' }
  }

  if (tags.includes('temporal:16d-block') || tags.includes('temporal:16d')) {
    return { mode: 'range', subtype: 'multi-day-block', stepDays: 16, label: '16天块时段' }
  }

  if (tags.includes('temporal:multi-day-block') || tags.includes('temporal:block')) {
    const match = stepStr.match(/^(\d+)d$/)
    const days = match ? Number(match[1]) : 8
    return { mode: 'range', subtype: 'multi-day-block', stepDays: days, label: `${days}天块时段` }
  }

  if (tags.includes('temporal:range') || tags.includes('temporal:period')) {
    if (gran === 'month' || stepStr === '1m' || stepStr === '1mon' || stepStr === '1month') {
      return { mode: 'range', subtype: 'monthly', stepDays: 30, label: '整月时段' }
    }
    const match = stepStr.match(/^(\d+)d$/)
    if (match && Number(match[1]) > 1) {
      const days = Number(match[1])
      return { mode: 'range', subtype: 'multi-day-block', stepDays: days, label: `${days}天块时段` }
    }
    return { mode: 'range', subtype: 'custom', label: '时间段' }
  }

  // 2. 隐式步长与粒度推断（平滑回退，无需硬编码）
  if (stepStr.startsWith('8d')) {
    return { mode: 'range', subtype: 'multi-day-block', stepDays: 8, label: '8天块时段' }
  }
  if (stepStr.startsWith('16d')) {
    return { mode: 'range', subtype: 'multi-day-block', stepDays: 16, label: '16天块时段' }
  }
  if (gran === 'month' || stepStr === '1m' || stepStr === '1mon' || stepStr === '1month') {
    return { mode: 'range', subtype: 'monthly', stepDays: 30, label: '整月时段' }
  }
  if (gran === 'year' || stepStr === '1y' || stepStr === '1yr' || stepStr === '1year') {
    return { mode: 'range', subtype: 'yearly', label: '自然年时段' }
  }

  // 默认时间点
  return { mode: 'instant', label: '时间点' }
}

/**
 * 格式化 ISO 日期为 YYYY-MM-DD
 */
function toDateStr(d: Date): string {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

/**
 * 格式化 ISO 日期为 YYYYMMDD
 */
function toCompactDateStr(d: Date): string {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}${m}${day}`
}

/**
 * 将某个日期按图层的时间模式对齐为标准起止时段。
 */
export function alignDateToTemporalRange(
  dateOrStr: Date | string,
  info: LayerTemporalModeInfo,
): AlignedTimeRange {
  const date =
    typeof dateOrStr === 'string'
      ? dateOrStr.includes('T')
        ? new Date(dateOrStr)
        : new Date(`${dateOrStr.slice(0, 10)}T00:00:00Z`)
      : dateOrStr
  const y = date.getFullYear()
  const m = date.getMonth()

  if (info.mode === 'range' && info.subtype === 'monthly') {
    // 整月：从当月 1 日到次月 1 日（半开区间）
    const start = new Date(Date.UTC(y, m, 1, 0, 0, 0))
    const end = new Date(Date.UTC(y, m + 1, 1, 0, 0, 0))
    const monthKey = `${y}-${String(m + 1).padStart(2, '0')}`
    return {
      start_at: start.toISOString(),
      end_at: end.toISOString(),
      granularity: 'month',
      timeKey: monthKey,
      displayLabel: `${monthKey}（整月）`,
    }
  }

  if (info.mode === 'range' && info.subtype === 'multi-day-block') {
    const step = info.stepDays || 8
    const dayOfMonth = date.getDate() // 1-31
    // 按 1 日为基准切块：例如 step=8，块为 1-8, 9-16, 17-24, 25-32
    const blockIndex = Math.floor((dayOfMonth - 1) / step)
    const blockStartDay = blockIndex * step + 1
    const start = new Date(Date.UTC(y, m, blockStartDay, 0, 0, 0))
    const end = new Date(Date.UTC(y, m, blockStartDay + step, 0, 0, 0))
    const sStr = toDateStr(start)
    const eDay = new Date(Date.UTC(y, m, blockStartDay + step - 1, 0, 0, 0))
    const eStr = toDateStr(eDay)
    const timeKey = `${toCompactDateStr(start)}_${toCompactDateStr(eDay)}`
    return {
      start_at: start.toISOString(),
      end_at: end.toISOString(),
      granularity: 'day',
      timeKey,
      displayLabel: `${sStr} ~ ${eStr}（${step}天块）`,
    }
  }

  if (info.mode === 'range' && info.subtype === 'yearly') {
    const start = new Date(Date.UTC(y, 0, 1, 0, 0, 0))
    const end = new Date(Date.UTC(y + 1, 0, 1, 0, 0, 0))
    return {
      start_at: start.toISOString(),
      end_at: end.toISOString(),
      granularity: 'year',
      timeKey: `${y}`,
      displayLabel: `${y}年（全年）`,
    }
  }

  // instant 模式：单日或单时刻
  const start = new Date(Date.UTC(y, m, date.getDate(), date.getHours(), 0, 0))
  const end = new Date(start.getTime() + 3600_000)
  const dStr = toDateStr(date)
  return {
    start_at: start.toISOString(),
    end_at: end.toISOString(),
    granularity: 'hour',
    timeKey: dStr,
    displayLabel: dStr,
  }
}
