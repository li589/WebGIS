/**
 * 产品品牌文案 — 与 About / 工具栏 / 登录页保持同一套；可用 VITE_BRAND_* 构建期白标覆盖。
 *
 * ── 品牌沿革 ──────────────────────────────────────────────────────────────
 * 2026-08 验收更名：由「综合地理态势分析系统」（代号 CGDA/CGDAS）更名为
 * 「星地融合土壤水分监测与干旱预警系统」。
 *   - 浏览器标签栏（document.title）：中文全称
 *   - 界面显示：以「星地融合土壤数据平台」+ 英文缩写 SGFS 为主
 *   - 英文显示名：Star-Ground Fusion Soil Data Platform
 *
 * 回退方案：将 BRAND 各字段恢复为下方 LEGACY_BRAND 的取值即可（favicon 与
 * 登录页视觉需同步换回 git 历史中 public/favicon.svg 的 CGDA 版本）。
 */

function envTrim(key: string): string | undefined {
  const raw = (import.meta.env as Record<string, unknown>)[key]
  if (typeof raw !== 'string') return undefined
  const trimmed = raw.trim()
  return trimmed || undefined
}

export const BRAND = {
  /** 工具栏/登录页短标题（界面主显示名） */
  shortName: envTrim('VITE_BRAND_SHORT_NAME') ?? '星地融合土壤数据平台',
  /** About / 浏览器标签栏中文全称 */
  fullName: envTrim('VITE_BRAND_FULL_NAME') ?? '星地融合土壤水分监测与干旱预警系统',
  /** 英文显示名 */
  displayNameEn: envTrim('VITE_BRAND_DISPLAY_NAME_EN') ?? 'Star-Ground Fusion Soil Data Platform',
  /** 英文缩写（界面主标识，替代旧技术代号） */
  abbr: envTrim('VITE_BRAND_ABBR') ?? 'SGFS',
  /** 眉题（缩写展示，弱化） */
  eyebrow: envTrim('VITE_BRAND_EYEBROW') ?? 'SGFS',
} as const

/**
 * 旧品牌（2026-08 前使用）— 仅作回退参考保留，勿在新界面引用。
 * 综合(Comprehensive) 地理(Geographic) 态势/数据(Data) 分析(Analysis) 系统(System)。
 */
export const LEGACY_BRAND = {
  shortName: '综合地理态势',
  fullName: '综合地理态势分析系统',
  eyebrow: 'CGDA',
  legacyAbbr: 'CGDA / CGDAS',
} as const

/** 侧栏/分类机构叙事标签（默认「科研」） */
export const ORG_LABEL = envTrim('VITE_ORG_LABEL') ?? '科研'
