import { describe, expect, it } from 'vitest'

import { buildWindGridFromGeoJSON, windToUV, uvToSpeedDirection, type WindGrid } from './wind-grid'
import {
  buildPaletteLUT,
  encodeWindGridToRGBA,
  WIND_TEXTURE_MAX_WIND,
} from './wind-particle-webgl-texture'
import {
  encodePositionBytes,
  decodePositionBytes,
  computeWorldWrapOffsets,
  extractMercatorProjectionMatrix,
  sampleEncodedWindSpeedK,
} from './wind-particle-webgl-renderer'
import type { WindGeoJSON } from './types'

function makeWindGrid(): WindGrid {
  return {
    rows: 2,
    cols: 2,
    south: 0,
    north: 10,
    west: 100,
    east: 110,
    // row 0 = 北（lat 10），row 1 = 南（lat 0）
    points: [
      [
        { lat: 10, lon: 100, speed: 10, direction: 0 },
        { lat: 10, lon: 110, speed: 20, direction: 90 },
      ],
      [
        { lat: 0, lon: 100, speed: 0, direction: 0 },
        { lat: 0, lon: 110, speed: 40, direction: 180 },
      ],
    ],
    checksum: 0,
  }
}

describe('wind-grid windToUV / uvToSpeedDirection', () => {
  it('气象风向 0°（北风）→ v 为负（向南吹）', () => {
    const [u, v] = windToUV(10, 0)
    expect(u).toBeCloseTo(0, 5)
    expect(v).toBeCloseTo(-10, 5)
  })

  it('气象风向 90°（东风）→ u 为负（向西吹）', () => {
    const [u, v] = windToUV(20, 90)
    expect(u).toBeCloseTo(-20, 5)
    expect(v).toBeCloseTo(0, 5)
  })

  it('uv 往返：uvToSpeedDirection 是 windToUV 的反函数', () => {
    const [u, v] = windToUV(15, 123)
    const { speed, direction } = uvToSpeedDirection(u, v)
    expect(speed).toBeCloseTo(15, 4)
    expect(direction).toBeCloseTo(123, 4)
  })

  it('涡旋中心 (0,0) 返回静风', () => {
    expect(uvToSpeedDirection(0, 0)).toEqual({ speed: 0, direction: 0 })
  })
})

