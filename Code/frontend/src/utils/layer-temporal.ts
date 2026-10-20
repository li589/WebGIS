/**
 * 从 ActiveLayer / 天气层构建 LayerTemporalSpec，并解析相对 T_ref 的生效切片。
 */
import type { ActiveLayer } from '../stores/layers/types'
import {
  defaultFollowPolicy,
  latestSlice,
  parseInstant,
  parseTimeStep,
  resolveSliceForInstant,
  sliceStartAsDateHour,
  timeListToSlices,
  timeStepToLegacyGranularity,
  type LayerTemporalSpec,
  type ResolvedSlice,
  type TimeSlice,
  type TimeStep,
} from './temporal-interval'

export function temporalSpecFromActiveLayer(
  layer: ActiveLayer | null | undefined,
): LayerTemporalSpec | null {
  if (!layer?.importedRaster) return null
  const raster = layer.importedRaster
  const step =
    (typeof raster.nativeStep === 'string'
      ? parseTimeStep(raster.nativeStep)
      : raster.nativeStep) ??
    (raster.timeList?.some((t) => /^\d{8}_\d{8}$/.test(t))
      ? ({ value: 8, unit: 'day' } as TimeStep)
      : raster.timeList?.length
        ? ({ value: 1, unit: 'day' } as TimeStep)
        : null)
  if (!step) return null
  const slices = raster.timeSlices?.length
    ? raster.timeSlices
    : timeListToSlices(raster.timeList ?? [])
  if (!slices.length) return null
  return {
    nativeStep: step,
    slices,
    followPolicy: raster.followPolicy ?? defaultFollowPolicy(step),
  }
}

export function resolveLayerEffectiveTime(
  layer: ActiveLayer | null | undefined,
  tRef: Date,
): ResolvedSlice | null {
  const spec = temporalSpecFromActiveLayer(layer)
  if (!spec) return null
  return resolveSliceForInstant(spec, tRef)
}

/**
 * 按月汇总 time_list 实际覆盖到的日历日：`YYYY-MM` → 有数据的日子集合。
 *
 * 逐日产品的 time_list 会混着「单日帧」和「多日合成窗口键」，两者都要展开，
 * 只按日期集合统计"这个月到底有几天有数据"。
 */
function coveredDaysByMonth(slices: TimeSlice[]): Map<string, Set<number>> {
  const out = new Map<string, Set<number>>()
  for (const sl of slices) {
    const start = parseInstant(sl.t0)
    if (!start) continue
    const end = sl.t1 ? parseInstant(sl.t1) : start
    if (!end) continue
    const cur = new Date(start.getFullYear(), start.getMonth(), start.getDate())
    const last = new Date(end.getFullYear(), end.getMonth(), end.getDate())
    let guard = 0
    while (cur.getTime() <= last.getTime() && guard++ < 4000) {
      const key = `${cur.getFullYear()}-${String(cur.getMonth() + 1).padStart(2, '0')}`
      const set = out.get(key) ?? new Set<number>()
      set.add(cur.getDate())
      out.set(key, set)
      cur.setDate(cur.getDate() + 1)
    }
  }
  return out
}

/**
 * 逐日产品的「最新完整月」锚点。
 *
 * 产物的最后一片常常是新月里孤零零的一天（如 `20260201`——2 月只算了一天），
 * 直接吸附到 `latestSlice` 会让时间轴停在一个几乎空白的新月，时间轴刻度一片灰
 * （用户 2026-10-20 反馈：加 SMAP 只想先看到一个月）。
 *
 * 这里改为：按月统计有数据的天数，从最新月份往回找第一个「覆盖达到该月 2/3」
 * 的月，锚到该月最后一个有数据的日子。SMAP 当前数据即落到 2026-01-31，
 * 时间轴一屏正好是 2026 年 1 月整月。
 */
function latestCompleteMonthAnchor(spec: LayerTemporalSpec): {
  date: Date
  hour: number
  label: string
} | null {
  const byMonth = coveredDaysByMonth(spec.slices)
  if (!byMonth.size) return null
  const keys = Array.from(byMonth.keys()).sort()
  for (let i = keys.length - 1; i >= 0; i--) {
    const key = keys[i]!
    const [yearStr, monthStr] = key.split('-')
    const year = Number(yearStr)
    const month = Number(monthStr)
    if (!Number.isFinite(year) || !Number.isFinite(month)) continue
    const daysInMonth = new Date(year, month, 0).getDate()
    const covered = byMonth.get(key)
    if (!covered?.size) continue
    // 2/3 覆盖即视为"这个月数据是齐的"；只有零头几天的新月会被跳过。
    if (covered.size < Math.ceil((daysInMonth * 2) / 3)) continue
    const lastDay = Math.max(...covered)
    return {
      date: new Date(year, month - 1, lastDay),
      hour: 0,
      label: `${year}${String(month).padStart(2, '0')}${String(lastDay).padStart(2, '0')}`,
    }
  }
  return null
}

export function snapTargetFromLayer(layer: ActiveLayer | null | undefined): {
  date: Date
  hour: number
  label: string
  granularity: 'hour' | 'day' | 'month' | 'year' | 'static'
} | null {
  const spec = temporalSpecFromActiveLayer(layer)
  if (!spec) return null
  const granularity = timeStepToLegacyGranularity(spec.nativeStep)
  // 逐日产品：优先落到最新完整月，别停在月初孤零零的一天。
  if (granularity === 'day' && spec.nativeStep.value <= 1) {
    const monthly = latestCompleteMonthAnchor(spec)
    if (monthly) {
      return { ...monthly, granularity }
    }
  }
  const latest = latestSlice(spec)
  if (!latest) return null
  const dh = sliceStartAsDateHour(latest)
  if (!dh) return null
  return {
    date: dh.date,
    hour: dh.hour,
    label: latest.label ?? String(latest.t0),
    granularity,
  }
}

export function referenceInstantFromTimeline(date: Date, hour: number): Date {
  const d = new Date(date)
  const h = Math.floor(hour)
  const m = Math.round((hour - h) * 60)
  d.setHours(h, m, 0, 0)
  return d
}
