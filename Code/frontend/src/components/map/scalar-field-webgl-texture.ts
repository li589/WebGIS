/**
 * 标量场纹理编码：R = 归一化值 [0,1]，A = 掩码；G/B 未用。
 * LUT 复用风场 `buildPaletteLUT`。
 */
import { buildPaletteLUT } from './wind-particle-webgl-texture'
import type { ScalarGrid } from './scalar-field-grid'

export { buildPaletteLUT }

export interface EncodedScalarTexture {
  data: Uint8Array
  width: number
  height: number
  west: number
  south: number
  east: number
  north: number
  minValue: number
  maxValue: number
}

export function encodeScalarGridToRGBA(
  grid: ScalarGrid,
  minValue: number,
  maxValue: number,
): EncodedScalarTexture {
  const { rows, cols, points } = grid
  const span = Math.max(1e-9, maxValue - minValue)
  const data = new Uint8Array(cols * rows * 4)
  for (let r = 0; r < rows; r++) {
    for (let c = 0; c < cols; c++) {
      const p = points[r][c]
      const idx = (r * cols + c) * 4
      if (!p.hasData) {
        data[idx] = 0
        data[idx + 1] = 0
        data[idx + 2] = 0
        data[idx + 3] = 0
        continue
      }
      const t = Math.max(0, Math.min(1, (p.value - minValue) / span))
      data[idx] = Math.round(t * 255)
      data[idx + 1] = 0
      data[idx + 2] = 0
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
    minValue,
    maxValue,
  }
}

/** 测试辅助：解码 R 通道归一化值 */
export function decodeScalarByte(byte: number): number {
  return Math.max(0, Math.min(1, byte / 255))
}
