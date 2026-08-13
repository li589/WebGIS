/**
 * 图层时空粒度与时间轴模型适配器
 * 支持 hour / day / month / year / static 多粒度计算、格式化与切片生成
 */

export type TimeGranularity = 'hour' | 'day' | 'month' | 'year' | 'static'

export interface TimelineAvailabilitySegment {
  index: number
  label: string
  state: 'empty' | 'partial' | 'ready' | 'static' | 'error' | 'fetchable'
  availabilityLabel: string
  timestamp?: number
}

/**
 * 根据粒度格式化时间与日期展示文本
 */
export function formatTimelineDateLabel(
  date: Date,
  granularity: TimeGranularity = 'hour',
  hour = 0,
): string {
  if (granularity === 'static') {
    return '静态图层 (无时间维度)'
  }

  const y = date.getFullYear()
  const m = String(date.getMonth() + 1).padStart(2, '0')
  const d = String(date.getDate()).padStart(2, '0')

  if (granularity === 'year') {
    return `${y}年`
  }
  if (granularity === 'month') {
    return `${y}年${m}月`
  }
  if (granularity === 'day') {
    return `${y}-${m}-${d}`
  }

  // hour 粒度
  const hInt = Math.floor(hour)
  const mInt = Math.round((hour - hInt) * 60)
  const hStr = String(hInt).padStart(2, '0')
  const mStr = String(mInt).padStart(2, '0')
  return `${y}-${m}-${d} ${hStr}:${mStr}`
}

/**
 * 根据粒度返回统一的单位标签（显示在时间轴一侧，而非每个刻度上）
 */
export function granularityUnitLabel(granularity: TimeGranularity): string {
  switch (granularity) {
    case 'hour':
      return '时'
    case 'day':
      return '日'
    case 'month':
      return '月'
    case 'year':
      return '年'
    case 'static':
      return ''
  }
}

/**
 * 根据粒度移动时间/日期。
 *
 * 月末（如 1/31 +1 月）和闰日跨平年（如 2/29 +1 年）时 JS Date 会滚动到次月
 * （setMonth/setFullYear 不钳制），本函数在溢出后用 ``setDate(0)`` 钳制到目标月
 * 最后一天（如 1/31 +1月 → 2/28，2/29 +1年 → 2/28），保持"月末不移出当月"语义。
 */
export function shiftTimelineDate(
  date: Date,
  delta: number,
  granularity: TimeGranularity = 'hour',
): Date {
  const result = new Date(date)
  if (granularity === 'static') return result

  if (granularity === 'year') {
    const origDay = date.getDate()
    result.setFullYear(result.getFullYear() + delta)
    // 闰日跨平年溢出 → 钳制到目标年同月最后一天
    if (result.getDate() !== origDay) result.setDate(0)
    return result
  }
  if (granularity === 'month') {
    const origDay = date.getDate()
    result.setMonth(result.getMonth() + delta)
    // 月末溢出（如 1/31→2 月）→ 钳制到目标月最后一天
    if (result.getDate() !== origDay) result.setDate(0)
    return result
  }
  if (granularity === 'day' || granularity === 'hour') {
    result.setDate(result.getDate() + delta)
    return result
  }
  return result
}

/**
 * 为不同时间粒度生成时间轴刻度与数据可用性切片
 *
 * 刻度 label 不再携带单位后缀（如 "1日" → "1"），
 * 单位信息由 granularityUnitLabel() 统一提供。
 */
