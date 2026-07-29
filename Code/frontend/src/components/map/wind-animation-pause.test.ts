import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { WindParticleOverlayController } from './wind-particle-overlay-controller'
import { WindParticleWebGLOverlayController } from './wind-particle-webgl-controller'
import type { WindParticleControllerContract } from './wind-particle-controller-contract'

describe('风场动画暂停（全屏面板）', () => {
  beforeEach(() => {
    vi.stubGlobal(
      'requestAnimationFrame',
      vi.fn(() => 1),
    )
    vi.stubGlobal('cancelAnimationFrame', vi.fn())
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('Canvas / WebGL 控制器均暴露 setAnimationPaused', () => {
    const map = {
      getLayer: vi.fn(() => undefined),
      removeLayer: vi.fn(),
      getSource: vi.fn(() => undefined),
      removeSource: vi.fn(),
      addLayer: vi.fn(),
      isStyleLoaded: vi.fn(() => true),
      on: vi.fn(),
      once: vi.fn(),
      off: vi.fn(),
      triggerRepaint: vi.fn(),
      getZoom: vi.fn(() => 5),
      getCanvasContainer: vi.fn(() => ({ appendChild: vi.fn() })),
      getCanvas: vi.fn(() => ({
        width: 800,
        height: 600,
        style: { width: '800px', height: '600px' },
      })),
      getContainer: vi.fn(() => ({ clientWidth: 800, clientHeight: 600 })),
    }

    const canvas: WindParticleControllerContract = new WindParticleOverlayController(map as any)
    const webgl: WindParticleControllerContract = new WindParticleWebGLOverlayController(map as any)
    expect(typeof canvas.setAnimationPaused).toBe('function')
    expect(typeof webgl.setAnimationPaused).toBe('function')
    expect(() => canvas.setAnimationPaused(true)).not.toThrow()
    expect(() => canvas.setAnimationPaused(false)).not.toThrow()
    expect(() => webgl.setAnimationPaused(true)).not.toThrow()
    expect(() => webgl.setAnimationPaused(false)).not.toThrow()
  })
})
