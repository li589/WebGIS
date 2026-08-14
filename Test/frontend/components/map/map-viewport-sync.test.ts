import { describe, expect, it } from 'vitest'

import {
  buildMapViewportSnapshot,
  estimateLngBoundsFromCenter,
  expandLngBoundsIfNearAntimeridian,
  normalizeLngBounds,
  preferVisibleLngBounds,
  resolveVisibleLngBounds,
  resolveVisibleViewportBBox,
} from '@/components/map/map-viewport-sync'
import { tilesInBounds } from '@/services/weather-tile-api'

describe('normalizeLngBounds', () => {
  it('preserves Asia–Pacific long path when MapLibre already expanded east > 180', () => {
    // west=-20 east=200：非洲→太平洋长路径；禁止折成美洲短路径
    expect(normalizeLngBounds(-20, 200, 110)).toEqual({ west: -20, east: 200 })
  })

  it('keeps unwrapped west < -180 by shifting the whole interval', () => {
    // 相机在亚太世界副本：west=-200 east=20 若各自 wrap 会变成西半球错弧
    const out = normalizeLngBounds(-200, 20, 150)
    // 中心 150 应落在结果弧内（允许 east>180）
    expect(out.east).toBeGreaterThan(out.west)
    let c = 150
    while (c < out.west) c += 360
    while (c >= out.west + 360) c -= 360
    expect(c).toBeLessThanOrEqual(out.east)
  })

  it('flips wrong-hemisphere bounds to the arc containing map center (Asia view → not Americas)', () => {
    // 视口在亚太（center≈150），但 getBounds 折进 [-120,80]（美洲–大西洋）
    const out = normalizeLngBounds(-120, 80, 150)
    expect(out.west).toBeCloseTo(80, 5)
    expect(out.east).toBeCloseTo(240, 5)
    expect(out.west).toBeLessThan(150)
    expect(out.east).toBeGreaterThan(150)
  })

  it('expands near-global gap at antimeridian to world when center sits in the slit', () => {
    // west=-170 east=170（340°），中心在日界线缝 180°
    expect(normalizeLngBounds(-170, 170, 180)).toEqual({ west: -180, east: 180 })
  })

  it('closes near-global IDL slit even when center is inside the long arc', () => {
    // 全球视野常见：getBounds≈-170..170，中心在 0（不在缝内）——旧逻辑会留下日界线窄缝→半屏/细带
    expect(normalizeLngBounds(-170, 170, 0)).toEqual({ west: -180, east: 180 })
    expect(normalizeLngBounds(-160, 160, 20)).toEqual({ west: -180, east: 180 })
  })

  it('keeps mid-range Pacific path under near-global threshold', () => {
    // 220° 亚太长路径不应被误合成世界
    expect(normalizeLngBounds(-20, 200, 110)).toEqual({ west: -20, east: 200 })
  })

  it('extends east when east < west (classic antimeridian short path)', () => {
    expect(normalizeLngBounds(170, -175, 179)).toEqual({ west: 170, east: 185 })
  })
})

