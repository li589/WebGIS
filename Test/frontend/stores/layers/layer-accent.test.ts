import { describe, expect, it } from 'vitest'
import { allocateLayerAccent, LAYER_ACCENT_PALETTE } from '@/stores/layers/layer-accent'

describe('allocateLayerAccent', () => {
  it('prefers catalog color when unused', () => {
    const style = allocateLayerAccent([], '#38bdf8')
    expect(style.accentColor).toBe('#38bdf8')
    expect(style.chipTone).toContain('56, 189, 248')
  })

  it('picks a distinct palette color when preferred is taken', () => {
    const used = ['#38bdf8']
    const style = allocateLayerAccent(used, '#38bdf8')
    expect(style.accentColor).not.toBe('#38bdf8')
    expect(LAYER_ACCENT_PALETTE).toContain(style.accentColor as (typeof LAYER_ACCENT_PALETTE)[number])
  })
})