describe('wind-grid buildWindGridFromGeoJSON', () => {
  const geojson: WindGeoJSON = {
    type: 'FeatureCollection',
    features: [
      {
        type: 'Feature',
        geometry: { type: 'Point', coordinates: [100, 10] },
        properties: { wind_speed_10m: 5, wind_direction_10m: 0 },
      },
      {
        type: 'Feature',
        geometry: { type: 'Point', coordinates: [110, 10] },
        properties: { wind_speed_10m: 6, wind_direction_10m: 90 },
      },
      {
        type: 'Feature',
        geometry: { type: 'Point', coordinates: [100, 0] },
        properties: { wind_speed_10m: 7, wind_direction_10m: 180 },
      },
      {
        type: 'Feature',
        geometry: { type: 'Point', coordinates: [110, 0] },
        properties: { wind_speed_10m: 8, wind_direction_10m: 270 },
      },
    ],
  }

  it('构建 2×2 网格与正确 bbox', () => {
    const grid = buildWindGridFromGeoJSON(geojson)!
    expect(grid).not.toBeNull()
    expect(grid.rows).toBe(2)
    expect(grid.cols).toBe(2)
    expect(grid.west).toBe(100)
    expect(grid.east).toBe(110)
    expect(grid.south).toBe(0)
    expect(grid.north).toBe(10)
  })

  it('row 0 = 最北（lat 降序），col 0 = 最西（lon 升序）', () => {
    const grid = buildWindGridFromGeoJSON(geojson)!
    // points[0][0] = 西北角 (lat10, lon100) → speed 5, direction 0
    expect(grid.points[0][0].speed).toBe(5)
    expect(grid.points[0][0].direction).toBe(0)
    // points[1][1] = 东南角 (lat0, lon110) → speed 8
    expect(grid.points[1][1].speed).toBe(8)
  })

  it('空 features 返回 null', () => {
    expect(buildWindGridFromGeoJSON({ type: 'FeatureCollection', features: [] })).toBeNull()
  })

  it('不足 2×2 返回 null', () => {
    const twoPoints: WindGeoJSON = {
      type: 'FeatureCollection',
      features: [
        {
          type: 'Feature',
          geometry: { type: 'Point', coordinates: [100, 10] },
          properties: { wind_speed_10m: 5, wind_direction_10m: 0 },
        },
        {
          type: 'Feature',
          geometry: { type: 'Point', coordinates: [110, 10] },
          properties: { wind_speed_10m: 5, wind_direction_10m: 0 },
        },
      ],
    }
    expect(buildWindGridFromGeoJSON(twoPoints)).toBeNull()
  })

  it('跨赤道缺带时补齐中间纬度行，UV 行距仍均匀', () => {
    const crossEq: WindGeoJSON = {
      type: 'FeatureCollection',
      features: [
        {
          type: 'Feature',
          geometry: { type: 'Point', coordinates: [120, 38.75] },
          properties: { wind_speed_10m: 5, wind_direction_10m: 0, resolution: 2.5 },
        },
        {
          type: 'Feature',
          geometry: { type: 'Point', coordinates: [122.5, 38.75] },
          properties: { wind_speed_10m: 5, wind_direction_10m: 0, resolution: 2.5 },
        },
        {
          type: 'Feature',
          geometry: { type: 'Point', coordinates: [120, 1.25] },
          properties: { wind_speed_10m: 6, wind_direction_10m: 0, resolution: 2.5 },
        },
        {
          type: 'Feature',
          geometry: { type: 'Point', coordinates: [122.5, 1.25] },
          properties: { wind_speed_10m: 6, wind_direction_10m: 0, resolution: 2.5 },
        },
        {
          type: 'Feature',
          geometry: { type: 'Point', coordinates: [120, -1.25] },
          properties: { wind_speed_10m: 7, wind_direction_10m: 0, resolution: 2.5 },
        },
        {
          type: 'Feature',
          geometry: { type: 'Point', coordinates: [122.5, -1.25] },
          properties: { wind_speed_10m: 7, wind_direction_10m: 0, resolution: 2.5 },
        },
        {
          type: 'Feature',
          geometry: { type: 'Point', coordinates: [120, -38.75] },
          properties: { wind_speed_10m: 8, wind_direction_10m: 0, resolution: 2.5 },
        },
        {
          type: 'Feature',
          geometry: { type: 'Point', coordinates: [122.5, -38.75] },
          properties: { wind_speed_10m: 8, wind_direction_10m: 0, resolution: 2.5 },
        },
      ],
    }
    const grid = buildWindGridFromGeoJSON(crossEq)!
    expect(grid.south).toBeCloseTo(-38.75, 5)
    expect(grid.north).toBeCloseTo(38.75, 5)
    expect(grid.rows).toBeGreaterThan(4)
    const step = (grid.north - grid.south) / (grid.rows - 1)
    expect(step).toBeCloseTo(2.5, 5)
    // 赤道附近行存在（即便原始点未给出 0°）
    const lats = grid.points.map((row) => row[0]!.lat)
    expect(lats.some((lat) => Math.abs(lat) < 1e-6 || Math.abs(lat) <= 1.25)).toBe(true)
  })
})

