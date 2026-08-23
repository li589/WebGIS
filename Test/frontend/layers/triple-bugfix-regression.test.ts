/**
 * 三联报障（续）回归锁（2026-08-24）：
 * A. 图层名泄漏产物文件名——normalizeProductTag 全串大写 + productTagLabel
 *    未知 tag 透传，'landcover_025.mat' 曾以 'LANDCOVER_025.MAT' 整体成为
 *    图层显示名。现 productTagLabel 未知 tag 剥数据扩展名。
 * C. 色带误兜底——后端色带全集（brg/plasma/terrain 等）大于前端可选集，
 *    旧 resolvePaletteId 兜底成 thermal-orange，导致"当前/默认配色"误判，
 *    用户显式选热力橙红被存 null 吞掉（渲染仍 viridis = "两配色一样"）。
 *    现 paletteIdsEqual / 严格 canonical 均不兜底。
 */
import { describe, expect, it } from 'vitest'
import {
  paletteIdsEqual,
  resolveCanonicalPaletteId,
  resolveCanonicalPaletteIdStrict,
} from '@/components/map/weather-render'
import { productTagLabel } from '@/utils/workflow-expected-outputs'

describe('三联报障 A：图层名不泄漏产物文件名', () => {
  it('未知 tag 剥数据扩展名（大写）', () => {
    expect(productTagLabel('LANDCOVER_025.MAT')).toBe('LANDCOVER_025')
    expect(productTagLabel('ARIDITY_025.TIF')).toBe('ARIDITY_025')
    expect(productTagLabel('OMEGA_BLOCK_D017.PNG')).toBe('OMEGA_BLOCK_D017')
  })

  it('已知 tag 不受影响', () => {
    expect(productTagLabel('SM')).toBe('SM')
    expect(productTagLabel('VOD')).toBe('VOD')
    expect(productTagLabel('OMEGA')).toBe('ω')
  })

  it('无扩展名未知 tag 原样透传', () => {
    expect(productTagLabel('SOMETHING')).toBe('SOMETHING')
  })
})

describe('三联报障 C：色带默认/相等判定不兜底 thermal-orange', () => {
  it('严格版：后端专属科学色带原样返回', () => {
    expect(resolveCanonicalPaletteIdStrict('brg')).toBe('brg')
    expect(resolveCanonicalPaletteIdStrict('plasma')).toBe('plasma')
    expect(resolveCanonicalPaletteIdStrict('terrain')).toBe('terrain')
    expect(resolveCanonicalPaletteIdStrict('ylgnbu')).toBe('ylgnbu')
  })

  it('严格版：前端色带与别名照常归一', () => {
    expect(resolveCanonicalPaletteIdStrict('orange-red')).toBe('thermal-orange')
    expect(resolveCanonicalPaletteIdStrict('viridis')).toBe('viridis')
  })

  it('渲染版仍兜底 thermal-orange（可见性语义保留）', () => {
    expect(resolveCanonicalPaletteId('brg')).toBe('thermal-orange')
  })

  it('未知后端色带 ≠ 任何前端可选项（显式选择必写覆盖）', () => {
    expect(paletteIdsEqual('thermal-orange', 'brg')).toBe(false)
    expect(paletteIdsEqual('viridis', 'plasma')).toBe(false)
    expect(paletteIdsEqual('thermal-orange', 'viridis')).toBe(false)
    expect(paletteIdsEqual('orange-red', 'thermal-orange')).toBe(true)
  })
})
