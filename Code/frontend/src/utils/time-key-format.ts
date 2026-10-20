/**
 * 时间键（overlay `time_list` / `default_time`）→ 侧栏展示用日期标签。
 *
 * 后端时间键为紧凑格式：
 *   - 单日：`YYYYMMDD`（如 20260201）
 *   - 区间：`YYYYMMDD_YYYYMMDD`（如 20251203_20251212，十天合成帧）
 *
 * 2026-10-16 用户要求：左侧图层面板统一显示为斜杠分隔
 *   - 单日：`YYYY/MM/DD`（2026/02/01）
 *   - 区间：`YYYY/MM/DD ~ YYYY/MM/DD`（2025/12/03 ~ 2025/12/12）
 *
 * 2026-10-17 用户要求：区间分隔符 `~` 前后各留一个空格，所有图层统一。
 *
 * 输入可能已经是带分隔符的形态（如 `2025_12_03-2025_12_12`，由上游
 * effectiveTimeLabel 提供），因此除紧凑键外还要吃下这类串，统一转斜杠。
 *
 * 注意：**只做展示转换，不改变任何时间键本身**。真实的 time key 仍以原始
 * 形态参与瓦片请求 / 时间轴匹配（见 `overlay-tiles-adapter.ts` 等）。
 * 因此这里只在渲染层调用，切勿把结果写回 layer.importedRaster.timeList /
 * effectiveTimeLabel，否则请求会带上非法时间键。
 *
 * 非上述形态（如 6h 步长的 `20251203_1200`）原样返回，避免误伤。
 */

const SINGLE_DAY = /^(\d{4})(\d{2})(\d{2})$/
const DAY_RANGE = /^(\d{4})(\d{2})(\d{2})_(\d{4})(\d{2})(\d{2})$/
// 已带分隔符的形态：2025_12_03 / 2025-12-03 / 2025/12/03
const SEPARATED_DAY = /^(\d{4})[_/-](\d{2})[_/-](\d{2})$/
const SEPARATED_RANGE = /^(\d{4})[_/-](\d{2})[_/-](\d{2})\s*[-~]\s*(\d{4})[_/-](\d{2})[_/-](\d{2})$/

function slashed(match: RegExpExecArray, offset: number): string {
  return `${match[offset]}/${match[offset + 1]}/${match[offset + 2]}`
}

/** `20251203_20251212` → `2025/12/03 ~ 2025/12/12`；`20260201` → `2026/02/01` */
export function formatTimeKeyLabel(raw: string | null | undefined): string {
  const key = String(raw ?? '').trim()
  if (!key) return ''

  const range = DAY_RANGE.exec(key) ?? SEPARATED_RANGE.exec(key)
  if (range) return `${slashed(range, 1)} ~ ${slashed(range, 4)}`

  const single = SINGLE_DAY.exec(key) ?? SEPARATED_DAY.exec(key)
  if (single) return slashed(single, 1)

  return key
}

/** 从任意时间键里抠出年月；抠不到返回 null。 */
function yearMonthOf(raw: string | null | undefined): { year: number; month: number } | null {
  const key = String(raw ?? '').trim()
  const compact = /^(\d{4})(\d{2})\d{2}/.exec(key)
  if (compact) return { year: Number(compact[1]), month: Number(compact[2]) }
  const separated = /^(\d{4})[_/-](\d{2})/.exec(key)
  if (separated) return { year: Number(separated[1]), month: Number(separated[2]) }
  return null
}

/**
 * 逐日产品的「该月实际覆盖范围」标签。
 *
 * 2026-10-20 用户要求：SMAP 这类**逐日**图层也要像风云（月产品）一样，卡片日期
 * 显示成一整月，而不是某一格单日、也不是 `2025/12/27 ~ 2025/12/31` 这种历史窗口键。
 *
 * 做法：拿当前命中键的年月 → 把 time_list 里所有键展开成日 → 收集落在该月的日子
 * → 取该月最早与最晚有数据的两天。跨月的合成块（如 `20251125_20251202`）会把
 * 12/01、12/02 也算进 12 月，所以结果和真实覆盖一致。
 *
 * 非逐日产品、或该月一天都没有时返回 null，由调用方回落到 `formatTimeKeyLabel`。
 */
export function formatMonthCoverageLabel(
  currentKey: string | null | undefined,
  timeList: string[] | null | undefined,
): string | null {
  const ym = yearMonthOf(currentKey)
  if (!ym || !timeList?.length) return null
  const { year, month } = ym

  let minDay = 0
  let maxDay = 0
  for (const raw of timeList) {
    const key = String(raw ?? '').trim()
    const single = SINGLE_DAY.exec(key)
    const range = DAY_RANGE.exec(key)
    const startKey = single ? single : range ? range : null
    if (!startKey) continue
    const sy = Number(startKey[1])
    const sm = Number(startKey[2])
    const sd = Number(startKey[3])
    // 区间键：终点取 range 的 4/5/6 组；单日键终点＝起点
    const ey = range ? Number(range[4]) : sy
    const em = range ? Number(range[5]) : sm
    const ed = range ? Number(range[6]) : sd

    // 只关心与目标月有交集的键：起点在目标月及之前、终点在目标月及之后
    const startsBefore = sy < year || (sy === year && sm <= month)
    const endsAfter = ey > year || (ey === year && em >= month)
    if (!startsBefore || !endsAfter) continue

    // 该键在目标月内的第一天 / 最后一天
    const firstInMonth = sy === year && sm === month ? sd : 1
    const daysInMonth = new Date(year, month, 0).getDate()
    const lastInMonth = ey === year && em === month ? ed : daysInMonth

    if (!minDay || firstInMonth < minDay) minDay = firstInMonth
    if (lastInMonth > maxDay) maxDay = lastInMonth
  }

  if (!minDay || !maxDay) return null
  const mm = String(month).padStart(2, '0')
  const from = `${year}/${mm}/${String(minDay).padStart(2, '0')}`
  if (minDay === maxDay) return from
  return `${from} ~ ${year}/${mm}/${String(maxDay).padStart(2, '0')}`
}
