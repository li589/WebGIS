// @vitest-environment jsdom
import { describe, expect, it } from 'vitest'

import { mulberry32, renderStarfieldCanvas, starfieldVisual } from '@/components/map/globe-starfield'

describe('starfieldVisual', () => {
  it('暗色主题比浅色主题星星更多更亮', () => {
    const dark = starfieldVisual('dark')
    const light = starfieldVisual('light')
    expect(dark.starCount).toBeGreaterThan(light.starCount)
    expect(dark.starAlphaMax).toBeGreaterThan(light.starAlphaMax)
    expect(dark.glowStarCount).toBeGreaterThan(0)
    expect(light.glowStarCount).toBe(0)
  })

  it('暗色主题包含尘埃暗带，浅色不包含', () => {
    expect(starfieldVisual('dark').dustBandCount).toBeGreaterThan(0)
    expect(starfieldVisual('light').dustBandCount).toBe(0)
  })

  it('浅色主题各 alpha 上限受到严格压制（浅色 UI 下不突兀）', () => {
    const light = starfieldVisual('light')
    expect(light.starAlphaMax).toBeLessThanOrEqual(0.25)
    expect(light.galaxyAlphaMax).toBeLessThanOrEqual(0.13)
    expect(light.nebulaAlphaMax).toBeLessThanOrEqual(0.05)
  })
})

describe('mulberry32', () => {
  it('固定种子产生可复现序列', () => {
    const a = mulberry32(42)
    const b = mulberry32(42)
    const seqA = Array.from({ length: 8 }, () => a())
    const seqB = Array.from({ length: 8 }, () => b())
    expect(seqA).toEqual(seqB)
  })

  it('输出始终在 [0, 1) 区间', () => {
    const rng = mulberry32(7)
    for (let i = 0; i < 200; i++) {
      const v = rng()
      expect(v).toBeGreaterThanOrEqual(0)
      expect(v).toBeLessThan(1)
    }
  })
})

describe('renderStarfieldCanvas', () => {
  it('minimal 模式返回透明空画布（正确尺寸）', () => {
    const canvas = renderStarfieldCanvas({ mode: 'minimal', width: 320, seed: 1 })
    expect(canvas.width).toBe(320)
    expect(canvas.height).toBe(160)
  })

  it('full/soft 模式在不支持 2d 上下文的环境下不抛错', () => {
    // jsdom 无 canvas 实现时 getContext 返回 null，函数应返回透明画布
    expect(() => renderStarfieldCanvas({ mode: 'full', width: 256, seed: 1 })).not.toThrow()
    expect(() => renderStarfieldCanvas({ mode: 'soft', width: 256, seed: 1 })).not.toThrow()
  })

  it('默认画布为 2:1 比例', () => {
    const canvas = renderStarfieldCanvas({ mode: 'minimal' })
    expect(canvas.height).toBe(Math.round(canvas.width / 2))
  })
})