describe('encodeWindGridToRGBA（R=u, G=v, B=speed, A=mask）', () => {
  it('输出尺寸 = cols × rows × 4', () => {
    const encoded = encodeWindGridToRGBA(makeWindGrid())
    expect(encoded.width).toBe(2)
    expect(encoded.height).toBe(2)
    expect(encoded.data.length).toBe(2 * 2 * 4)
    expect(encoded.west).toBe(100)
    expect(encoded.north).toBe(10)
  })

  it('编码 texel 行序为北→南（首 texel = 西北角）', () => {
    const encoded = encodeWindGridToRGBA(makeWindGrid())
    // 西北角 speed=10, direction=0 → u≈0, v=-10
    const [u, v] = windToUV(10, 0)
    const expectR = Math.round((u / WIND_TEXTURE_MAX_WIND + 1) * 0.5 * 255)
    const expectG = Math.round((v / WIND_TEXTURE_MAX_WIND + 1) * 0.5 * 255)
    expect(encoded.data[0]).toBe(expectR) // R = u
    expect(encoded.data[1]).toBe(expectG) // G = v
    expect(encoded.data[2]).toBe(Math.round((10 / WIND_TEXTURE_MAX_WIND) * 255)) // B = speed
    expect(encoded.data[3]).toBe(255) // A = mask
  })

  it('speed=40（量程上限）编码 B 为 255', () => {
    const encoded = encodeWindGridToRGBA(makeWindGrid())
    // 东南角 speed=40 → 第 4 个 texel (idx=3)
    const idx = 3 * 4
    expect(encoded.data[idx + 2]).toBe(255)
  })

  it('speed=0 编码 B 为 0', () => {
    const encoded = encodeWindGridToRGBA(makeWindGrid())
    // 西南角 speed=0 → 第 3 个 texel (idx=2)
    const idx = 2 * 4
    expect(encoded.data[idx + 2]).toBe(0)
  })
})

describe('buildPaletteLUT', () => {
  it('输出 256×1 RGBA（1024 字节）', () => {
    const lut = buildPaletteLUT(['#000000', '#ffffff'])
    expect(lut.length).toBe(256 * 4)
  })

  it('两色渐变端点正确', () => {
    const lut = buildPaletteLUT(['#000000', '#ffffff'])
    expect([lut[0], lut[1], lut[2]]).toEqual([0, 0, 0]) // 起点黑
    const last = (256 - 1) * 4
    expect([lut[last], lut[last + 1], lut[last + 2]]).toEqual([255, 255, 255]) // 终点白
    expect(lut[last + 3]).toBe(255) // alpha
  })

  it('空输入回退到默认透明→白渐变', () => {
    const lut = buildPaletteLUT([])
    expect(lut.length).toBe(256 * 4)
    expect(lut[3]).toBe(0) // 起点 alpha 0
  })
})

describe('B3 位置编解码往返（encodePositionBytes / decodePositionBytes）', () => {
  it('(0, 0) 往返', () => {
    const [r, g, b, a] = encodePositionBytes(0, 0)
    const [nx, ny] = decodePositionBytes(r, g, b, a)
    expect(nx).toBeCloseTo(0, 5)
    expect(ny).toBeCloseTo(0, 5)
  })

  it('(1, 1) 附近往返（钳制在 [0,1]）', () => {
    const [r, g, b, a] = encodePositionBytes(1, 1)
    const [nx, ny] = decodePositionBytes(r, g, b, a)
    expect(nx).toBeCloseTo(1, 3)
    expect(ny).toBeCloseTo(1, 3)
  })

  it('任意值往返精度 ~1/65025', () => {
    for (const [x, y] of [
      [0.5, 0.25],
      [0.123, 0.987],
      [0.3333, 0.6666],
    ]) {
      const [r, g, b, a] = encodePositionBytes(x, y)
      const [nx, ny] = decodePositionBytes(r, g, b, a)
      expect(nx).toBeCloseTo(x, 4)
      expect(ny).toBeCloseTo(y, 4)
    }
  })

  it('超出 [0,1] 的值被钳制', () => {
    const [r, g, b, a] = encodePositionBytes(1.5, -0.5)
    const [nx, ny] = decodePositionBytes(r, g, b, a)
    expect(nx).toBeLessThanOrEqual(1)
    expect(ny).toBeGreaterThanOrEqual(0)
  })
})

