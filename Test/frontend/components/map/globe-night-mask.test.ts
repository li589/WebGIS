import { describe, expect, it } from 'vitest'

import { buildGlobeNightMesh, GLOBE_NIGHT_MESH_VERTEX_COUNT } from '@/components/map/globe-night-mask-shaders'
import {
  buildNightMaskPixels,
  sunAltitudeDeg,
  NIGHT_MASK_RGBA,
  quantizeNightMaskHour,
} from '@/components/map/globe-night-mask'
import { subsolarDeclination, subsolarLongitude } from '@/components/map/globe-scene-utils'

function sampleAlpha(
  data: Uint8ClampedArray,
  width: number,
  height: number,
  lon: number,
  lat: number,
): number {
  const col = Math.round(((lon + 180) / 360) * (width - 1))
  const row = Math.round(((90 - lat) / 180) * (height - 1))
  return data[(row * width + col) * 4 + 3]
}

describe('sunAltitudeDeg', () => {
  it('太阳下点处 h>0，对跖点 h<0', () => {
    const date = new Date(Date.UTC(2026, 7, 28))
    const lon = subsolarLongitude(12, 8)
    const decl = subsolarDeclination(date)
    expect(sunAltitudeDeg(lon, 0, lon, decl)).toBeGreaterThan(0)
    expect(sunAltitudeDeg(lon + 180, 0, lon, decl)).toBeLessThan(0)
  })

  it('极点随赤纬整极昼/极夜（无经度依赖）', () => {
    const decl = 23.45
    expect(sunAltitudeDeg(0, 90, 0, decl)).toBeGreaterThan(0)
    expect(sunAltitudeDeg(100, 90, 0, decl)).toBeGreaterThan(0)
    expect(sunAltitudeDeg(0, -90, 0, decl)).toBeLessThan(0)
  })
})

describe('buildGlobeNightMesh', () => {
  it('全球三角网格顶点数稳定且可被 3 整除', () => {
    const mesh = buildGlobeNightMesh()
    expect(mesh.length / 2).toBe(GLOBE_NIGHT_MESH_VERTEX_COUNT)
    expect(mesh.length % 6).toBe(0)
    expect(GLOBE_NIGHT_MESH_VERTEX_COUNT).toBeGreaterThan(1000)
  })
})

describe('quantizeNightMaskHour', () => {
  it('对齐 slider step=0.25', () => {
    expect(quantizeNightMaskHour(12.1)).toBe(12)
    expect(quantizeNightMaskHour(12.2)).toBe(12.25)
    expect(quantizeNightMaskHour(12.38)).toBe(12.5)
    expect(quantizeNightMaskHour(12.4)).toBe(12.5)
  })
})

describe('buildNightMaskPixels（自然档 v1 硬边暗/亮）', () => {
  const width = 360
  const height = 180
  const date = new Date(Date.UTC(2026, 7, 28))

  it('昼侧透明、夜侧带 alpha', () => {
    const data = buildNightMaskPixels(width, height, 12, date, 8)
    const subsolarLon = subsolarLongitude(12, 8)
    const dayAlpha = sampleAlpha(data, width, height, subsolarLon, 0)
    const nightAlpha = sampleAlpha(data, width, height, subsolarLon + 180, 0)
    expect(dayAlpha).toBe(0)
    expect(nightAlpha).toBe(NIGHT_MASK_RGBA.a)
  })

  it('极点像素有遮罩（无 89.9° 极冠亮洞）', () => {
    const data = buildNightMaskPixels(width, height, 0, date, 8)
    const northAlpha = sampleAlpha(data, width, height, 0, 90)
    const southAlpha = sampleAlpha(data, width, height, 0, -90)
    // 至少一极为夜或昼的全覆盖 alpha（0 或 NIGHT_MASK_RGBA.a），不应出现"半覆盖"
    expect(northAlpha === 0 || northAlpha === NIGHT_MASK_RGBA.a).toBe(true)
    expect(southAlpha === 0 || southAlpha === NIGHT_MASK_RGBA.a).toBe(true)
  })

  it('24 小时采样：每帧均有昼夜两侧（非全透明/全暗）', () => {
    for (let hour = 0; hour < 24; hour += 3) {
      const data = buildNightMaskPixels(width, height, hour, date, 8)
      let nightCount = 0
      let dayCount = 0
      for (let i = 3; i < data.length; i += 4) {
        if (data[i] > 0) nightCount++
        else dayCount++
      }
      expect(nightCount).toBeGreaterThan(0)
      expect(dayCount).toBeGreaterThan(0)
    }
  })

  it('夏至：北极圈以上全昼（alpha=0）', () => {
    const data = buildNightMaskPixels(width, height, 12, new Date(Date.UTC(2026, 5, 21)), 0)
    const alpha70N = sampleAlpha(data, width, height, 0, 70)
    expect(alpha70N).toBe(0)
  })

  it('二分日：昼侧经度透明、夜侧经度带 alpha', () => {
    const data = buildNightMaskPixels(width, height, 12, new Date(Date.UTC(2026, 2, 22)), 0)
    expect(sampleAlpha(data, width, height, 0, 0)).toBe(0)
    expect(sampleAlpha(data, width, height, 180, 0)).toBe(NIGHT_MASK_RGBA.a)
  })

  it('夏至：夜侧不触及北极圈以上（高纬极昼透明）', () => {
    const data = buildNightMaskPixels(width, height, 12, new Date(Date.UTC(2026, 5, 21)), 0)
    const subsolarLon = subsolarLongitude(12, 0)
    const nightLon = subsolarLon + 180
    const alpha66N = sampleAlpha(data, width, height, nightLon, 66)
    expect(alpha66N).toBe(NIGHT_MASK_RGBA.a)
    expect(sampleAlpha(data, width, height, nightLon, 75)).toBe(0)
  })
})
