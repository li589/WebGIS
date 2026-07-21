/**
 * 风场纹理编码 — WindGrid → GPU 纹理数据。
 *
 * 编码方案（RGBA8，无扩展依赖，最大兼容）：
 *   R = u 分量编码：byte = round(((u / MAX) + 1) * 0.5 * 255)
 *   G = v 分量编码：同 R
 *   B = speed 编码：byte = round((speed / MAX) * 255)
 *   A = 数据掩码：255 = 有数据，0 = 无数据
 *
 * 预存 u/v（而非 speed/direction）的原因：采样 shader 直接做双线性插值即得
 * 向量，无需在 GPU 里做三角函数；与现有 CPU `interpolateWind` 在 (u,v) 空间
 * 插值的数学完全等价。
 *
 * 纹理布局：宽 = cols，高 = rows；texel (c, r) = points[r][c]；行序 北→南。
 * 上传时用 UNPACK_FLIP_Y_WEBGL=false，使 row 0（北）落在纹理 v=0，
 * shader 内 v_tex = (north - lat) / (north - south)（北 0 → 南 1）。
 *
 * 8 位量化说明：80 m/s 量程 / 256 级 ≈ 0.31 m/s 步进，对风场可视化（B2）足够；
 * 若 B3 平流出现可见阶梯，再升级为 float 纹理（OES_texture_float）。
 */
import { windToUV, type WindGrid } from './wind-grid'

/** 风速量程上限（m/s），覆盖 DEFAULT_WIND_SPEED_STOPS 的 35 m/s 上限并留余量 */
export const WIND_TEXTURE_MAX_WIND = 40

export interface EncodedWindTexture {
  data: Uint8Array
  /** 纹理宽（= cols） */
  width: number
  /** 纹理高（= rows） */
  height: number
  west: number
  south: number
  east: number
  north: number
}

/** 把单个 u/v 分量（m/s）编码为 [0,255] 字节。 */
function encodeComponent(value: number): number {
  const normalized = (value / WIND_TEXTURE_MAX_WIND + 1) * 0.5
  return Math.round(Math.max(0, Math.min(1, normalized)) * 255)
}

/** 把风速（m/s，非负）编码为 [0,255] 字节。 */
function encodeSpeed(speed: number): number {
  return Math.round(Math.max(0, Math.min(1, speed / WIND_TEXTURE_MAX_WIND)) * 255)
}

/**
 * 把风场网格编码为 RGBA8 像素数组。
 * 返回 Uint8Array，长度 = cols * rows * 4，行序 北→南。
 */
export function encodeWindGridToRGBA(grid: WindGrid): EncodedWindTexture {
  const { rows, cols, points } = grid
  const data = new Uint8Array(cols * rows * 4)
  for (let r = 0; r < rows; r++) {
    for (let c = 0; c < cols; c++) {
      const p = points[r][c]
      const idx = (r * cols + c) * 4
      if (!Number.isFinite(p.speed) || !Number.isFinite(p.direction)) {
        data[idx] = 0
        data[idx + 1] = 0
        data[idx + 2] = 0
        data[idx + 3] = 0
        continue
      }
      const [u, v] = windToUV(p.speed, p.direction)
      data[idx] = encodeComponent(u)
      data[idx + 1] = encodeComponent(v)
      data[idx + 2] = encodeSpeed(p.speed)
      data[idx + 3] = 255
    }
  }
  return {
    data,
    width: cols,
    height: rows,
    west: grid.west,
    south: grid.south,
    east: grid.east,
    north: grid.north,
  }
}

// ── LUT 调色板纹理（B5 使用，此处先提供编码 helper）────────────────

/**
 * 把一组 CSS 颜色（hex 字符串）展开为 256×1 RGBA LUT 像素数组。
 * 供 B5 配色纹理使用。
 */
export function buildPaletteLUT(colors: string[]): Uint8Array {
  const size = 256
  const data = new Uint8Array(size * 4)
  const parsed = colors
    .filter((c) => typeof c === 'string' && c.startsWith('#') && c.length >= 7)
    .map((c) => [
      parseInt(c.slice(1, 3), 16),
      parseInt(c.slice(3, 5), 16),
      parseInt(c.slice(5, 7), 16),
    ])
  if (parsed.length === 0) {
    // 缺省：透明 → 白 渐变
    for (let i = 0; i < size; i++) {
      const t = i / (size - 1)
      data[i * 4] = Math.round(242 + t * 13)
      data[i * 4 + 1] = Math.round(246 + t * 9)
      data[i * 4 + 2] = 255
      data[i * 4 + 3] = Math.round(t * 255)
    }
    return data
  }
  for (let i = 0; i < size; i++) {
    const ratio = i / (size - 1)
    const srcIdx = ratio * (parsed.length - 1)
    const lo = Math.floor(srcIdx)
    const hi = Math.min(lo + 1, parsed.length - 1)
    const frac = srcIdx - lo
    for (let ch = 0; ch < 3; ch++) {
      data[i * 4 + ch] = Math.round(parsed[lo][ch] + (parsed[hi][ch] - parsed[lo][ch]) * frac)
    }
    data[i * 4 + 3] = 255
  }
  return data
}
