import { describe, expect, it } from 'vitest'

import {
  lngLatToMercatorNormalized,
  TRIANGLE_FRAGMENT_SHADER,
  TRIANGLE_VERTEX_SHADER,
  MERCATOR_PROJECTION_GLSL,
  GLOBE_SPHERE_GLSL,
  WIND_FIELD_VERTEX_SHADER,
  WIND_FIELD_FRAGMENT_SHADER,
  PARTICLE_UPDATE_FRAGMENT_SHADER,
} from '@/components/map/wind-particle-webgl-shaders'

describe('lngLatToMercatorNormalized（GLSL 投影的 TS 镜像）', () => {
  it('赤道 × 本初子午线 → 世界中心 (0.5, 0.5)', () => {
    expect(lngLatToMercatorNormalized(0, 0)).toEqual([0.5, 0.5])
  })

  it('西缘 lon=-180 → x=0', () => {
    expect(lngLatToMercatorNormalized(-180, 0)[0]).toBe(0)
  })

  it('东缘 lon=180 → x=1', () => {
    expect(lngLatToMercatorNormalized(180, 0)[0]).toBe(1)
  })

  it('Mercator 北缘 lat≈85.05 → y≈0', () => {
    expect(lngLatToMercatorNormalized(0, 85.051129)[1]).toBeCloseTo(0, 5)
  })

  it('Mercator 南缘 lat≈-85.05 → y≈1', () => {
    expect(lngLatToMercatorNormalized(0, -85.051129)[1]).toBeCloseTo(1, 5)
  })

  it('纬度超出范围被钳制（不发散）', () => {
    expect(lngLatToMercatorNormalized(0, 90)[1]).toBeCloseTo(0, 5)
    expect(lngLatToMercatorNormalized(0, -90)[1]).toBeCloseTo(1, 5)
  })

  it('北纬为正 y<0.5，南纬为正 y>0.5（北 0 → 南 1）', () => {
    expect(lngLatToMercatorNormalized(0, 30)[1]).toBeLessThan(0.5)
    expect(lngLatToMercatorNormalized(0, -30)[1]).toBeGreaterThan(0.5)
  })
})

describe('B1 调试着色器源码', () => {
  it('vertex shader 含投影助手与矩阵', () => {
    expect(TRIANGLE_VERTEX_SHADER).toContain('a_lnglat')
    expect(TRIANGLE_VERTEX_SHADER).toContain('u_matrix')
    expect(TRIANGLE_VERTEX_SHADER).toContain('lngLatToMercator')
    expect(TRIANGLE_VERTEX_SHADER).toContain('gl_Position')
  })

  it('fragment shader 输出颜色', () => {
    expect(TRIANGLE_FRAGMENT_SHADER).toContain('gl_FragColor')
  })

  it('Mercator 投影助手含纬度钳制', () => {
    expect(MERCATOR_PROJECTION_GLSL).toContain('85.051129')
    expect(MERCATOR_PROJECTION_GLSL).toContain('lngLatToMercator')
  })
})

describe('globe 投影着色器契约', () => {
  it('暴露单位球投影助手', () => {
    expect(GLOBE_SPHERE_GLSL).toContain('lngLatToGlobeSphere')
    expect(GLOBE_SPHERE_GLSL).toContain('cosLat')
  })

  it('风场 shader 支持 globe 分支与边缘羽化', () => {
    expect(WIND_FIELD_VERTEX_SHADER).toContain('u_useGlobe')
    expect(WIND_FIELD_VERTEX_SHADER).toContain('lngLatToGlobeSphere')
    expect(WIND_FIELD_FRAGMENT_SHADER).toContain('edgeFade')
    expect(WIND_FIELD_FRAGMENT_SHADER).toContain('discard')
  })
})

describe('B3 粒子更新着色器稳定性约定', () => {
  it('含多子步 RK2 与位移钳制常量', () => {
    expect(PARTICLE_UPDATE_FRAGMENT_SHADER).toContain('SUBSTEPS')
    expect(PARTICLE_UPDATE_FRAGMENT_SHADER).toContain('MAX_STEP_DEG')
    expect(PARTICLE_UPDATE_FRAGMENT_SHADER).toContain('for (int i = 0; i < SUBSTEPS; i++)')
  })

  it('高风速 DROP_BUMP 保持低值（避免急流区狂跳）', () => {
    const bump = PARTICLE_UPDATE_FRAGMENT_SHADER.match(/DROP_BUMP\s*=\s*([0-9.]+)/)
    expect(bump).not.toBeNull()
    expect(Number(bump![1])).toBeLessThanOrEqual(0.004)
  })
})
