/**
 * 下载节点表单共享工具：节点属性读取 + YYYYMMDD ⇄ ISO 日期转换。
 *
 * 后端下载节点（download/ssh_sync、download/nsidc_smap_download、download/gldas_download、download/fy_preprocess）
 * 的日期参数统一以 YYYYMMDD 字符串存储；原生 <input type="date"> 需要 YYYY-MM-DD，
 * 故在展示与写回之间做转换。
 */

/** YYYYMMDD(20240115) → ISO(2024-01-15)，供 <input type="date"> 使用。 */
export function yyyymmddToIso(value: unknown): string {
  const s = String(value ?? '').trim()
  if (!s) return ''
  if (/^\d{4}-\d{2}-\d{2}/.test(s)) return s.slice(0, 10)
  if (/^\d{8}$/.test(s)) return `${s.slice(0, 4)}-${s.slice(4, 6)}-${s.slice(6, 8)}`
  return ''
}

/** ISO(2024-01-15) → YYYYMMDD(20240115)，写回节点属性。 */
export function isoToYyyymmdd(value: unknown): string {
  const s = String(value ?? '').trim()
  if (!s) return ''
  if (/^\d{8}$/.test(s)) return s
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(s)
  if (m) return `${m[1]}${m[2]}${m[3]}`
  return s
}

/** 读取节点属性，缺失 / 空值时回退默认值。 */
export function getNodeProperty<T>(
  node: { properties?: Record<string, unknown> | null } | null | undefined,
  key: string,
  defaultValue: T,
): T {
  const v = node?.properties?.[key]
  if (v === undefined || v === null || v === '') return defaultValue
  return v as T
}

/**
 * 把节点属性同步进本地 reactive 表单对象。
 * 仅覆盖 defaults 中声明的键；空值回退默认值。
 */
export function syncFormFromNode(
  form: Record<string, unknown>,
  node: { properties?: Record<string, unknown> | null } | null | undefined,
  defaults: Record<string, unknown>,
): void {
  const p = node?.properties ?? {}
  for (const k of Object.keys(defaults)) {
    const v = p[k]
    form[k] = v === undefined || v === null || v === '' ? defaults[k] : v
  }
}

// ── 表单校验工具 ──────────────────────────────────────────────────────────────

/** 表单错误集合类型：字段名 → 错误信息。 */
export type FormErrors = Record<string, string>

/**
 * 校验日期范围 start <= end（YYYYMMDD 格式）。
 * - 两者皆空视为合法（日期非必填场景）。
 * - 仅一端填写则报错。
 * - 格式非 8 位数字则报错。
 * - start > end（定长 YYYYMMDD 可直接字典序比较）则报错。
 * 返回 null 表示通过，否则返回中文错误描述。
 */
export function validateDateRange(startDate: string, endDate: string): string | null {
  if (!startDate && !endDate) return null
  if (!startDate) return '开始日期不能为空'
  if (!endDate) return '结束日期不能为空'
  if (!/^\d{8}$/.test(startDate)) return '开始日期格式无效（应为 YYYYMMDD）'
  if (!/^\d{8}$/.test(endDate)) return '结束日期格式无效（应为 YYYYMMDD）'
  if (startDate > endDate) return '开始日期不能晚于结束日期'
  return null
}

/**
 * 校验非空字段。支持字符串（trim 后非空）与数组（长度 > 0）。
 * null / undefined / 空字符串 / 空数组均视为空。
 * 返回 null 表示通过，否则返回 `${label}不能为空`。
 */
export function validateRequired(value: unknown, label: string): string | null {
  if (
    value == null ||
    (typeof value === 'string' && !value.trim()) ||
    (Array.isArray(value) && value.length === 0)
  ) {
    return `${label}不能为空`
  }
  return null
}
