/**
 * 登录页按产品主题（slug）切换 accent / 光晕等视觉变量。
 * 品牌文案与 logo 来自 /auth/themes/public；此处仅负责未登录时的氛围色。
 */
export type LoginThemeCssVars = Record<`--${string}`, string>

const SGFS_VARS: LoginThemeCssVars = {
  '--login-accent': '#5ad5ff',
  '--login-accent-strong': '#88dfff',
  '--login-accent-surface': 'rgba(90, 213, 255, 0.12)',
  '--login-accent-border': 'rgba(90, 213, 255, 0.3)',
  '--login-border-accent': 'rgba(90, 213, 255, 0.35)',
  '--login-glow-warm': 'rgba(255, 200, 120, 0.08)',
  '--login-title-base': '#f5fcff',
  '--login-title-accent-stop': '#9ce8ff',
}

/** 已知第二产品线的示例预设（暖色），便于与 SGFS 青色系区分。 */
const WARM_SOIL_VARS: LoginThemeCssVars = {
  '--login-accent': '#ffc878',
  '--login-accent-strong': '#ffe4a8',
  '--login-accent-surface': 'rgba(255, 200, 120, 0.14)',
  '--login-accent-border': 'rgba(255, 200, 120, 0.35)',
  '--login-border-accent': 'rgba(255, 176, 112, 0.4)',
  '--login-glow-warm': 'rgba(255, 140, 100, 0.12)',
  '--login-title-base': '#fff8ef',
  '--login-title-accent-stop': '#ffe8b8',
}

const KNOWN_PRESETS: Record<string, LoginThemeCssVars> = {
  sgfs: SGFS_VARS,
  'warm-soil': WARM_SOIL_VARS,
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

export function resolveLoginThemeStyle(slug: string | null | undefined): LoginThemeCssVars {
  const key = slug?.trim().toLowerCase() || 'sgfs'
  const preset = KNOWN_PRESETS[key] ?? derivePresetFromSlug(key)
  return {
    ...preset,
    '--accent': preset['--login-accent'],
    '--accent-strong': preset['--login-accent-strong'],
    '--accent-surface': preset['--login-accent-surface'],
    '--accent-border': preset['--login-accent-border'],
    '--border-accent': preset['--login-border-accent'],
  }
}
