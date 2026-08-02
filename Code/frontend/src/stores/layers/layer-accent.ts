/**
 * 已添加图层的实例级强调色：用于侧栏背景区分与时间轴主色。
 * 优先复用 catalog 建议色；若与已占用色过近则从调色板轮换。
 */

export const LAYER_ACCENT_PALETTE = [
  '#38bdf8',
  '#f97316',
  '#a78bfa',
  '#34d399',
  '#f472b6',
  '#fbbf24',
  '#22d3ee',
  '#fb7185',
  '#4ade80',
  '#e879f9',
  '#60a5fa',
  '#c084fc',
  '#2dd4bf',
  '#facc15',
  '#94a3b8',
] as const

export interface LayerAccentStyle {
  accentColor: string
  accentGlow: string
  chipTone: string
}

function hexToRgb(hex: string): [number, number, number] | null {
  const raw = hex.replace('#', '').trim()
  if (raw.length !== 6) return null
  const n = Number.parseInt(raw, 16)
  if (!Number.isFinite(n)) return null
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255]
}

function colorDistance(a: string, b: string): number {
  const ra = hexToRgb(a)
  const rb = hexToRgb(b)
  if (!ra || !rb) return 999
  const dr = ra[0] - rb[0]
  const dg = ra[1] - rb[1]
  const db = ra[2] - rb[2]
  return Math.sqrt(dr * dr + dg * dg + db * db)
}

function withDerivedTones(accentColor: string): LayerAccentStyle {
  const rgb = hexToRgb(accentColor)
  if (!rgb) {
    return {
      accentColor,
      accentGlow: 'rgba(103, 212, 255, 0.28)',
      chipTone: 'rgba(103, 212, 255, 0.16)',
    }
  }
  const [r, g, b] = rgb
  return {
    accentColor,
    accentGlow: `rgba(${r}, ${g}, ${b}, 0.32)`,
    chipTone: `rgba(${r}, ${g}, ${b}, 0.18)`,
  }
}

/** 在已占用色中挑选一个足够可区分的颜色 */
export function allocateLayerAccent(
  usedColors: Iterable<string>,
  preferred?: string | null,
): LayerAccentStyle {
  const used = [...usedColors].filter(Boolean)
  const pref = preferred?.trim()
  if (pref && used.every((c) => colorDistance(c, pref) > 48)) {
    return withDerivedTones(pref)
  }
  for (const candidate of LAYER_ACCENT_PALETTE) {
    if (used.every((c) => colorDistance(c, candidate) > 48)) {
      return withDerivedTones(candidate)
    }
  }
  const idx = used.length % LAYER_ACCENT_PALETTE.length
  return withDerivedTones(LAYER_ACCENT_PALETTE[idx] ?? '#38bdf8')
}
