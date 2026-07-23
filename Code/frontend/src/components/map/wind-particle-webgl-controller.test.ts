import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'

import { WindParticleWebGLOverlayController } from './wind-particle-webgl-controller'
import { WindParticleWebGLLayer } from './wind-particle-webgl-renderer'
import type { WindParticleControllerContract } from './wind-particle-controller-contract'

/** 最小 mock map：只实现 controller 在 reset/destroy/removeCatalogArtifacts 路径上会触达的方法。 */
function makeMockMap() {
  return {
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
}

describe('WindParticleWebGLOverlayController 契约', () => {
  it('满足 WindParticleControllerContract 公开 API', () => {
    const map = makeMockMap()
    const controller = new WindParticleWebGLOverlayController(map as any)
    // 类型断言：能赋值给契约接口（结构类型）
    const contract: WindParticleControllerContract = controller
    expect(typeof contract.sync).toBe('function')
    expect(typeof contract.reset).toBe('function')
    expect(typeof contract.removeCatalogArtifacts).toBe('function')
    expect(typeof contract.destroy).toBe('function')
    expect(contract.activeCatalogId).toBeNull()
  })

  it('activeCatalogId 可读写', () => {
    const controller = new WindParticleWebGLOverlayController(makeMockMap() as any)
    controller.activeCatalogId = 'wind-field'
    expect(controller.activeCatalogId).toBe('wind-field')
    controller.activeCatalogId = null
    expect(controller.activeCatalogId).toBeNull()
  })

  it('reset/destroy 在无任何层时安全不抛错', () => {
    const controller = new WindParticleWebGLOverlayController(makeMockMap() as any)
    expect(() => controller.reset()).not.toThrow()
    expect(() => controller.destroy()).not.toThrow()
  })

  it('removeCatalogArtifacts 未命中激活图层时返回 false', () => {
    const controller = new WindParticleWebGLOverlayController(makeMockMap() as any)
    controller.activeCatalogId = 'wind-field'
    expect(controller.removeCatalogArtifacts('other-layer')).toBe(false)
    expect(controller.activeCatalogId).toBe('wind-field')
  })

  it('removeCatalogArtifacts 命中激活图层时 reset 并清空 id', () => {
    const controller = new WindParticleWebGLOverlayController(makeMockMap() as any)
    controller.activeCatalogId = 'wind-field'
    expect(controller.removeCatalogArtifacts('wind-field')).toBe(true)
    expect(controller.activeCatalogId).toBeNull()
  })
  it('style 未加载时排队到 style.load 再 addLayer', () => {
    const map = makeMockMap()
    map.isStyleLoaded = vi.fn(() => false)
    const controller = new WindParticleWebGLOverlayController(map as any)
    // 通过私有路径：sync 会 ensureWebGLLayer；这里直接调用内部方法不便，
    // 用 reset 后构造层：先强制 isStyleLoaded false，再触发 ensure via sync 过重。
    // 直接验证 once 注册：通过调用 destroy 前的 ensure 等价行为。
    ;(controller as any).ensureWebGLLayer()
    expect(map.once).toHaveBeenCalledWith('style.load', expect.any(Function))
    expect(map.addLayer).not.toHaveBeenCalled()

    map.isStyleLoaded = vi.fn(() => true)
    const handler = map.once.mock.calls[0][1] as () => void
    handler()
    expect(map.addLayer).toHaveBeenCalled()
  })
})

describe('WindParticleWebGLLayer 结构', () => {
  // requestAnimationFrame 是浏览器专有 API；node 测试环境需 stub
  const originalRaf = globalThis.requestAnimationFrame
  const originalCancelRaf = (globalThis as any).cancelAnimationFrame

  beforeEach(() => {
    globalThis.requestAnimationFrame = vi.fn(() => 1) as any
    ;(globalThis as any).cancelAnimationFrame = vi.fn()
  })

  afterEach(() => {
    globalThis.requestAnimationFrame = originalRaf
    ;(globalThis as any).cancelAnimationFrame = originalCancelRaf
  })

  it('默认 id 与 CustomLayerInterface 必需字段', () => {
    const layer = new WindParticleWebGLLayer()
    expect(layer.id).toBe('wind-particle-webgl')
    expect(layer.type).toBe('custom')
    expect(layer.renderingMode).toBe('2d')
    expect(typeof layer.onAdd).toBe('function')
    expect(typeof layer.render).toBe('function')
    expect(typeof layer.onRemove).toBe('function')
  })

  it('自定义 id 生效', () => {
    const layer = new WindParticleWebGLLayer('my-layer')
    expect(layer.id).toBe('my-layer')
  })

  it('dispose/start/stop 在未 onAdd 时安全不抛错', () => {
    const layer = new WindParticleWebGLLayer()
    expect(() => layer.start()).not.toThrow()
    expect(() => layer.stop()).not.toThrow()
    expect(() => layer.dispose()).not.toThrow()
  })
})

describe('WindParticleWebGLOverlayController fetch abort', () => {
  const originalFetch = globalThis.fetch

  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    globalThis.fetch = originalFetch
    vi.useRealTimers()
  })

  it('新 sync 开始时中断进行中的 geojson fetch', async () => {
    const signals: AbortSignal[] = []
    globalThis.fetch = vi.fn((_url: string, init?: RequestInit) => {
      const signal = init!.signal as AbortSignal
      signals.push(signal)
      return new Promise((_resolve, reject) => {
        if (signal.aborted) {
          reject(new DOMException('Aborted', 'AbortError'))
          return
        }
        signal.addEventListener('abort', () => {
          reject(new DOMException('Aborted', 'AbortError'))
        })
      })
    }) as typeof fetch

    const controller = new WindParticleWebGLOverlayController(makeMockMap() as any)
    controller.activeCatalogId = 'wind-field'

    const overlayState = {
      catalogId: 'wind-field',
      geojsonUrl: 'https://example.com/a.geojson',
      geojsonData: null,
      renderHint: { paint_mode: 'particle_flow' },
    } as any

    const syncOptions = {
      overlayToken: 1,
      getSyncWeatherToken: () => 1,
      getEnabledParticleFlowCatalogId: () => 'wind-field',
    }

    const first = controller.sync(overlayState, syncOptions)
    expect(signals).toHaveLength(1)
    expect(signals[0].aborted).toBe(false)

    const second = controller.sync(
      { ...overlayState, geojsonUrl: 'https://example.com/b.geojson' },
      syncOptions,
    )
    expect(signals).toHaveLength(2)
    expect(signals[0].aborted).toBe(true)

    controller.reset()
    await Promise.allSettled([first, second])
  })
})
