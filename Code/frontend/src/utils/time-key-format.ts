/**
 * 时间键（overlay `time_list` / `default_time`）→ 侧栏展示用日期标签。
 *
 * 后端时间键为紧凑格式：
 *   - 单日：`YYYYMMDD`（如 20260201）
 *   - 区间：`YYYYMMDD_YYYYMMDD`（如 20251203_20251212，十天合成帧）
 *
 * 2026-10-16 用户要求：左侧图层面板统一显示为斜杠分隔
 *   - 单日：`YYYY/MM/DD`（2026/02/01）
 *   - 区间：`YYYY/MM/DD~YYYY/MM/DD`（2025/12/03~2025/12/12）
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

/** `20251203_20251212` → `2025/12/03~2025/12/12`；`20260201` → `2026/02/01` */
export function formatTimeKeyLabel(raw: string | null | undefined): string {
  const key = String(raw ?? '').trim()
  if (!key) return ''

  const range = DAY_RANGE.exec(key) ?? SEPARATED_RANGE.exec(key)
  if (range) return `${slashed(range, 1)}~${slashed(range, 4)}`

  const single = SINGLE_DAY.exec(key) ?? SEPARATED_DAY.exec(key)
  if (single) return slashed(single, 1)

  return key
}
