import { describe, expect, it } from 'vitest'

import {
  classifyBasemapBrightness,
  daylightFactor,
  resolveGlobeLighting,
  resolveGlobeSky,
  subsolarDeclination,
  subsolarLongitude,
} from '@/components/map/globe-scene-utils'

describe('classifyBasemapBrightness', () => {
  it('街道/矢量等亮色底图归为 light（易过曝）', () => {
    expect(classifyBasemapBrightness('street')).toBe('light')
    expect(classifyBasemapBrightness(undefined)).toBe('light')
    expect(classifyBasemapBrightness('none')).toBe('light')
  })

  it('影像与地形归为 medium', () => {
    expect(classifyBasemapBrightness('satellite')).toBe('medium')
    expect(classifyBasemapBrightness('terrain')).toBe('medium')
  })

  it('暗色底图归为 dark', () => {
    expect(classifyBasemapBrightness('dark')).toBe('dark')
  })
})

describe('daylightFactor', () => {
  it('正午最强、午夜最弱、晨昏过渡平滑', () => {
    expect(daylightFactor(12)).toBeCloseTo(1)
    expect(daylightFactor(0)).toBeCloseTo(0)
    expect(daylightFactor(24)).toBeCloseTo(0)
    const morning = daylightFactor(9)
    expect(morning).toBeGreaterThan(0)
    expect(morning).toBeLessThan(1)
  })

  it('容忍越界小时（负数 / >24）', () => {
    expect(daylightFactor(-12)).toBeCloseTo(1)
    expect(daylightFactor(36)).toBeCloseTo(1)
  })
})

describe('resolveGlobeLighting', () => {
  it('亮色底图直射强度低于暗色底图（防过曝核心约束）', () => {
    const light = resolveGlobeLighting(12, 'light', 'standard')
    const dark = resolveGlobeLighting(12, 'dark', 'standard')
    expect(light).not.toBeNull()
    expect(dark).not.toBeNull()
    expect(light!.intensity).toBeLessThan(dark!.intensity)
  })

  it('亮色底图太阳高度上限更低（长影柔和，不直射）', () => {
    const light = resolveGlobeLighting(12, 'light', 'standard')!
    const dark = resolveGlobeLighting(12, 'dark', 'standard')!
    expect(light.elevation).toBeLessThan(dark.elevation)
    expect(light.elevation).toBeLessThanOrEqual(36)
    expect(dark.elevation).toBeLessThanOrEqual(64)
  })

  it('standard 与 natural 档光照参数一致（档位只影响晨昏样式，不影响光照数值）', () => {
    const standard = resolveGlobeLighting(12, 'medium', 'standard')!
    const natural = resolveGlobeLighting(12, 'medium', 'natural')!
    expect(natural.intensity).toBeCloseTo(standard.intensity)
    expect(natural.elevation).toBeCloseTo(standard.elevation)
    expect(natural.color).toBe(standard.color)
  })

  it('off 档返回 null（关闭昼夜光照）', () => {
    expect(resolveGlobeLighting(12, 'dark', 'off')).toBeNull()
  })

  it('强度始终在 MapLibre 合法区间内', () => {
    for (const hour of [0, 3, 6, 9, 12, 15, 18, 21, 23]) {
      for (const brightness of ['light', 'medium', 'dark'] as const) {
        for (const mode of ['standard', 'natural'] as const) {
          const light = resolveGlobeLighting(hour, brightness, mode)!
          expect(light.intensity).toBeGreaterThanOrEqual(0.18)
          expect(light.intensity).toBeLessThanOrEqual(1.0)
          expect(light.elevation).toBeGreaterThan(0)
          expect(light.color).toMatch(/^rgb\(\d+, \d+, \d+\)$/)
        }
      }
    }
  })

  it('夜间强度低于白天（昼夜差保持）', () => {
    const night = resolveGlobeLighting(0, 'dark', 'standard')!
    const noon = resolveGlobeLighting(12, 'dark', 'standard')!
    expect(night.intensity).toBeLessThan(noon.intensity)
  })

  it('亮色底图色温更冷暗（color 整体压暗，乘到白底上避免过曝）', () => {
    const light = resolveGlobeLighting(18, 'light', 'standard')!
    const dark = resolveGlobeLighting(18, 'dark', 'standard')!
    // 亮色底图 RGB 各分量应明显低于暗色底图（伽马压制策略）
    const lightRgb = /rgb\((\d+), (\d+), (\d+)\)/.exec(light.color)!.slice(1).map(Number)
    const darkRgb = /rgb\((\d+), (\d+), (\d+)\)/.exec(dark.color)!.slice(1).map(Number)
    for (let i = 0; i < 3; i++) {
      expect(lightRgb[i]).toBeLessThan(darkRgb[i])
    }
  })
})

