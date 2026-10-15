/**
 * 时间键（overlay `time_list` / `default_time`）→ 侧栏展示用日期标签。
 *
 * 后端时间键为紧凑格式：
 *   - 单日：`YYYYMMDD`（如 20260201）
 *   - 区间：`YYYYMMDD_YYYYMMDD`（如 20251203_20251212，十天合成帧）
 *
 * 2026-10-15 用户要求：左侧图层面板统一显示为
 *   - 单日：`YYYY_MM_DD`（2026_02_01）
 *   - 区间：`YYYY_MM_DD~YYYY_MM_DD`（2025_12_03~2025_12_12）
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

function dashify(match: RegExpExecArray, offset: number): string {
  return `${match[offset]}_${match[offset + 1]}_${match[offset + 2]}`
}

/** `20251203_20251212` → `2025_12_03~2025_12_12`；`20260201` → `2026_02_01` */
export function formatTimeKeyLabel(raw: string | null | undefined): string {
  const key = String(raw ?? '').trim()
  if (!key) return ''

  const range = DAY_RANGE.exec(key)
  if (range) return `${dashify(range, 1)}~${dashify(range, 4)}`

  const single = SINGLE_DAY.exec(key)
  if (single) return dashify(single, 1)

  return key
}
