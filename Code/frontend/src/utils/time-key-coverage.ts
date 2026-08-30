/**
 * 时间轴 timeKey 与产物 time_list 匹配（YYYY-MM-DD / YYYYMMDD / 块窗）。
 */
export function normalizeTimeToken(value: string): string {
  const s = String(value || '').trim()
  const m = /^(\d{4})[-_/]?(\d{2})[-_/]?(\d{2})/.exec(s)
  if (m) return `${m[1]}${m[2]}${m[3]}`
  if (/^\d{4}-\d{2}$/.test(s)) return s.replace('-', '')
  if (/^\d{4}$/.test(s)) return s
  return s.replace(/[-_T:\s]/g, '').slice(0, 8)
}

/**
 * 计划会话 timeKey 是否可被 buildTimeRangeFromKey 解析。
 * 接受：YYYY / YYYY-MM / YYYY-MM-DD / YYYY-MM-DDTHH:00:00
 */
export function isPlausiblePlanTimeKey(raw: string): boolean {
  const key = String(raw || '').trim()
  if (!key) return false
  if (/^\d{4}$/.test(key)) return true
  if (/^\d{4}-\d{2}$/.test(key)) {
    const m = Number(key.slice(5, 7))
    return m >= 1 && m <= 12
  }
  if (/^\d{4}-\d{2}-\d{2}$/.test(key)) {
    const [y, mo, d] = key.split('-').map(Number)
    const dt = new Date(y, mo - 1, d)
    return (
      !Number.isNaN(dt.getTime()) &&
      dt.getFullYear() === y &&
      dt.getMonth() === mo - 1 &&
      dt.getDate() === d
    )
  }
  if (/^\d{4}-\d{2}-\d{2}T\d{2}:00:00$/.test(key)) {
    const d = new Date(key)
    return !Number.isNaN(d.getTime())
  }
  return false
}

/** time_list 项（日或块）是否覆盖轴上 timeKey。 */
export function timeListCoversTimeKey(timeList: string[] | undefined | null, timeKey: string): boolean {
  if (!timeList?.length || !timeKey) return false
  const target = normalizeTimeToken(timeKey)
  if (!target) return false
  for (const item of timeList) {
    const raw = String(item || '').trim()
    if (!raw) continue
    // YYYYMMDD_YYYYMMDD block
    const block = /^(\d{4})[-_/]?(\d{2})[-_/]?(\d{2})[_-](\d{4})[-_/]?(\d{2})[-_/]?(\d{2})/.exec(raw)
    if (block) {
      const a = `${block[1]}${block[2]}${block[3]}`
      const b = `${block[4]}${block[5]}${block[6]}`
      if (target.length >= 8 && a <= target.slice(0, 8) && target.slice(0, 8) <= b) return true
      continue
    }
    const day = normalizeTimeToken(raw)
    if (day && (day === target || target.startsWith(day) || day.startsWith(target.slice(0, 8)))) {
      return true
    }
  }
  return false
}
