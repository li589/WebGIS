/** 产品品牌文案 — 与 About / 工具栏保持同一套；可用 VITE_BRAND_* 构建期白标覆盖 */

function envTrim(key: string): string | undefined {
  const raw = (import.meta.env as Record<string, unknown>)[key]
  if (typeof raw !== 'string') return undefined
  const trimmed = raw.trim()
  return trimmed || undefined
}

export const BRAND = {
  /** 工具栏短标题 */
  shortName: envTrim('VITE_BRAND_SHORT_NAME') ?? '综合地理态势',
  /** About / 文档全称 */
  fullName: envTrim('VITE_BRAND_FULL_NAME') ?? '综合地理态势分析系统',
  /** 眉题（技术代号，弱化展示） */
  eyebrow: envTrim('VITE_BRAND_EYEBROW') ?? 'CGDA',
} as const

/** 侧栏/分类机构叙事标签（默认「科研」） */
export const ORG_LABEL = envTrim('VITE_ORG_LABEL') ?? '科研'
