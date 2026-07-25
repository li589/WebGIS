import { describe, expect, it } from 'vitest'

import {
  clampPanelDim,
  clampPanelOffset,
  isRightDockedPanel,
  nextSizeFromResizeDelta,
  offsetXToPinRightEdge,
  shouldCompensateOffsetOnResize,
} from './control-panel-geometry'

describe('control-panel-geometry', () => {
  it('clamps size and offset', () => {
    expect(clampPanelDim(50, 100, 400)).toBe(100)
    expect(clampPanelDim(500, 100, 400)).toBe(400)
    expect(clampPanelOffset(200, 80)).toBe(80)
    expect(clampPanelOffset(-200, 80)).toBe(-80)
  })

  it('bottom-left resize grows left/down without flipping axes', () => {
    expect(
      nextSizeFromResizeDelta({
        handlePosition: 'bottom-left',
        baseWidth: 300,
        baseHeight: 400,
        deltaX: -40,
        deltaY: 60,
      }),
    ).toEqual({ width: 340, height: 460 })
  })

  it('analysis / right-dock does not compensate offset on resize', () => {
    expect(isRightDockedPanel('analysis')).toBe(true)
    expect(isRightDockedPanel('layers')).toBe(false)
    expect(
      shouldCompensateOffsetOnResize({ panelKey: 'analysis', handlePosition: 'bottom-left' }),
    ).toBe(false)
    expect(
      shouldCompensateOffsetOnResize({
        panelKey: 'layers',
        handlePosition: 'bottom-left',
        layoutPinsRightEdge: true,
      }),
    ).toBe(false)
    expect(
      shouldCompensateOffsetOnResize({ panelKey: 'layers', handlePosition: 'bottom-left' }),
    ).toBe(true)
    expect(
      shouldCompensateOffsetOnResize({ panelKey: 'layers', handlePosition: 'bottom-right' }),
    ).toBe(false)
  })

  it('pin-right offset keeps right edge when compensating', () => {
    expect(offsetXToPinRightEdge(0, 300, 360, 120)).toBe(-60)
    expect(offsetXToPinRightEdge(0, 300, 500, 80)).toBe(-80)
  })
})
