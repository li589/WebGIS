import { describe, expect, it } from 'vitest'
import { buildNightMaskPixels, NIGHT_MASK_RGBA } from '@/components/map/globe-night-mask'

describe('夜半球光栅遮罩（渲染可行性回归）', () => {
  it('典型时刻均有昼夜两侧像素', () => {
    for (const [label, hour, date] of [
      ['hour=12 today', 12, new Date('2026-08-27T00:00:00Z')],
      ['hour=0 today', 0, new Date('2026-08-27T00:00:00Z')],
      ['hour=18 today', 18, new Date('2026-08-27T00:00:00Z')],
      ['hour=6 solstice', 6, new Date('2026-06-21T00:00:00Z')],
    ] as const) {
      const data = buildNightMaskPixels(360, 180, hour, date)
      let night = 0
      let day = 0
      for (let i = 3; i < data.length; i += 4) {
        if (data[i] > 0) night++
        else day++
      }
      console.log(label, 'night px', night, 'day px', day)
      expect(night).toBeGreaterThan(1000)
      expect(day).toBeGreaterThan(1000)
      expect(NIGHT_MASK_RGBA.a).toBeGreaterThan(0)
    }
  })
})
