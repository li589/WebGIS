import { describe, expect, it } from 'vitest'

import {
  buildNightHemisphereGeoJSON,
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

describe('subsolarLongitude / subsolarDeclination / buildNightHemisphereGeoJSON（自然晨昏线）', () => {
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

  it('夜半球中心 = 太阳下点 + 180°；昼侧经度不落入夜核（二分日）', () => {
    // 二分日（Cooper 模型 δ=0，年内第 81 天）：hour=12 UTC → 太阳下点 0°、夜中心 180°
    const json = buildNightHemisphereGeoJSON(12, new Date(Date.UTC(2026, 2, 22)), 0)
    expect(json.type).toBe('FeatureCollection')
    const coreLons = json.features
      .filter((f) => f.properties.hemisphere === 'night-core')
      .flatMap((f) => f.geometry.coordinates[0].map((pt) => pt[0]))
    // 0° 经线（hour=12 UTC 的昼侧中央）不应出现在夜核边界上
    expect(coreLons.some((lon) => Math.abs(lon) < 1)).toBe(false)
    // 180° 必在夜核内
    expect(coreLons.some((lon) => Math.abs(lon) === 180)).toBe(true)
  })

  it('结构 = night-core 多边形（硬边全暗区）+ terminator linestring（line-blur 羽化载体）', () => {
    // 非二分日（δ≠0，φc 曲线路径）
    const json = buildNightHemisphereGeoJSON(6, new Date(Date.UTC(2026, 5, 21)))
    const cores = json.features.filter((f) => f.properties.hemisphere === 'night-core')
    const terms = json.features.filter((f) => f.properties.hemisphere === 'terminator')
    expect(cores.length).toBeGreaterThan(0)
    expect(terms.length).toBeGreaterThan(0)
    for (const c of cores) expect(c.geometry.type).toBe('Polygon')
    for (const t of terms) expect(t.geometry.type).toBe('LineString')
    // 无过渡带 tier 条纹（用户反馈"好多线"——条纹方案已废弃）
    expect(json.features.some((f) => 'tier' in f.properties)).toBe(false)
    // 无 twilight 彩色条带
    expect(
      json.features.some((f) => (f.properties as { hemisphere?: string }).hemisphere === 'twilight'),
    ).toBe(false)
  })

  it('二分日 terminator 退化为两条经线线段（λn±90），夜核覆盖全纬度', () => {
    // Cooper 模型 δ=0 的日子：年内第 81 天（2026-03-22）
    const json = buildNightHemisphereGeoJSON(12, new Date(Date.UTC(2026, 2, 22)), 0)
    const terms = json.features.filter((f) => f.properties.hemisphere === 'terminator')
    expect(terms.length).toBe(2)
    for (const t of terms) {
      const line = t.geometry.coordinates as number[][]
      // 经线线段：经度恒定，纬度从 -90 到 90
      expect(line[0][0]).toBe(line[line.length - 1][0])
      const lats = line.map((pt) => pt[1])
      expect(Math.min(...lats)).toBe(-90)
      expect(Math.max(...lats)).toBe(90)
    }
    const termLons = terms.map((t) => (t.geometry.coordinates as number[][])[0][0])
    expect(Math.abs(Math.abs(termLons[0] - termLons[1]) - 180)).toBeLessThan(1)
    // 二分日夜核 = 夜侧经度带全纬度（极冠洞 0.5° ×2 = 1° 在赤道两侧，<2px 忽略）
    const coreLats = json.features
      .filter((f) => f.properties.hemisphere === 'night-core')
      .flatMap((f) => f.geometry.coordinates[0].map((pt) => pt[1]))
    expect(Math.min(...coreLats)).toBe(-89.9)
    expect(Math.max(...coreLats)).toBe(89.9)
  })

  it('所有几何坐标在 [-180,180]×[-90,90]，polygon ring 闭合（含 antimeridian 拆分）', () => {
    for (const hour of [0, 3, 6, 9, 12, 15, 18, 21, 23.5]) {
      const json = buildNightHemisphereGeoJSON(hour, new Date(Date.UTC(2026, 5, 21)))
      expect(json.features.length).toBeGreaterThan(0)
      for (const feature of json.features) {
        // Polygon: coordinates[0]=ring；LineString: coordinates=点列
        const pts = (
          feature.geometry.type === 'Polygon'
            ? feature.geometry.coordinates[0]
            : feature.geometry.coordinates
        ) as number[][]
        for (const [lon, lat] of pts) {
          expect(lon).toBeGreaterThanOrEqual(-180)
          expect(lon).toBeLessThanOrEqual(180)
          expect(lat).toBeGreaterThanOrEqual(-90)
          expect(lat).toBeLessThanOrEqual(90)
        }
        if (feature.geometry.type === 'Polygon') {
          const first = pts[0]
          const last = pts[pts.length - 1]
          expect(first[0]).toBe(last[0])
          expect(first[1]).toBe(last[1])
        }
      }
    }
  })

  it('晨昏线随日期弯曲：夏至夜侧偏南（北半球高纬无夜侧段），冬至相反', () => {
    // 夏至（δ>0）：夜核边界不触及北纬 66.5° 以上（北极圈极昼）
    const summer = buildNightHemisphereGeoJSON(12, new Date(Date.UTC(2026, 5, 21)))
    const summerCoreLats = summer.features
      .filter((f) => f.properties.hemisphere === 'night-core')
      .flatMap((f) => f.geometry.coordinates[0].map((pt) => pt[1]))
    expect(Math.max(...summerCoreLats)).toBeLessThan(66.6)

    // 冬至（δ<0）：夜核边界不触及南纬 66.5° 以下（南极圈极昼）
    const winter = buildNightHemisphereGeoJSON(12, new Date(Date.UTC(2026, 11, 21)))
    const winterCoreLats = winter.features
      .filter((f) => f.properties.hemisphere === 'night-core')
      .flatMap((f) => f.geometry.coordinates[0].map((pt) => pt[1]))
    expect(Math.min(...winterCoreLats)).toBeGreaterThan(-66.6)
  })

  it('terminator 曲线沿晨昏线纬度边界 φc(λ)（非平直）', () => {
    // 夏至：φc 曲线在夜心经度处达最高纬度（北半球），两侧递减——弯曲形态
    const json = buildNightHemisphereGeoJSON(12, new Date(Date.UTC(2026, 5, 21)), 0)
    const terms = json.features.filter((f) => f.properties.hemisphere === 'terminator')
    const allLats = terms.flatMap((t) => (t.geometry.coordinates as number[][]).map((pt) => pt[1]))
    const minLat = Math.min(...allLats)
    const maxLat = Math.max(...allLats)
    // 曲线有显著纬度变化（弯曲，非直线）
    expect(maxLat - minLat).toBeGreaterThan(30)
  })
})

describe('晨昏线渲染质量（折点/平滑性/采样密度）', () => {
  it('terminator 采样密度 ≥90 点/180°（1° 步长）且最大转角 <0.15 rad（无折点）', () => {
    const json = buildNightHemisphereGeoJSON(20, new Date(Date.UTC(2026, 7, 28)), 8)
    const terms = json.features.filter((f) => f.properties.hemisphere === 'terminator')
    expect(terms.length).toBeGreaterThan(0)
    for (const t of terms) {
      const pts = t.geometry.coordinates as number[][]
      // 1° 步长：180° 范围 ≥ 90 点
      expect(pts.length).toBeGreaterThanOrEqual(90)
      // 相邻线段方向变化角（转角）应极小——折点会表现为局部大转角
      let maxTurn = 0
      for (let i = 2; i < pts.length; i++) {
        const a1 = Math.atan2(pts[i - 1][1] - pts[i - 2][1], pts[i - 1][0] - pts[i - 2][0])
        const a2 = Math.atan2(pts[i][1] - pts[i - 1][1], pts[i][0] - pts[i - 1][0])
        let d = Math.abs(a2 - a1)
        if (d > Math.PI) d = 2 * Math.PI - d
        maxTurn = Math.max(maxTurn, d)
      }
      expect(maxTurn).toBeLessThan(0.15)
    }
  })
})