describe('estimateLngBoundsFromCenter / preferVisibleLngBounds', () => {
  it('estimates IDL-crossing arc from center and worldSize', () => {
    // 半屏 ≈ 90°：center=180 → west≈90 east≈270
    const est = estimateLngBoundsFromCenter(180, 512, 512 * 2)
    expect(est).not.toBeNull()
    expect(est!.west).toBeLessThan(180)
    expect(est!.east).toBeGreaterThan(180)
  })

  it('preferVisibleLngBounds upgrades single-hemisphere getBounds to center IDL arc', () => {
    // getBounds 只覆盖亚洲大半（未跨日界线），中心估弧跨 IDL
    const fromBounds = { west: 40, east: 160 }
    const fromCenter = { west: 100, east: 260 }
    const out = preferVisibleLngBounds(fromBounds, fromCenter)
    expect(out.east).toBeGreaterThan(180)
    expect(out.west).toBeLessThan(150)
  })

  it('preferVisibleLngBounds keeps correct short IDL path from getBounds when similar span', () => {
    const fromBounds = { west: 150, east: 210 }
    const fromCenter = { west: 155, east: 205 }
    expect(preferVisibleLngBounds(fromBounds, fromCenter)).toEqual(fromBounds)
  })

  it('preferVisibleLngBounds forces world for near-global either side', () => {
    expect(preferVisibleLngBounds({ west: -170, east: 170 }, { west: -90, east: 90 })).toEqual({
      west: -180,
      east: 180,
    })
  })

  it('expandLngBoundsIfNearAntimeridian widens Asia-only arc when center hugs IDL', () => {
    const out = expandLngBoundsIfNearAntimeridian({ west: 100, east: 175 }, 175)
    expect(out.east).toBeGreaterThan(180)
    expect(out.west).toBeLessThanOrEqual(150)
  })

  it('expandLngBoundsIfNearAntimeridian is no-op far from IDL', () => {
    expect(expandLngBoundsIfNearAntimeridian({ west: 100, east: 120 }, 110)).toEqual({
      west: 100,
      east: 120,
    })
  })
})

describe('map-viewport-sync', () => {
  it('normalizes center and bounds into EPSG:4326 snapshot', () => {
    const snapshot = buildMapViewportSnapshot({
      getCenter: () => ({ lng: 190, lat: 23 }),
      getBounds: () => ({
        getSouth: () => -95,
        getNorth: () => 96,
        getWest: () => 181,
        getEast: () => 540,
      }),
      getZoom: () => 5.8,
    })

    expect(snapshot).toEqual({
      center: { lng: -170, lat: 23 },
      bbox: {
        // 近全球跨度闭合为世界（勿留 -179..180 日界线窄缝）
        west: -180,
        south: -90,
        east: 180,
        north: 90,
        crs: 'EPSG:4326',
      },
      zoom: 5.8,
    })
  })

  it('preserves antimeridian-crossing viewport via +360 east extension', () => {
    // 视口实际跨越 170° → 180° → -180° → -175°（短路径，跨 ±180° 经线）
    // 旧实现错误交换为 west=-175/east=170（映射到地球反面，跨度 345°）
    // 新实现保留 west=170，east 扩展为 185（短路径语义，便于 tilesInBounds 归一化）
    const snapshot = buildMapViewportSnapshot({
      getCenter: () => ({ lng: -181, lat: 10 }),
      getBounds: () => ({
        getSouth: () => -10,
        getNorth: () => 20,
        getWest: () => 170,
        getEast: () => -175,
      }),
      getZoom: () => 4.5,
    })

    expect(snapshot.center.lng).toBe(179)
    expect(snapshot.bbox).toEqual({
      west: 170,
      south: -10,
      east: 185,
      north: 20,
      crs: 'EPSG:4326',
    })
  })

  it('Asia–Pacific camera with Americas-folded bounds yields Asia–Pacific bbox', () => {
    const snapshot = buildMapViewportSnapshot({
      getCenter: () => ({ lng: 150, lat: 20 }),
      getBounds: () => ({
        getSouth: () => -40,
        getNorth: () => 55,
        getWest: () => -120,
        getEast: () => 80,
      }),
      getZoom: () => 2.5,
    })
    expect(snapshot.bbox.west).toBeLessThan(150)
    expect(snapshot.bbox.east).toBeGreaterThan(150)
    // 应覆盖亚太而非仅美洲
    expect(snapshot.bbox.west).toBeGreaterThan(0)
    expect(snapshot.bbox.east).toBeGreaterThan(180)
  })

  it('upgrades single-hemisphere getBounds using worldSize when view crosses IDL', () => {
    // getBounds 只给亚洲侧；worldSize 显示半屏约跨过日界线
    const snapshot = buildMapViewportSnapshot({
      getCenter: () => ({ lng: 170, lat: 10 }),
      getBounds: () => ({
        getSouth: () => -30,
        getNorth: () => 40,
        getWest: () => 80,
        getEast: () => 170,
      }),
      getZoom: () => 2,
      getViewportWidthPx: () => 800,
      getWorldSizePx: () => 800, // halfSpan ≈ 180° → 近全球；用更大 world 保留跨 IDL
    })
    // worldSize=800, width=800 → halfSpan=180 → world
    expect(snapshot.bbox.west).toBe(-180)
    expect(snapshot.bbox.east).toBe(180)
  })

  it('upgrades Asia-only bounds to IDL-crossing when center span crosses antimeridian', () => {
    const snapshot = buildMapViewportSnapshot({
      getCenter: () => ({ lng: 170, lat: 10 }),
      getBounds: () => ({
        getSouth: () => -30,
        getNorth: () => 40,
        getWest: () => 90,
        getEast: () => 160,
      }),
      getZoom: () => 3,
      // halfSpan = 800*360/1600/2 = 90 → center±90 ≈ [80, 260]
      getViewportWidthPx: () => 800,
      getWorldSizePx: () => 1600,
    })
    expect(snapshot.bbox.east).toBeGreaterThan(180)
    expect(snapshot.bbox.west).toBeLessThan(170)
  })
})

