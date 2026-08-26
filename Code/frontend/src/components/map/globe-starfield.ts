/**
 * 程序化深空星图生成器（纯函数，可单测）。
 *
 * 不引入图片资源，用 Canvas 2D 按参数生成：
 * - 星星：随机分布 + 少数亮星带十字光芒
 * - 银河：沿对角带的高斯点云（亮核 + 弥散外层）
 * - 星系/星云：2-3 团椭圆径向渐变
 * - 尘埃暗带：沿银河走向的深色低 alpha 条纹（增加真实感）
 *
 * 主题感知：dark 完整深空星图；light 淡化为一层「晴空微尘」（星星变少变浅、
 * 银河变成淡蓝白光带），保证浅色 UI 下不突兀。
 */

export type StarfieldMode = 'full' | 'soft' | 'minimal'

export interface StarfieldOptions {
  /** full=完整深空星图；soft=浅色淡化微尘；minimal=不生成（空背景） */
  mode: StarfieldMode
  /** 画布宽度（默认 1024，2:1 比例） */
  width?: number
  height?: number
  /** 随机种子（默认随机；测试注入固定种子保证稳定） */
  seed?: number
}

/** mulberry32：可复现的轻量伪随机数发生器 */
export function mulberry32(seed: number): () => number {
  let a = seed >>> 0
  return () => {
    a |= 0
    a = (a + 0x6d2b79f5) | 0
    let t = Math.imul(a ^ (a >>> 15), 1 | a)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

export interface StarfieldVisual {
  starCount: number
  starAlphaMin: number
  starAlphaMax: number
  glowStarCount: number
  galaxyAlphaMax: number
  nebulaAlphaMax: number
  dustBandCount: number
}

/** 主题 → 视觉强度参数（供测试与组件共用） */
export function starfieldVisual(theme: 'dark' | 'light'): StarfieldVisual {
  if (theme === 'dark') {
    return {
      starCount: 460,
      starAlphaMin: 0.2,
      starAlphaMax: 0.95,
      glowStarCount: 12,
      galaxyAlphaMax: 0.32,
      nebulaAlphaMax: 0.11,
      dustBandCount: 3,
    }
  }
  return {
    starCount: 200,
    starAlphaMin: 0.06,
    starAlphaMax: 0.24,
    glowStarCount: 0,
    galaxyAlphaMax: 0.12,
    nebulaAlphaMax: 0.04,
    dustBandCount: 0,
  }
}

function drawGalaxy(
  ctx: CanvasRenderingContext2D,
  w: number,
  h: number,
  rng: () => number,
  theme: 'dark' | 'light',
  visual: StarfieldVisual,
): void {
  const x0 = w * 0.18
  const y0 = h * 0.68
  const x1 = w * 0.86
  const y1 = h * 0.3
  const bandHalf = h * 0.16
  const points = theme === 'dark' ? 520 : 260

  // 弥散外层：沿带中心线高斯散布的淡蓝点
  for (let i = 0; i < points; i++) {
    const t = rng()
    const px = x0 + (x1 - x0) * t
    const py = y0 + (y1 - y0) * t
    const off = (rng() - 0.5) * 2 * bandHalf
    const offY = Math.sin(((t - 0.5) * Math.PI) / 1) // 中心亮、两端收
    const a = (0.03 + rng() * 0.1) * Math.abs(Math.cos(t * Math.PI)) * 2
    if (a < 0.012) continue
    ctx.fillStyle =
      theme === 'dark'
        ? `rgba(214, 226, 255, ${a})`
        : `rgba(223, 231, 245, ${a * 0.8})`
    const r = 0.5 + rng() * (theme === 'dark' ? 2.2 : 1.6)
    ctx.beginPath()
    ctx.arc(px + off * 1.4, py + off * 0.6 - offY * h * 0.02, r, 0, Math.PI * 2)
    ctx.fill()
  }

  // 亮核：中心线附近的密集小星（银河最亮段）
  const corePoints = theme === 'dark' ? 180 : 60
  for (let i = 0; i < corePoints; i++) {
    const t = rng()
    const px = x0 + (x1 - x0) * t
    const py = y0 + (y1 - y0) * t
    const off = (rng() - 0.5) * 2 * bandHalf * 0.28
    const a = 0.08 + rng() * visual.galaxyAlphaMax * 0.9
    ctx.fillStyle =
      theme === 'dark'
        ? `rgba(240, 246, 255, ${a})`
        : `rgba(240, 246, 252, ${a * 0.7})`
    const r = 0.3 + rng() * 1.1
    ctx.beginPath()
    ctx.arc(px + off * 1.3, py + off * 0.55, r, 0, Math.PI * 2)
    ctx.fill()
  }

  // 尘埃暗带：沿银河走向的深色低 alpha 宽线（仅暗色主题，增强层次）
  for (let b = 0; b < visual.dustBandCount; b++) {
    const shift = (b - (visual.dustBandCount - 1) / 2) * bandHalf * 0.22
    ctx.strokeStyle = 'rgba(0, 0, 0, 0.05)'
    ctx.lineWidth = bandHalf * (0.16 + rng() * 0.14)
    ctx.lineCap = 'round'
    ctx.beginPath()
    ctx.moveTo(x0, y0 + shift)
    ctx.quadraticCurveTo(w * 0.5, h * 0.62 + shift, x1, y1 + shift)
    ctx.stroke()
  }
}

function drawNebula(
  ctx: CanvasRenderingContext2D,
  w: number,
  h: number,
  rng: () => number,
  theme: 'dark' | 'light',
  visual: StarfieldVisual,
): void {
  const palettes: Array<[string, string]> = theme === 'dark'
    ? [
        ['rgba(106, 92, 255,', 'rgba(70, 60, 180,'], // 蓝紫
        ['rgba(255, 122, 217,', 'rgba(180, 70, 150,'], // 粉
        ['rgba(77, 200, 255,', 'rgba(50, 130, 190,'], // 青
      ]
    : [
        ['rgba(160, 150, 235,', 'rgba(180, 175, 225,'],
        ['rgba(225, 190, 230,', 'rgba(215, 200, 225,'],
      ]
  const spots = theme === 'dark' ? 3 : 2
  for (let i = 0; i < spots; i++) {
    const [core, edge] = palettes[i % palettes.length]
    const cx = w * (0.2 + rng() * 0.6)
    const cy = h * (0.18 + rng() * 0.6)
    const rx = w * (0.08 + rng() * 0.1)
    const ry = rx * (0.45 + rng() * 0.3)
    const alpha = 0.5 + rng() * 0.5
    const grad = ctx.createRadialGradient(cx, cy, 0, cx, cy, Math.max(rx, ry))
    grad.addColorStop(0, `${core} ${(0.02 + rng() * 0.03) * (visual.nebulaAlphaMax / 0.11)})`)
    grad.addColorStop(0.55, `${edge} ${0.5 * alpha * (visual.nebulaAlphaMax / 0.11) * 0.5})`)
    grad.addColorStop(1, `${edge} 0)`)
    ctx.fillStyle = grad
    ctx.beginPath()
    ctx.ellipse(cx, cy, rx, ry, rng() * Math.PI, 0, Math.PI * 2)
    ctx.fill()
  }
}

function drawGlowStar(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  r: number,
  color: string,
  alpha: number,
): void {
  const len = r * 7
  // 中心点
  ctx.fillStyle = color
  ctx.globalAlpha = alpha
  ctx.beginPath()
  ctx.arc(x, y, r, 0, Math.PI * 2)
  ctx.fill()
  // 十字光芒
  ctx.strokeStyle = color
  ctx.lineWidth = Math.max(0.6, r * 0.4)
  ctx.lineCap = 'round'
  ctx.globalAlpha = alpha * 0.55
  ctx.beginPath()
  ctx.moveTo(x - len, y)
  ctx.lineTo(x + len, y)
  ctx.moveTo(x, y - len)
  ctx.lineTo(x, y + len)
  ctx.stroke()
  ctx.globalAlpha = 1
}

/** 生成星图 canvas（2:1 比例默认 1024×512）。minimal 模式返回透明空画布。 */
export function renderStarfieldCanvas(options: StarfieldOptions): HTMLCanvasElement {
  const width = options.width ?? 1024
  const height = options.height ?? Math.round(width / 2)
  const canvas = document.createElement('canvas')
  canvas.width = width
  canvas.height = height
  const ctx = canvas.getContext('2d')
  if (!ctx) return canvas // 无 2d 上下文（极端环境）时返回透明画布

  if (options.mode === 'minimal') return canvas

  const theme: 'dark' | 'light' = options.mode === 'full' ? 'dark' : 'light'
  const visual = starfieldVisual(theme)
  const rng = mulberry32(options.seed ?? (Math.random() * 0xffffffff) >>> 0)

  // 银河（先画，星星叠其上）
  drawGalaxy(ctx, width, height, rng, theme, visual)
  drawNebula(ctx, width, height, rng, theme, visual)

  // 星星
  const palette = theme === 'dark'
    ? ['#ffffff', '#e8f0ff', '#cfddff', '#fff3dd']
    : ['#8ea0c0', '#a8b6d0', '#bcc8de', '#e8ecf4']
  for (let i = 0; i < visual.starCount; i++) {
    const x = rng() * width
    const y = rng() * height
    const r = 0.35 + rng() * (theme === 'dark' ? 1.25 : 0.9)
    const alpha = visual.starAlphaMin + rng() * (visual.starAlphaMax - visual.starAlphaMin)
    const color = palette[Math.floor(rng() * palette.length)]
    ctx.fillStyle = color
    ctx.globalAlpha = alpha
    ctx.beginPath()
    ctx.arc(x, y, r, 0, Math.PI * 2)
    ctx.fill()
  }
  ctx.globalAlpha = 1

  // 亮星十字光芒（仅暗色主题）
  for (let i = 0; i < visual.glowStarCount; i++) {
    const x = rng() * width
    const y = rng() * height
    const r = 1.5 + rng() * 1.2
    const alpha = 0.55 + rng() * 0.4
    const color = palette[Math.floor(rng() * 2)]
    drawGlowStar(ctx, x, y, r, color, alpha)
  }

  return canvas
}
