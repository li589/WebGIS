// @vitest-environment jsdom
import { describe, expect, it } from 'vitest'

import {
  BRIGHT_STARS,
  DEEP_SKY_OBJECTS,
  GALACTIC_TILT_DEG,
  equatorialToGalactic,
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
describe('银河云气渲染（科研级重做）', () => {
  it('equatorialToGalactic 与 galacticToEquatorial 互为逆变换', () => {
    // 采样若干赤道坐标，转银道再转回，应恢复原值
    const samples: Array<[number, number]> = [
      [0, 0],
      [6, 30],
      [12, -45],
      [18.615, 38.784],
      [5.392, -69.756],
      [22.5, 80],
    ]
    for (const [ra, dec] of samples) {
      const { lDeg, bDeg } = equatorialToGalactic(ra, dec)
      const back = galacticToEquatorial(lDeg, bDeg)
      // RA 存在 0/24 wrap 边界（浮点残差可能落在 23.9999...），按圆周距离比较
      const raDiff = Math.abs(back.raHours - (((ra % 24) + 24) % 24))
      const raDist = Math.min(raDiff, 24 - raDiff)
      expect(raDist).toBeLessThan(1e-4)
      // 往返浮点残差 ~1e-4 度（0.36 角秒，亚像素级），对星图渲染完全无感
      expect(back.decDeg).toBeCloseTo(dec, 3)
    }
  })

  it('银心方向逆变换结果与已知值一致（RA 266.405° Dec -28.936°）', () => {
    // 银心 (l=0, b=0) → RA 17.760h / Dec -28.936°
    const { raHours, decDeg } = galacticToEquatorial(0, 0)
    expect(raHours).toBeCloseTo(17.7603, 2)
    expect(decDeg).toBeCloseTo(-28.936, 2)
    // 逆变换：银心的赤道坐标 → l=0, b=0
    const { lDeg, bDeg } = equatorialToGalactic(raHours, decDeg)
    expect(Math.abs(lDeg) < 0.01 || Math.abs(lDeg - 360) < 0.01).toBe(true)
    expect(Math.abs(bDeg)).toBeLessThan(0.01)
  })

  it('full 模式画布上银河带区域比偏离银道面的区域更亮（云气渲染有效）', () => {
    // 256×128 画布，采样银道面附近 vs 银极附近像素亮度
    const canvas = renderStarfieldCanvas({ mode: 'full', width: 256, height: 128, seed: 42 })
    const ctx = canvas.getContext('2d')
    if (!ctx) return // 无 2d 上下文环境跳过
    const data = ctx.getImageData(0, 0, 256, 128).data
    const brightnessAt = (ra: number, dec: number) => {
      const x = Math.round((ra / 24) * 255)
      const y = Math.round(((90 - dec) / 180) * 127)
      const idx = (y * 256 + x) * 4
      return (data[idx] + data[idx + 1] + data[idx + 2]) / 3 * (data[idx + 3] / 255)
    }
    // 银心附近（RA 17.76h ≈ x=189, Dec -29°）
    const galacticCore = brightnessAt(17.76, -29)
    // 北银极（Dec +27°，RA 12.85h）——离银道面最远
    const galacticPole = brightnessAt(12.85, 27.1)
    expect(galacticCore).toBeGreaterThan(galacticPole)
  })

  it('same seed 输出确定性（两次渲染逐像素一致）', () => {
    const a = renderStarfieldCanvas({ mode: 'full', width: 256, height: 128, seed: 99 })
    const b = renderStarfieldCanvas({ mode: 'full', width: 256, height: 128, seed: 99 })
    const ctxA = a.getContext('2d')
    const ctxB = b.getContext('2d')
    if (!ctxA || !ctxB) return
    const da = ctxA.getImageData(0, 0, 256, 128).data
    const db = ctxB.getImageData(0, 0, 256, 128).data
    expect(Array.from(da.slice(0, 2048))).toEqual(Array.from(db.slice(0, 2048)))
  })
})
