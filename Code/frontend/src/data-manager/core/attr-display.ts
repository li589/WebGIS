/**
 * 属性表单元格展示：统一空值 / 数字 / 多语言文本，避免乱码与「undefined」字样。
 * 同时提供字段名 / 单元格安全输入校验（防控制字符、路径分隔与超长注入）。
 */

const REPLACEMENT = /\uFFFD/g
/** 控制字符（保留常见空白：TAB/LF/CR） */
// eslint-disable-next-line no-control-regex -- intentional security filter for control chars
const UNSAFE_CTRL = /[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F]/g
// eslint-disable-next-line no-control-regex -- intentional security filter for field names
const FIELD_FORBIDDEN = /[\\/:*?"<>|\u0000-\u001F\u007F]/
const MAX_FIELD_NAME = 64
const MAX_CELL_VALUE = 4000

export function formatAttrCell(value: unknown): string {
  if (value == null) return ''
  if (typeof value === 'number') {
    if (!Number.isFinite(value)) return ''
    if (Number.isInteger(value)) return String(value)
    const abs = Math.abs(value)
    if (abs !== 0 && (abs < 1e-6 || abs >= 1e9)) return value.toExponential(4)
    return String(Math.round(value * 1e8) / 1e8)
  }
  if (typeof value === 'boolean') return value ? 'true' : 'false'
  if (value instanceof Date) return value.toISOString()
  if (typeof value === 'object') {
    try {
      return JSON.stringify(value)
    } catch {
      return String(value)
    }
  }
  let text = String(value)
  if (REPLACEMENT.test(text)) {
    text = text.replace(REPLACEMENT, '�')
  }
  return text
}

export function attrCellTitle(value: unknown): string {
  const text = formatAttrCell(value)
  return text.length > 80 ? text : text
}

export function describeSourceEncoding(meta: {
  source_encoding?: unknown
  encoding_strict?: unknown
  encoding_sources?: unknown
}): string {
  const enc = String(meta.source_encoding || '').trim()
  if (!enc) return ''
  const strict = meta.encoding_strict
  const src = Array.isArray(meta.encoding_sources)
    ? meta.encoding_sources.map(String).filter(Boolean).slice(0, 2).join(',')
    : ''
  const parts = [`源编码 ${enc}`]
  if (strict === false || enc.includes('+replace')) {
    parts.push('有替换字符，请核对')
  }
  if (src) parts.push(src)
  return parts.join(' · ')
}

export type SafeInputResult = { ok: true; value: string } | { ok: false; error: string }

/** 清洗普通文本输入：去 NUL/控制符，限制长度。 */
export function sanitizeSafeText(
  raw: unknown,
  opts?: { maxLen?: number; allowNewlines?: boolean },
): SafeInputResult {
  const maxLen = opts?.maxLen ?? MAX_CELL_VALUE
  const allowNewlines = opts?.allowNewlines ?? false
  let text = raw == null ? '' : String(raw)
  // eslint-disable-next-line no-control-regex -- strip NUL bytes for safety
  text = text.replace(/\u0000/g, '')
  if (allowNewlines) {
    // eslint-disable-next-line no-control-regex -- strip control chars except newline
    text = text.replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F]/g, '')
  } else {
    text = text.replace(UNSAFE_CTRL, '').replace(/[\r\n]/g, ' ')
  }
  if (text.length > maxLen) {
    return { ok: false, error: `内容过长（最多 ${maxLen} 字符）` }
  }
  return { ok: true, value: text }
}

/** 字段名：去空白控制符，禁止路径/通配等危险字符。 */
export function sanitizeFieldName(raw: unknown): SafeInputResult {
  const trimmed = String(raw ?? '')
    // eslint-disable-next-line no-control-regex -- strip NUL bytes from field names
    .replace(/\u0000/g, '')
    .replace(UNSAFE_CTRL, '')
    .trim()
  if (!trimmed) return { ok: false, error: '字段名不能为空' }
  if (trimmed.length > MAX_FIELD_NAME) {
    return { ok: false, error: `字段名过长（最多 ${MAX_FIELD_NAME} 字符）` }
  }
  if (FIELD_FORBIDDEN.test(trimmed)) {
    return { ok: false, error: '字段名不能包含 \\ / : * ? " < > | 或控制字符' }
  }
  if (/^\.+$/.test(trimmed)) {
    return { ok: false, error: '字段名无效' }
  }
  return { ok: true, value: trimmed }
}