describe('B6 computeWorldWrapOffsets（反子午线世界包裹）', () => {
  it('主世界恰好居中铺满屏幕（tx=-w/2）→ 仅 [0]', () => {
    const m = new Float32Array(16)
    m[0] = 2.0
    m[12] = -1.0 // 主世界 clip [-1,1]，恰好无副本露出
    expect(computeWorldWrapOffsets(m)).toEqual([0])
    m[0] = 4.5
    m[12] = -2.25
    expect(computeWorldWrapOffsets(m)).toEqual([0])
  })

  it('matrix[0] >= 2.0 且贴近反子午线（跨幅临界）→ 含相邻副本', () => {
    const m = new Float32Array(16)
    m[0] = 2.0
    m[12] = 0 // 主世界 clip [0,2]，屏幕左半露出副本 -1
    expect(computeWorldWrapOffsets(m)).toEqual([-2, 0])
    m[0] = 4.5
    m[12] = -0.15 // 主世界 clip [-0.15,4.35]，左缘露出副本 -1
    expect(computeWorldWrapOffsets(m)).toEqual([-4.5, 0])
  })

  it('matrix[0] < 2.0（露出相邻世界）→ 覆盖全部可见副本', () => {
    const m = new Float32Array(16)
    m[0] = 1.0
    m[12] = -0.5 // 主世界 clip [-0.5,0.5]，两侧各露出半屏
    expect(computeWorldWrapOffsets(m)).toEqual([-1, 0, 1])
    m[0] = 0.5
    m[12] = -0.25 // 主世界居中，屏幕含 4 个世界（clip 范围 [-1.25,1.25] 内 5 个副本相交）
    expect(computeWorldWrapOffsets(m)).toEqual([-1, -0.5, 0, 0.5, 1])
  })

  it('matrix[0] / matrix[12] 非有限值或退化值时安全回退为 [0]', () => {
    expect(computeWorldWrapOffsets(new Float32Array(16))).toEqual([0]) // 全 0 → matrix[0]=0
    const m = new Float32Array(16)
    m[0] = Number.NaN
    expect(computeWorldWrapOffsets(m)).toEqual([0])
    m[0] = -1
    expect(computeWorldWrapOffsets(m)).toEqual([0])
    m[0] = 1.0
    m[12] = Number.NaN
    expect(computeWorldWrapOffsets(m)).toEqual([0])
  })
})

describe('extractMercatorProjectionMatrix（MapLibre 5）', () => {
  it('优先使用 defaultProjectionData.mainMatrix', () => {
    const main = new Float32Array(16)
    main[0] = 1.5
    const mvp = new Float32Array(16)
    mvp[0] = 9
    const got = extractMercatorProjectionMatrix({
      defaultProjectionData: { mainMatrix: main },
      modelViewProjectionMatrix: mvp,
    } as any)
    expect(got).toBe(main)
  })

  it('无 defaultProjectionData 时返回 null（不回退 modelViewProjectionMatrix）', () => {
    // modelViewProjectionMatrix 是像素世界坐标矩阵，与 lngLatToMercatorNormalized 不兼容，
    // 会导致粒子投影到屏外。故不再回退，让上层走 matrixMissFrames 失败检测。
    const mvp = new Float32Array(16)
    mvp[5] = 2
    const got = extractMercatorProjectionMatrix({
      modelViewProjectionMatrix: mvp,
    } as any)
    expect(got).toBeNull()
  })

  it('兼容旧版直接传入 Float32Array', () => {
    const m = new Float32Array(16)
    m[10] = 3
    expect(extractMercatorProjectionMatrix(m)).toBe(m)
  })

  it('非法输入返回 null', () => {
    expect(extractMercatorProjectionMatrix(null)).toBeNull()
    expect(extractMercatorProjectionMatrix({} as any)).toBeNull()
  })
})

describe('sampleEncodedWindSpeedK', () => {
  it('在网格中心取 B 通道归一化风速', () => {
    const data = new Uint8Array(2 * 2 * 4)
    // texel (1,0): speed byte 128
    data[(0 * 2 + 1) * 4 + 2] = 128
    const k = sampleEncodedWindSpeedK(
      { data, width: 2, height: 2, west: 0, south: 0, east: 2, north: 2 },
      1.1,
      1.5,
    )
    expect(k).toBeCloseTo(128 / 255, 5)
  })

  it('超出 bbox 返回 0', () => {
    const data = new Uint8Array(4)
    data[2] = 255
    expect(
      sampleEncodedWindSpeedK(
        { data, width: 1, height: 1, west: 0, south: 0, east: 1, north: 1 },
        2,
        0.5,
      ),
    ).toBe(0)
  })
})
