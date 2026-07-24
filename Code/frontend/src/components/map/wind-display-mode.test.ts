import { describe, expect, it } from 'vitest'

import {
  paintModeToWindDisplayMode,
  windDisplayModeChip,
  windDisplayModeLabel,
  windDisplayModeToPaintMode,
} from './wind-display-mode'

describe('wind-display-mode dual-axis mapping', () => {
  it('maps UI particle to catalog particle_flow', () => {
    expect(windDisplayModeChip('particle')).toBe('particle_flow')
    expect(windDisplayModeToPaintMode('particle')).toBe('particle_flow')
    expect(paintModeToWindDisplayMode('particle_flow')).toBe('particle')
  })

  it('exposes Chinese labels for UI (never paint_mode ids)', () => {
    expect(windDisplayModeLabel('particle')).toBe('粒子流')
    expect(windDisplayModeLabel('streamline')).toBe('流量场')
    expect(windDisplayModeLabel('off')).toBe('关闭')
  })

  it('does not treat barb as a WindDisplayMode', () => {
    expect(paintModeToWindDisplayMode('barb')).toBeNull()
    expect(paintModeToWindDisplayMode('grid_fill')).toBeNull()
  })
})