describe('resolveGlobeSky', () => {
  it('白天亮色底图用更柔和的雾蓝（避免亮面反射发白）', () => {
    const light = resolveGlobeSky(12, 'light')
    const dark = resolveGlobeSky(12, 'dark')
    expect(light.skyColor).not.toBe(dark.skyColor)
    expect(light.atmosphereBlend).toBeLessThan(dark.atmosphereBlend)
  })

  it('夜间统一深空蓝黑', () => {
    const night = resolveGlobeSky(0, 'light')
    expect(night.skyColor).toBe('#0a2440')
    expect(night.horizonFogBlend).toBeGreaterThan(0.8)
  })

  it('晨昏（daylight 临界）切换日/夜配色不抛错', () => {
    for (const hour of [0, 6, 7, 8, 16, 17, 18, 23]) {
      const sky = resolveGlobeSky(hour, 'medium')
      expect(sky.skyColor).toMatch(/^#[0-9a-f]{6}$/)
      expect(sky.fogGroundBlend).toBeGreaterThan(0)
      expect(sky.fogGroundBlend).toBeLessThanOrEqual(1)
    }
  })
})

describe('subsolarLongitude / subsolarDeclination', () => {
  it('太阳下点经度按本地时区换算：UTC 正午在 0°、北京正午在 120°E、北京午夜在 60°W', () => {
    // UTC（tz=0）：hour=12 → 0°；hour=0 → ±180；hour=18 → 90°W
    expect(subsolarLongitude(12, 0)).toBeCloseTo(0, 5)
    expect(Math.abs(subsolarLongitude(0, 0))).toBeCloseTo(180, 5)
    expect(subsolarLongitude(18, 0)).toBeCloseTo(-90, 5)
    // 北京时间（tz=+8）：正午 12:00 = UTC 04:00 → 太阳下点 120°E（杭州附近）
    expect(subsolarLongitude(12, 8)).toBeCloseTo(120, 5)
    // 北京午夜 00:00 = UTC 昨日 16:00 → 太阳下点 60°W
    expect(subsolarLongitude(0, 8)).toBeCloseTo(-60, 5)
    // 周期性：hour 与 hour+24 等价
    expect(subsolarLongitude(6 + 24, 8)).toBeCloseTo(subsolarLongitude(6, 8), 5)
  })

  it('太阳赤纬：二分日≈0°、夏至≈+23.45°、冬至≈-23.45°', () => {
    const equinox = subsolarDeclination(new Date(Date.UTC(2026, 2, 20))) // 3-20 春分
    const solsticeSummer = subsolarDeclination(new Date(Date.UTC(2026, 5, 21))) // 6-21 夏至
    const solsticeWinter = subsolarDeclination(new Date(Date.UTC(2026, 11, 21))) // 12-21 冬至
    expect(Math.abs(equinox)).toBeLessThan(2)
    expect(solsticeSummer).toBeGreaterThan(20)
    expect(solsticeSummer).toBeLessThanOrEqual(23.45)
    expect(solsticeWinter).toBeLessThan(-20)
    expect(solsticeWinter).toBeGreaterThanOrEqual(-23.45)
  })
})
