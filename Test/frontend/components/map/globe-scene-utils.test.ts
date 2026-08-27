import { describe, expect, it } from 'vitest'

import {
  buildNightHemisphereGeoJSON,
  classifyBasemapBrightness,
  daylightFactor,
  resolveGlobeLighting,
  resolveGlobeSky,
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

  it('亮色底图色温更冷暗（color 整体压暗，乘到白底上避免过曝）', () => {
    const light = resolveGlobeLighting(18, 'light', 'auto')!
    const dark = resolveGlobeLighting(18, 'dark', 'auto')!
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

describe('subsolarLongitude / buildNightHemisphereGeoJSON（晨昏线）', () => {
  it('太阳下点经度随 hour 旋转：12h 在 0°、0h 在 180°、18h 在 90°W', () => {
    expect(subsolarLongitude(12)).toBeCloseTo(0, 5)
    expect(Math.abs(subsolarLongitude(0))).toBeCloseTo(180, 5)
    expect(subsolarLongitude(18)).toBeCloseTo(-90, 5)
    // 周期性：hour 与 hour+24 等价
    expect(subsolarLongitude(6 + 24)).toBeCloseTo(subsolarLongitude(6), 5)
  })

  it('夜半球中心 = 太阳下点 + 180°，覆盖对侧 180° 经度范围', () => {
    // hour=12 → 夜中心 180°，夜半球跨 90°E~90°W（跨 antimeridian 拆两段）
    const json = buildNightHemisphereGeoJSON(12)
    expect(json.type).toBe('FeatureCollection')
    const lons = json.features.flatMap((f) =>
      f.geometry.coordinates[0].map((pt) => pt[0]),
    )
    // 0° 经线（太平洋中央区域在 hour=12 应为白昼）不能落入夜半球
    expect(lons.some((lon) => lon === 0)).toBe(false)
    // 180° 必在夜半球内
    expect(lons.some((lon) => Math.abs(lon) === 180)).toBe(true)
  })

  it('GeoJSON 不跨 antimeridian 断裂：所有 ring 经度在 [-180,180] 且方向连续', () => {
    for (const hour of [0, 3, 6, 9, 12, 15, 18, 21, 23.5]) {
      const json = buildNightHemisphereGeoJSON(hour)
      for (const feature of json.features) {
        const ring = feature.geometry.coordinates[0]
        for (const [lon] of ring) {
          expect(lon).toBeGreaterThanOrEqual(-180)
          expect(lon).toBeLessThanOrEqual(180)
        }
        // ring 闭合
        const first = ring[0]
        const last = ring[ring.length - 1]
        expect(first[0]).toBe(last[0])
        expect(first[1]).toBe(last[1])
      }
    }
  })

  it('晨昏渐变为 5 层嵌套：夜心被全部层覆盖、最外层恰达夜半球边界（±90°）', () => {
    // hour=6 → 太阳在 90°E，夜心在 90°W（不跨 antimeridian，几何最直观）
    const json = buildNightHemisphereGeoJSON(6)
    // 5 层且每层 ring 宽度 = 2*(t+1)*18°
    const tiers = json.features.map((f) => f.properties.tier)
    expect(tiers).toEqual([0, 1, 2, 3, 4])
    for (const f of json.features) {
      const ring = f.geometry.coordinates[0]
      const west = ring[0][0]
      const east = ring[1][0]
      const expectedHalf = (f.properties.tier + 1) * 18
      expect(east - west).toBeCloseTo(expectedHalf * 2, 5)
      // 夜心 -90° 必须在层内
      expect(west <= -90 && -90 <= east).toBe(true)
    }
    // 最外层边界 = 夜心 ±90°（= 0° 与 180°，即晨昏线位置）
    const outer = json.features.find((f) => f.properties.tier === 4)!
    const outerWest = outer.geometry.coordinates[0][0][0]
    const outerEast = outer.geometry.coordinates[0][1][0]
    expect(outerWest).toBeCloseTo(-180, 5)
    expect(outerEast).toBeCloseTo(0, 5)
  })
})
