import { describe, expect, it } from 'vitest'

import {
  classifyBasemapBrightness,
  daylightFactor,
  resolveGlobeLighting,
  resolveGlobeSky,
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
    const light = resolveGlobeLighting(12, 'light', 'auto')
    const dark = resolveGlobeLighting(12, 'dark', 'auto')
    expect(light).not.toBeNull()
    expect(dark).not.toBeNull()
    expect(light!.intensity).toBeLessThan(dark!.intensity)
  })

  it('亮色底图太阳高度上限更低（长影柔和，不直射）', () => {
    const light = resolveGlobeLighting(12, 'light', 'auto')!
    const dark = resolveGlobeLighting(12, 'dark', 'auto')!
    expect(light.elevation).toBeLessThan(dark.elevation)
    expect(light.elevation).toBeLessThanOrEqual(36)
    expect(dark.elevation).toBeLessThanOrEqual(64)
  })

  it('柔和档整体压低强度', () => {
    const standard = resolveGlobeLighting(12, 'medium', 'standard')!
    const soft = resolveGlobeLighting(12, 'medium', 'soft')!
    expect(soft.intensity).toBeLessThan(standard.intensity)
  })

  it('auto 与 standard 亮度一致（auto 仅按底图缩放）', () => {
    const auto = resolveGlobeLighting(15, 'medium', 'auto')!
    const standard = resolveGlobeLighting(15, 'medium', 'standard')!
    expect(auto.intensity).toBeCloseTo(standard.intensity)
  })

  it('off 档返回 null（关闭昼夜光照）', () => {
    expect(resolveGlobeLighting(12, 'dark', 'off')).toBeNull()
  })

  it('强度始终在 MapLibre 合法区间内', () => {
    for (const hour of [0, 3, 6, 9, 12, 15, 18, 21, 23]) {
      for (const brightness of ['light', 'medium', 'dark'] as const) {
        for (const mode of ['auto', 'soft', 'standard'] as const) {
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
    const night = resolveGlobeLighting(0, 'dark', 'auto')!
    const noon = resolveGlobeLighting(12, 'dark', 'auto')!
    expect(night.intensity).toBeLessThan(noon.intensity)
  })

  it('亮色底图色温更白（减少暖色叠加到白底）', () => {
    const light = resolveGlobeLighting(18, 'light', 'auto')!
    const dark = resolveGlobeLighting(18, 'dark', 'auto')!
    // 同一时刻，亮色底图的 green 分量应更高（更接近白）
    const lightGreen = Number(/rgb\(\d+, (\d+), \d+\)/.exec(light.color)![1])
    const darkGreen = Number(/rgb\(\d+, (\d+), \d+\)/.exec(dark.color)![1])
    expect(lightGreen).toBeGreaterThanOrEqual(darkGreen)
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