describe('resolveVisibleLngBounds / resolveVisibleViewportBBox', () => {
  it('upgrades Asia-only getBounds with worldSize to IDL-crossing arc', () => {
    const map = {
      getCenter: () => ({ lng: 170, lat: 10 }),
      getBounds: () => ({
        getSouth: () => -30,
        getNorth: () => 40,
        getWest: () => 90,
        getEast: () => 160,
      }),
      getZoom: () => 3,
      getViewportWidthPx: () => 800,
      getWorldSizePx: () => 1600,
    }
    const lng = resolveVisibleLngBounds(map)
    expect(lng.east).toBeGreaterThan(180)
    const bbox = resolveVisibleViewportBBox(map, { clampLat: [-85, 85] })
    expect(bbox.west).toBe(lng.west)
    expect(bbox.east).toBe(lng.east)
    expect(bbox.south).toBeGreaterThanOrEqual(-85)
  })

  it('matches snapshot lng arc for near-global slit', () => {
    const map = {
      getCenter: () => ({ lng: 0, lat: 0 }),
      getBounds: () => ({
        getSouth: () => -80,
        getNorth: () => 80,
        getWest: () => -170,
        getEast: () => 170,
      }),
      getZoom: () => 1,
    }
    expect(resolveVisibleLngBounds(map)).toEqual({ west: -180, east: 180 })
    expect(buildMapViewportSnapshot(map).bbox.west).toBe(-180)
    expect(buildMapViewportSnapshot(map).bbox.east).toBe(180)
  })

  it('forces both sides of IDL when center is near ±180 even without worldSize', () => {
    // 回归：renderWorldCopies 下 getBounds 只给亚洲侧，且 transform.worldSize 未就绪
    // → 旧逻辑只拉半边瓦片，日界线「只亮一半边」
    const map = {
      getCenter: () => ({ lng: 175, lat: 10 }),
      getBounds: () => ({
        getSouth: () => -20,
        getNorth: () => 40,
        getWest: () => 100,
        getEast: () => 175,
      }),
      getZoom: () => 3,
      getViewportWidthPx: () => 800,
      // 故意不提供 getWorldSizePx / transform —— 走 zoom 回退 + 贴日界线兜底
    }
    const lng = resolveVisibleLngBounds(map)
    expect(lng.east).toBeGreaterThan(180)
    expect(lng.west).toBeLessThan(175)
    const tiles = tilesInBounds({ ...lng, south: -20, north: 40 }, 3, 0)
    const n = 8
    const xs = new Set(tiles.map((t) => t.x))
    // 必须同时覆盖靠近 n-1（+180 西侧）与 0（-180 东侧）
    expect(xs.has(n - 1) || [...xs].some((x) => x >= n - 2)).toBe(true)
    expect(xs.has(0) || xs.has(1)).toBe(true)
  })
})
