// @vitest-environment jsdom
import { describe, expect, it } from 'vitest'

import {
  BRIGHT_STARS,
  DEEP_SKY_OBJECTS,
  GALACTIC_TILT_DEG,
  galacticToEquatorial,
  mulberry32,
  renderStarfieldCanvas,
  starfieldVisual,
} from '@/components/map/globe-starfield'

describe('starfieldVisual', () => {
  it('暗色主题比浅色主题背景星更多更亮', () => {
    const dark = starfieldVisual('dark')
    const light = starfieldVisual('light')
    expect(dark.bgStarCount).toBeGreaterThan(light.bgStarCount)
    expect(dark.bgStarAlphaMax).toBeGreaterThan(light.bgStarAlphaMax)
    expect(dark.showDeepSky).toBe(true)
    expect(light.showDeepSky).toBe(false)
  })

  it('浅色主题不画尘埃暗带（避免浅色 UI 上显得脏）', () => {
    expect(starfieldVisual('dark').dustBandCount).toBeGreaterThan(0)
    expect(starfieldVisual('light').dustBandCount).toBe(0)
  })

  it('浅色主题各 alpha 上限受到严格压制（浅色 UI 下不突兀���', () => {
    const light = starfieldVisual('light')
    expect(light.bgStarAlphaMax).toBeLessThanOrEqual(0.25)
    expect(light.galaxyAlphaMax).toBeLessThanOrEqual(0.16)
  })

  it('glowStarBoost 控制亮星光芒强度（暗色强、浅色弱）', () => {
    expect(starfieldVisual('dark').glowStarBoost).toBeGreaterThan(
      starfieldVisual('light').glowStarBoost,
    )
  })
})

describe('真实亮星表 BRIGHT_STARS', () => {
  it('包含一定数量的肉眼可观测亮星', () => {
    expect(BRIGHT_STARS.length).toBeGreaterThanOrEqual(55)
    expect(BRIGHT_STARS.length).toBeLessThan(120)
  })

  it('最亮的几颗符合已知数据（天狼星/老人星/织女星等）', () => {
    const sirius = BRIGHT_STARS.find((s) => s.name === 'Sirius')!
    expect(sirius.mag).toBeCloseTo(-1.46, 1)
    expect(sirius.raHours).toBeGreaterThan(6.6)
    expect(sirius.raHours).toBeLessThan(6.9)
    const vega = BRIGHT_STARS.find((s) => s.name === 'Vega')!
    expect(vega.mag).toBeLessThan(0.1)
    expect(vega.decDeg).toBeGreaterThan(38)
    const canopus = BRIGHT_STARS.find((s) => s.name === 'Canopus')!
    expect(canopus.decDeg).toBeLessThan(-50) // 南天明星
  })

  it('每颗星的 RA 在 [0, 24) 范围、Dec 在 [-90, +90]、mag 在合理区间', () => {
    for (const s of BRIGHT_STARS) {
      expect(s.raHours).toBeGreaterThanOrEqual(0)
      expect(s.raHours).toBeLessThan(24)
      expect(s.decDeg).toBeGreaterThanOrEqual(-90)
      expect(s.decDeg).toBeLessThanOrEqual(90)
      expect(s.mag).toBeGreaterThanOrEqual(-2)
      expect(s.mag).toBeLessThanOrEqual(3)
      expect(['O', 'B', 'A', 'F', 'G', 'K', 'M']).toContain(s.spectral)
    }
  })

  it('北极星 (Polaris) 在赤纬 +89° 附近', () => {
    const polaris = BRIGHT_STARS.find((s) => s.name === 'Polaris')!
    expect(polaris.decDeg).toBeGreaterThan(89)
  })
})

describe('真实深空天体 DEEP_SKY_OBJECTS', () => {
  it('包含 LMC/SMC（南天麦哲伦云）/ M31（仙女座）/ M42（猎户）/ M45（昴星团）', () => {
    const names = DEEP_SKY_OBJECTS.map((o) => o.name)
    expect(names).toContain('LMC')
    expect(names).toContain('SMC')
    expect(names).toContain('M31')
    expect(names).toContain('M42')
    expect(names).toContain('M45')
  })

  it('LMC 在南天（赤纬 < -60°）', () => {
    const lmc = DEEP_SKY_OBJECTS.find((o) => o.name === 'LMC')!
    expect(lmc.decDeg).toBeLessThan(-60)
  })

  it('M31 仙女座星系在北半天球', () => {
    const m31 = DEEP_SKY_OBJECTS.find((o) => o.name === 'M31')!
    expect(m31.decDeg).toBeGreaterThan(0)
  })
})

describe('银河几何 galacticToEquatorial（J2000 银道→赤道）', () => {
  it('银心方向 (l=0, b=0) → RA 266.4° / Dec -28.94°（人马座方向）', () => {
    const { raHours, decDeg } = galacticToEquatorial(0, 0)
    const raDeg = raHours * 15
    expect(raDeg).toBeCloseTo(266.4, 0)
    expect(decDeg).toBeCloseTo(-28.9, 0)
  })

  it('北银极 (l 任意, b=+90) → RA 192.86° / Dec +27.13°', () => {
    const { raHours, decDeg } = galacticToEquatorial(0, 90)
    const raDeg = raHours * 15
    expect(raDeg).toBeCloseTo(192.86, 0)
    expect(decDeg).toBeCloseTo(27.13, 0)
  })

  it('银道倾角常量符合 IAU 1958 标准（62.87°）', () => {
    expect(GALACTIC_TILT_DEG).toBeCloseTo(62.87, 1)
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
    expect(() => renderStarfieldCanvas({ mode: 'full', width: 256, seed: 1 })).not.toThrow()
    expect(() => renderStarfieldCanvas({ mode: 'soft', width: 256, seed: 1 })).not.toThrow()
  })

  it('默认画布为 2:1 比例', () => {
    const canvas = renderStarfieldCanvas({ mode: 'minimal' })
    expect(canvas.height).toBe(Math.round(canvas.width / 2))
  })
})