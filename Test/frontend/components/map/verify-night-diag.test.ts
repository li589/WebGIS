import { describe, expect, it } from 'vitest'
import { buildNightHemisphereGeoJSON } from '@/components/map/globe-scene-utils'

function ringArea(pts: number[][]): number {
  let a = 0
  for (let i = 0; i < pts.length - 1; i++) {
    a += pts[i][0] * pts[i + 1][1] - pts[i + 1][0] * pts[i][1]
  }
  return Math.abs(a) / 2
}

describe('夜半球面积数值验证（临时诊断）', () => {
  it('各时刻面积应为半球量级（>10000 sq.deg）且全夜核存在', () => {
    for (const [label, hour, date] of [
      ['hour=12 today', 12, new Date('2026-08-27T00:00:00Z')],
      ['hour=0 today', 0, new Date('2026-08-27T00:00:00Z')],
      ['hour=18 today', 18, new Date('2026-08-27T00:00:00Z')],
      ['hour=6 solstice', 6, new Date('2026-06-21T00:00:00Z')],
    ] as const) {
      const json = buildNightHemisphereGeoJSON(hour, date)
      let totalArea = 0
      let coreArea = 0
      for (const f of json.features) {
        const area = ringArea(f.geometry.coordinates[0])
        totalArea += area
        if (f.properties.tier === 36) coreArea += area
      }
      console.log(label, 'feats:', json.features.length, 'total:', Math.round(totalArea), 'core:', Math.round(coreArea))
      expect(totalArea).toBeGreaterThan(10000)
      expect(coreArea).toBeGreaterThan(5000)
    }
  })
})
