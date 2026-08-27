import { describe, expect, it } from 'vitest'
import { buildNightHemisphereGeoJSON } from '@/components/map/globe-scene-utils'

function ringArea(pts: number[][]): number {
  let a = 0
  for (let i = 0; i < pts.length - 1; i++) {
    a += pts[i][0] * pts[i + 1][1] - pts[i + 1][0] * pts[i][1]
  }
  return Math.abs(a) / 2
}

describe('夜半球面积数值验证（渲染可行性回归）', () => {
  it('夜核多边形面积应为半球量级（>10000 sq.deg），terminator 线存在', () => {
    for (const [label, hour, date] of [
      ['hour=12 today', 12, new Date('2026-08-27T00:00:00Z')],
      ['hour=0 today', 0, new Date('2026-08-27T00:00:00Z')],
      ['hour=18 today', 18, new Date('2026-08-27T00:00:00Z')],
      ['hour=6 solstice', 6, new Date('2026-06-21T00:00:00Z')],
    ] as const) {
      const json = buildNightHemisphereGeoJSON(hour, date)
      let coreArea = 0
      let termCount = 0
      for (const f of json.features) {
        if (f.properties.hemisphere === 'night-core') {
          coreArea += ringArea(f.geometry.coordinates[0] as number[][])
        } else if (f.properties.hemisphere === 'terminator') {
          termCount++
        }
      }
      console.log(label, 'feats:', json.features.length, 'coreArea:', Math.round(coreArea), 'terms:', termCount)
      // 夜核覆盖夜半球（平面投影下南极变形，量级校验）
      expect(coreArea).toBeGreaterThan(10000)
      // 晨昏线（line-blur 羽化载体）必须存在
      expect(termCount).toBeGreaterThan(0)
    }
  })
})
