import { describe, expect, it } from 'vitest'

import {
  buildGlobeNightMesh,
  globeNightMeshLatRange,
  GLOBE_MERCATOR_MAX_LAT,
  GLOBE_NIGHT_MASK_FRAGMENT_SHADER,
  GLOBE_NIGHT_MASK_VERTEX_SHADER,
} from '@/components/map/globe-night-mask-shaders'

describe('buildGlobeNightMesh（极冠覆盖）', () => {
  it('纬度覆盖真正 ±90°（非仅 ±85.051）', () => {
    const { minLat, maxLat } = globeNightMeshLatRange()
    expect(minLat).toBe(-90)
    expect(maxLat).toBe(90)
  })

  it('含南/北极冠扇形顶点（越过 Mercator 上限）', () => {
    const mesh = buildGlobeNightMesh(30, 30) // 粗步长便于断言
    const lats: number[] = []
    for (let i = 1; i < mesh.length; i += 2) lats.push(mesh[i]!)
    expect(lats).toContain(90)
    expect(lats).toContain(-90)
    expect(Math.max(...lats.filter((φ) => φ < 90))).toBeCloseTo(GLOBE_MERCATOR_MAX_LAT, 5)
    expect(Math.min(...lats.filter((φ) => φ > -90))).toBeCloseTo(-GLOBE_MERCATOR_MAX_LAT, 5)
  })

  it('顶点着色器使用未钳制球面函数（覆盖极点）', () => {
    expect(GLOBE_NIGHT_MASK_VERTEX_SHADER).toContain('lngLatToGlobeSphereNight')
    expect(GLOBE_NIGHT_MASK_VERTEX_SHADER).toContain('clamp(latDeg, -90.0, 90.0)')
    expect(GLOBE_NIGHT_MASK_VERTEX_SHADER).not.toContain('85.051129')
    expect(GLOBE_NIGHT_MASK_VERTEX_SHADER).toContain('v_sphere')
  })

  it('片元着色器逐像素精确裁剪前半球 + 软边晨昏过渡 + 大气折射', () => {
    expect(GLOBE_NIGHT_MASK_FRAGMENT_SHADER).toContain('u_camDir')
    // 逐像素归一化（消除顶点插值误差——球面轮廓附近三角形"翻到球面外"的壳感）
    expect(GLOBE_NIGHT_MASK_FRAGMENT_SHADER).toContain('normalize(v_sphere)')
    expect(GLOBE_NIGHT_MASK_FRAGMENT_SHADER).toContain('dot(n, u_camDir)')
    // 软边过渡（替代硬边 if (sinH >= 0.0) discard）
    expect(GLOBE_NIGHT_MASK_FRAGMENT_SHADER).toContain('clamp(-sinRefract / 0.0349')
    expect(GLOBE_NIGHT_MASK_FRAGMENT_SHADER).toContain('u_nightAlpha * t')
    // 大气折射修正（sin 0.83°）
    expect(GLOBE_NIGHT_MASK_FRAGMENT_SHADER).toContain('0.0145')
  })
})
