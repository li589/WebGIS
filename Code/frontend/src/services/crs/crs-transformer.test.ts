import { describe, expect, it } from 'vitest'
import proj4 from 'proj4'
import { transformPoint, transformBounds, transformPointsBatch } from './crs-transformer'
import { getCrs, listCrs } from './crs-registry'
import { bd09ToGcj02, gcj02ToBd09 } from './gcj-bd'
import { detectFromBounds } from './crs-detector'

describe('crs-registry', () => {
  it('注册 13 个 CRS', () => {
    expect(listCrs().length).toBe(13)
  })

  it('getCrs 兼容 GCJ-02 旧码', () => {
    expect(getCrs('GCJ-02')?.code).toBe('GCJ02')
    expect(getCrs('BD-09')?.code).toBe('BD09')
  })

  it('包含 Task 6.4 新增的 GK/Lambert CRS', () => {
    expect(getCrs('EPSG:4527')).toBeDefined()
    expect(getCrs('EPSG:4528')).toBeDefined()
    expect(getCrs('EPSG:4529')).toBeDefined()
    expect(getCrs('EPSG:3034')).toBeDefined()
  })
})

describe('crs-transformer', () => {
  it('EPSG:4326 → EPSG:3857 与 proj4 一致', () => {
    // 用 proj4 直接结果作为参照（避免硬编码错值）：116.39°E, 39.91°N → Web Mercator
    const expected = proj4('EPSG:4326', 'EPSG:3857', [116.39, 39.91])
    const [lng, lat] = transformPoint(116.39, 39.91, 'EPSG:4326', 'EPSG:3857')
    expect(lng).toBeCloseTo(expected[0], 3)
    expect(lat).toBeCloseTo(expected[1], 3)
  })

  it('GCJ02 → WGS84 与后端 _gcj_bd 北京样例一致', () => {
    // 北京天安门 GCJ02 (116.39747, 39.90880) → WGS84 (116.391226, 39.907397)
    // 后端 _BEIJING_WGS84 = (116.391226, 39.907397) 是公认真值
    const [lng, lat] = transformPoint(116.39747, 39.9088, 'GCJ02', 'EPSG:4326')
    expect(lng).toBeCloseTo(116.3912, 3)
    expect(lat).toBeCloseTo(39.9074, 3)
  })

  it('BD09 → GCJ02 与直译公式一致', () => {
    const result = transformPoint(116.404, 39.915, 'BD09', 'GCJ02')
    const expected = bd09ToGcj02(116.404, 39.915)
    expect(result[0]).toBeCloseTo(expected[0], 9)
    expect(result[1]).toBeCloseTo(expected[1], 9)
  })

  it('GCJ02 → BD09 走直连路径', () => {
    const result = transformPoint(116.404, 39.915, 'GCJ02', 'BD09')
    const expected = gcj02ToBd09(116.404, 39.915)
    expect(result[0]).toBeCloseTo(expected[0], 9)
    expect(result[1]).toBeCloseTo(expected[1], 9)
  })

  it('偏移在 CRS 转换后应用', () => {
    const [lng, lat] = transformPoint(0, 0, 'EPSG:4326', 'EPSG:4326', {
      lngOffset: 1.5,
      latOffset: 2.5,
    })
    expect(lng).toBeCloseTo(1.5, 9)
    expect(lat).toBeCloseTo(2.5, 9)
  })

  it('EPSG:4527 ↔ EPSG:4326 往返一致（北京）', () => {
    // 先 WGS84 → GK 4527 正算得到北京 GK 坐标，再反算回 WGS84 验证往返一致。
    // GK zone 39（CM 117°E，false easting 39500000）：北京 116.39°E 在 CM 以西
    // 0.6°，easting 应略小于 39500000 + 500000 = 40000000。
    const beijing: [number, number] = [116.391226, 39.907397]
    const gk = transformPoint(beijing[0], beijing[1], 'EPSG:4326', 'EPSG:4527')
    expect(gk[0]).toBeGreaterThan(39400000)
    expect(gk[0]).toBeLessThan(39550000)
    expect(gk[1]).toBeGreaterThan(4400000)
    expect(gk[1]).toBeLessThan(4450000)
    const back = transformPoint(gk[0], gk[1], 'EPSG:4527', 'EPSG:4326')
    expect(back[0]).toBeCloseTo(beijing[0], 7)
    expect(back[1]).toBeCloseTo(beijing[1], 7)
  })

  it('EPSG:3034 ↔ EPSG:4326 往返一致（欧洲）', () => {
    // EPSG:3034 (ETRS89 / LCC Europe)，lat_0=52°N。选 lat=53°（原点以北）以确保
    // Y > 2800000。LCC 往返精度约 1e-6 度（~0.1mm），用 1e-5 断言足够。
    const europe: [number, number] = [10.5, 53.0]
    const lcc = transformPoint(europe[0], europe[1], 'EPSG:4326', 'EPSG:3034')
    expect(lcc[0]).toBeGreaterThan(4000000)
    expect(lcc[0]).toBeLessThan(5000000)
    expect(lcc[1]).toBeGreaterThan(2800000)
    expect(lcc[1]).toBeLessThan(3500000)
    const back = transformPoint(lcc[0], lcc[1], 'EPSG:3034', 'EPSG:4326')
    expect(back[0]).toBeCloseTo(europe[0], 5)
    expect(back[1]).toBeCloseTo(europe[1], 5)
  })

  it('bounds 四角转换', () => {
    const result = transformBounds([116, 39, 117, 40], 'EPSG:4326', 'EPSG:3857')
    expect(result[0]).toBeLessThan(result[2])
    expect(result[1]).toBeLessThan(result[3])
  })

  it('批量点转换', () => {
    const points: Array<[number, number]> = [
      [116.39, 39.91],
      [121.47, 31.23],
    ]
    const result = transformPointsBatch(points, 'EPSG:4326', 'EPSG:3857')
    expect(result.length).toBe(2)
    const expected0 = proj4('EPSG:4326', 'EPSG:3857', points[0])
    expect(result[0][0]).toBeCloseTo(expected0[0], -2)
  })

  it('相同 CRS 直接返回原值', () => {
    const [lng, lat] = transformPoint(116.39, 39.91, 'EPSG:4326', 'EPSG:4326')
    expect(lng).toBeCloseTo(116.39, 9)
    expect(lat).toBeCloseTo(39.91, 9)
  })
})

describe('crs-detector', () => {
  it('地理坐标系识别', () => {
    const result = detectFromBounds([116, 39, 117, 40])
    expect(result.sourceCrs).toBe('EPSG:4326')
    expect(result.method).toBe('bounds_heuristic')
  })

  it('高斯-克吕格 zone 39 识别', () => {
    const result = detectFromBounds([39500000, 4400000, 39510000, 4410000])
    expect(result.sourceCrs).toBe('EPSG:4527')
  })

  it('Lambert Europe 识别', () => {
    const result = detectFromBounds([4000000, 2500000, 4500000, 3000000])
    expect(result.sourceCrs).toBe('EPSG:3034')
  })

  it('默认投影系 UTM 50N', () => {
    const result = detectFromBounds([447000, 4419000, 448000, 4420000])
    expect(result.sourceCrs).toBe('EPSG:32650')
  })
})
