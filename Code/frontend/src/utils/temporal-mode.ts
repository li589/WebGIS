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
 * 以 UTC 分量格式化 ISO 日期为 YYYY-MM-DD。
 *
 * 多日块的块边界由 Date.UTC 构造，用本地分量读取会在 UTC 负偏移区
 * 偏早一天；块基准须与算法侧严格一致，故此处只用 UTC 分量。
 */
function toUtcDateStr(d: Date): string {
  const y = d.getUTCFullYear()
  const m = String(d.getUTCMonth() + 1).padStart(2, '0')
  const day = String(d.getUTCDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

/**
 * 以 UTC 分量格式化 ISO 日期为 YYYYMMDD（时间键，需与盘上产物对齐）。
 */
function toUtcCompactDateStr(d: Date): string {
  const y = d.getUTCFullYear()
  const m = String(d.getUTCMonth() + 1).padStart(2, '0')
  const day = String(d.getUTCDate()).padStart(2, '0')
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
    // 块基准必须与算法侧一致：omega_sf_fenkuai / make_viirs8_blocks 以
    // 「每年 1 月 1 日」为起点、每 step 天一块，跨年重置（年末不足 step 天
    // 的尾块截断到 12/31）。此前按「月内 1/9/17/25」切，非 step 整数倍的
    // 月份会与算法块错位——如 12/25 归入前端块 12/25~1/1，而算法块是
    // 12/19~12/26；下载窗只覆盖算法块的一部分，块内有效观测不足 2 天，
    // 反演即报 coverage_gap「无有效像元」。
    const startOfYearMs = Date.UTC(y, 0, 1, 0, 0, 0)
    const dayOfYear =
      Math.floor((Date.UTC(y, m, date.getDate(), 0, 0, 0) - startOfYearMs) / 86_400_000) + 1
    const blockStartOffset = step * Math.floor((dayOfYear - 1) / step)
    const start = new Date(Date.UTC(y, 0, 1 + blockStartOffset, 0, 0, 0))
    // 含端点末日：块起点 + (step-1) 天，且不越过当年 12/31（跨年不合并）
    const lastDayMs = Math.min(
      start.getTime() + (step - 1) * 86_400_000,
      Date.UTC(y, 11, 31, 0, 0, 0),
    )
    const lastDay = new Date(lastDayMs)
    const end = new Date(lastDayMs + 86_400_000) // 半开终点，与 job payload 一致
    const sStr = toUtcDateStr(start)
    const eStr = toUtcDateStr(lastDay)
    const timeKey = `${toUtcCompactDateStr(start)}_${toUtcCompactDateStr(lastDay)}`
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