export function generateTimelineSegments(
  date: Date,
  granularity: TimeGranularity = 'hour',
  availabilityMap?: Record<number, 'empty' | 'partial' | 'ready' | 'error' | 'fetchable'>,
): TimelineAvailabilitySegment[] {
  if (granularity === 'static') {
    return [
      {
        index: 0,
        label: '静态',
        state: 'static',
        availabilityLabel: '无时间维度 · 全面就绪',
      },
    ]
  }

  const labelFor = (state: 'empty' | 'partial' | 'ready' | 'error' | 'fetchable') => {
    if (state === 'ready') return '数据可用'
    if (state === 'partial') return '部分就绪 / 加载中'
    if (state === 'error') return '产出异常'
    if (state === 'fetchable') return '可在线获取'
    return '无数据'
  }

  if (granularity === 'month') {
    return Array.from({ length: 12 }, (_, idx) => {
      // 未知 ≠ 就绪：缺 map 或未覆盖格一律 empty，避免工作流计算中「假全绿」
      const state = availabilityMap?.[idx] ?? 'empty'
      return {
        index: idx,
        label: `${idx + 1}`,
        state,
        availabilityLabel: labelFor(state),
      }
    })
  }

  if (granularity === 'year') {
    // 近 10 年滑动窗口；index 用真实年份，便于刻度点击 / 滑块直接改年
    const currentYear = date.getFullYear()
    const baseYear = currentYear - 5
    const segments: TimelineAvailabilitySegment[] = []
    for (let i = 0; i < 10; i++) {
      const yr = baseYear + i
      const state = availabilityMap?.[yr] ?? availabilityMap?.[i] ?? 'empty'
      segments.push({
        index: yr,
        label: `${yr}`,
        state,
        availabilityLabel:
          state === 'ready'
            ? '年度数据已就绪'
            : state === 'partial'
              ? '部分就绪 / 加载中'
              : state === 'error'
                ? '产出异常'
                : state === 'fetchable'
                  ? '可在线获取'
                  : '无数据',
      })
    }
    return segments
  }

  if (granularity === 'day') {
    // 呈现当月天数，不带 "日" 后缀
    const year = date.getFullYear()
    const month = date.getMonth()
    const daysInMonth = new Date(year, month + 1, 0).getDate()
    const segments: TimelineAvailabilitySegment[] = []
    for (let d = 1; d <= daysInMonth; d++) {
      const state = availabilityMap?.[d] ?? 'empty'
      segments.push({
        index: d,
        label: `${d}`,
        state,
        availabilityLabel:
          state === 'ready'
            ? '每日数据已就绪'
            : state === 'partial'
              ? '部分就绪 / 加载中'
              : state === 'error'
                ? '产出异常'
                : state === 'fetchable'
                  ? '可在线获取'
                  : '无数据',
      })
    }
    return segments
  }

  // hour 粒度 (0 - 23 小时)，用紧凑格式 "0" ~ "23" 代替 "00:00"
  const segments: TimelineAvailabilitySegment[] = []
  for (let h = 0; h < 24; h++) {
    const state = availabilityMap?.[h] ?? 'empty'
    const statusText =
      state === 'ready'
        ? '瓦片数据已就绪'
        : state === 'partial'
          ? '降采样中/部分补全'
          : state === 'error'
            ? '产出异常'
            : state === 'fetchable'
              ? '可在线获取'
              : '无数据'
    segments.push({
      index: h,
      label: `${h}`,
      state,
      availabilityLabel: statusText,
    })
  }
  return segments
}

/**
 * 智能计算哪些 tick 应显示完整文字标签。
 * 根据总 tick 数 & 可用渲染宽度自动抽稀，
 * 保证首尾和间隔均匀子集有标签，其余只显示小竖线。
 *
 * @param totalTicks  总刻度数
 * @param maxLabels   最多允许显示的文字刻度数（默认 12）
 * @returns           应显示标签的 tick 序号集合
 */
export function computeVisibleTickIndices(totalTicks: number, maxLabels = 12): Set<number> {
  if (totalTicks <= maxLabels) {
    return new Set(Array.from({ length: totalTicks }, (_, i) => i))
  }

  const visible = new Set<number>()
  // 始终包含首尾
  visible.add(0)
  visible.add(totalTicks - 1)

  // 按等间距在内部插入标签点
  const innerSlots = maxLabels - 2
  const step = (totalTicks - 1) / (innerSlots + 1)
  for (let i = 1; i <= innerSlots; i++) {
    visible.add(Math.round(step * i))
  }
  return visible
}
