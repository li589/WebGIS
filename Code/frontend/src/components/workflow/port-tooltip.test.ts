import { describe, expect, it } from 'vitest'
import { buildPortTooltip } from './port-tooltip'

describe('buildPortTooltip', () => {
  it('builds a friendly bbox input tip without arrow clutter', () => {
    const model = buildPortTooltip({
      direction: 'input',
      name: 'bbox',
      type: 'geometry:bbox',
      description: '空间裁剪 ← 空间范围节点',
      required: false,
      suggestTitles: ['空间范围', '地图视口'],
    })
    expect(model.title).toBe('bbox')
    expect(model.badge).toBe('输入')
    expect(model.body).not.toContain('←')
    expect(model.body).toMatch(/空间|裁剪|西|范围/)
    expect(model.tips.some((t) => t.includes('空间范围'))).toBe(true)
  })

  it('explains time_range outputs', () => {
    const model = buildPortTooltip({
      direction: 'output',
      name: 'time_range',
      type: 'value:time_range',
      description: '时间范围输出',
    })
    expect(model.tone).toBe('out')
    expect(model.typeLabel).toContain('时间')
    expect(model.body.length).toBeGreaterThan(20)
  })
})
