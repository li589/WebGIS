/**
 * 登录页氛围色：按主题的 login_palette（仅登录页）解析 CSS 变量。
 * 品牌文案与 logo 来自 /auth/themes/public；此处不改应用内主题色。
 */

export type LoginPaletteId = 'cyan' | 'green' | 'warm' | 'violet' | 'slate'

export type LoginThemeCssVars = Record<`--${string}`, string>

export const LOGIN_PALETTE_OPTIONS: ReadonlyArray<{
  id: LoginPaletteId
  label: string
}> = [
  { id: 'cyan', label: '青蓝（默认）' },
  { id: 'green', label: '青绿（植被/生态）' },
  { id: 'warm', label: '暖土（土壤/干旱）' },
  { id: 'violet', label: '紫靛' },
  { id: 'slate', label: '冷灰' },
]

const CYAN_VARS: LoginThemeCssVars = {
  '--login-accent': '#5ad5ff',
  '--login-accent-strong': '#88dfff',
  '--login-accent-surface': 'rgba(90, 213, 255, 0.12)',
  '--login-accent-border': 'rgba(90, 213, 255, 0.3)',
  '--login-border-accent': 'rgba(90, 213, 255, 0.35)',
  '--login-glow-warm': 'rgba(255, 200, 120, 0.08)',
  '--login-title-base': '#f5fcff',
  '--login-title-accent-stop': '#9ce8ff',
}

const GREEN_VARS: LoginThemeCssVars = {
  '--login-accent': '#5dce8a',
  '--login-accent-strong': '#8fe0ad',
  '--login-accent-surface': 'rgba(93, 206, 138, 0.14)',
  '--login-accent-border': 'rgba(93, 206, 138, 0.35)',
  '--login-border-accent': 'rgba(72, 180, 120, 0.4)',
  '--login-glow-warm': 'rgba(160, 220, 120, 0.1)',
  '--login-title-base': '#f2fff6',
  '--login-title-accent-stop': '#a8ebc0',
}

const WARM_VARS: LoginThemeCssVars = {
  '--login-accent': '#ffc878',
  '--login-accent-strong': '#ffe4a8',
  '--login-accent-surface': 'rgba(255, 200, 120, 0.14)',
  '--login-accent-border': 'rgba(255, 200, 120, 0.35)',
  '--login-border-accent': 'rgba(255, 176, 112, 0.4)',
  '--login-glow-warm': 'rgba(255, 140, 100, 0.12)',
  '--login-title-base': '#fff8ef',
  '--login-title-accent-stop': '#ffe8b8',
}

const VIOLET_VARS: LoginThemeCssVars = {
  '--login-accent': '#b49cff',
  '--login-accent-strong': '#d0c2ff',
  '--login-accent-surface': 'rgba(180, 156, 255, 0.14)',
  '--login-accent-border': 'rgba(180, 156, 255, 0.35)',
  '--login-border-accent': 'rgba(160, 130, 255, 0.4)',
  '--login-glow-warm': 'rgba(220, 160, 255, 0.1)',
  '--login-title-base': '#f8f5ff',
  '--login-title-accent-stop': '#d8ccff',
}

const SLATE_VARS: LoginThemeCssVars = {
  '--login-accent': '#9eb0c4',
  '--login-accent-strong': '#c2cfde',
  '--login-accent-surface': 'rgba(158, 176, 196, 0.14)',
  '--login-accent-border': 'rgba(158, 176, 196, 0.35)',
  '--login-border-accent': 'rgba(140, 160, 184, 0.4)',
  '--login-glow-warm': 'rgba(180, 200, 220, 0.1)',
  '--login-title-base': '#f4f7fb',
  '--login-title-accent-stop': '#c8d4e4',
}

const PALETTE_PRESETS: Record<LoginPaletteId, LoginThemeCssVars> = {
  cyan: CYAN_VARS,
  green: GREEN_VARS,
  warm: WARM_VARS,
  violet: VIOLET_VARS,
  slate: SLATE_VARS,
}

/** 历史 slug → palette（兼容旧调用与未带 login_palette 的回退） */
const SLUG_PALETTE_FALLBACK: Record<string, LoginPaletteId> = {
  sgfs: 'cyan',
  'warm-soil': 'warm',
}

function hashHue(slug: string): number {
  let h = 0
  for (let i = 0; i < slug.length; i += 1) {
    h = (h * 31 + slug.charCodeAt(i)) >>> 0
  }
  return h % 360
}

function derivePresetFromSlug(slug: string): LoginThemeCssVars {
  const hue = hashHue(slug.trim().toLowerCase())
  return {
    '--login-accent': `hsl(${hue} 78% 68%)`,
    '--login-accent-strong': `hsl(${hue} 85% 78%)`,
    '--login-accent-surface': `hsla(${hue}, 78%, 68%, 0.12)`,
    '--login-accent-border': `hsla(${hue}, 78%, 68%, 0.3)`,
    '--login-border-accent': `hsla(${hue}, 78%, 68%, 0.35)`,
    '--login-glow-warm': `hsla(${(hue + 40) % 360}, 70%, 60%, 0.1)`,
    '--login-title-base': '#f5fcff',
    '--login-title-accent-stop': `hsl(${hue} 70% 80%)`,
  }
}

function withAccentAliases(preset: LoginThemeCssVars): LoginThemeCssVars {
  return {
    ...preset,
    '--accent': preset['--login-accent'],
    '--accent-strong': preset['--login-accent-strong'],
    '--accent-surface': preset['--login-accent-surface'],
    '--accent-border': preset['--login-accent-border'],
    '--border-accent': preset['--login-border-accent'],
  }
}

export function normalizeLoginPalette(
  value: string | null | undefined,
): LoginPaletteId | null {
  const key = value?.trim().toLowerCase()
  if (key && key in PALETTE_PRESETS) return key as LoginPaletteId
  return null
}

/**
 * 解析登录页 CSS 变量。优先 login_palette；否则按已知 slug 回退，再否则按 slug hash 派生。
 */
export function resolveLoginThemeStyle(
  slugOrPalette?: string | null,
  loginPalette?: string | null,
): LoginThemeCssVars {
  const fromPalette = normalizeLoginPalette(loginPalette)
  if (fromPalette) return withAccentAliases(PALETTE_PRESETS[fromPalette])

  const key = slugOrPalette?.trim().toLowerCase() || 'sgfs'
  const asPalette = normalizeLoginPalette(key)
  if (asPalette) return withAccentAliases(PALETTE_PRESETS[asPalette])

  const fromSlug = SLUG_PALETTE_FALLBACK[key]
  if (fromSlug) return withAccentAliases(PALETTE_PRESETS[fromSlug])

  return withAccentAliases(derivePresetFromSlug(key))
}
