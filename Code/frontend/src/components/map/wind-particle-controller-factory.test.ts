import { describe, expect, it, afterEach, vi } from 'vitest'

import {
  createDefaultWindParticleController,
  isWebGLAvailable,
  isWebGLWindEnabled,
  isWebGLWindUsable,
} from './wind-particle-controller-factory'
import { WindParticleOverlayController } from './wind-particle-overlay-controller'
import { WindParticleWebGLOverlayController } from './wind-particle-webgl-controller'

/**
 * 工厂函数依赖浏览器专有 API（window/document/localStorage）。
 * vitest 默认 node 环境无这些全局，故用 stubGlobal 注入完整 mock。
 */
interface StubWindow {
  location: { search: string; href: string }
  localStorage: {
    getItem: (k: string) => string | null
    setItem: (k: string, v: string) => void
    removeItem: (k: string) => void
  }
  document: {
    createElement: (tag: string) => { getContext: (id: string) => unknown }
  }
}

function makeStubWindow(search = '', webglSupported = false): StubWindow {
  const store: Record<string, string> = {}
  const glStub = webglSupported
    ? {
        getParameter: (pname: number) => {
          // MAX_VERTEX_TEXTURE_IMAGE_UNITS 常见值为 0x8B4C；任意 pname 都返回 ≥1 以满足探测
          void pname
          return 16
        },
        MAX_VERTEX_TEXTURE_IMAGE_UNITS: 0x8b4c,
      }
    : null
  return {
    location: { search, href: `http://localhost/${search}` },
    localStorage: {
      getItem: (k) => store[k] ?? null,
      setItem: (k, v) => {
        store[k] = v
      },
      removeItem: (k) => {
        delete store[k]
      },
    },
    document: {
      createElement: () => ({
        getContext: (id: string) => {
          if (!webglSupported) return null
          if (id === 'webgl2' || id === 'webgl' || id === 'experimental-webgl') return glStub
          return null
        },
      }),
    },
  }
}

describe('isWebGLWindEnabled 特性开关', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('无开关时默认开启', () => {
    vi.stubGlobal('window', makeStubWindow())
    expect(isWebGLWindEnabled()).toBe(true)
  })

  it('URL ?windgl=1 启用', () => {
    vi.stubGlobal('window', makeStubWindow('?windgl=1'))
    expect(isWebGLWindEnabled()).toBe(true)
  })

  it('URL ?windgl=0 强制关闭（优先于 localStorage）', () => {
    const w = makeStubWindow('?windgl=0')
    w.localStorage.setItem('windgl', '1')
    vi.stubGlobal('window', w)
    expect(isWebGLWindEnabled()).toBe(false)
  })

  it('localStorage windgl=0 关闭', () => {
    const w = makeStubWindow()
    w.localStorage.setItem('windgl', '0')
    vi.stubGlobal('window', w)
    expect(isWebGLWindEnabled()).toBe(false)
  })

  it('localStorage windgl=1 保持开启', () => {
    const w = makeStubWindow()
    w.localStorage.setItem('windgl', '1')
    vi.stubGlobal('window', w)
    expect(isWebGLWindEnabled()).toBe(true)
  })

  it('URL ?windgl=1 优先于 localStorage windgl=0', () => {
    const w = makeStubWindow('?windgl=1')
    w.localStorage.setItem('windgl', '0')
    vi.stubGlobal('window', w)
    expect(isWebGLWindEnabled()).toBe(true)
  })
})

describe('createDefaultWindParticleController', () => {
  const makeMap = () => ({}) as any

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('默认 + WebGL 可用时创建 WebGL controller', () => {
    vi.stubGlobal('window', makeStubWindow('', true))
    const c = createDefaultWindParticleController(makeMap())
    expect(c).toBeInstanceOf(WindParticleWebGLOverlayController)
  })

  it('默认但 WebGL 不可用时回退 Canvas', () => {
    vi.stubGlobal('window', makeStubWindow('', false))
    const c = createDefaultWindParticleController(makeMap())
    expect(c).toBeInstanceOf(WindParticleOverlayController)
  })

  it('显式 windgl=0 时创建 Canvas controller', () => {
    vi.stubGlobal('window', makeStubWindow('?windgl=0', true))
    const c = createDefaultWindParticleController(makeMap())
    expect(c).toBeInstanceOf(WindParticleOverlayController)
  })

  it('显式 windgl=1 + WebGL 可用时创建 WebGL controller', () => {
    vi.stubGlobal('window', makeStubWindow('?windgl=1', true))
    const c = createDefaultWindParticleController(makeMap())
    expect(c).toBeInstanceOf(WindParticleWebGLOverlayController)
  })
})

describe('isWebGLAvailable 浏览器探测', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('canvas.getContext 返回 null 时为 false', () => {
    vi.stubGlobal('window', makeStubWindow('', false))
    expect(isWebGLAvailable()).toBe(false)
  })

  it('canvas.getContext 返回对象时为 true', () => {
    vi.stubGlobal('window', makeStubWindow('', true))
    expect(isWebGLAvailable()).toBe(true)
  })

  it('无 window 时安全返回 false', () => {
    vi.stubGlobal('window', undefined)
    expect(isWebGLAvailable()).toBe(false)
  })
})

describe('isWebGLWindUsable WebGL 探测', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('WebGL 可用时为 true', () => {
    vi.stubGlobal('window', makeStubWindow('', true))
    expect(isWebGLWindUsable()).toBe(true)
  })

  it('无 WebGL 时为 false', () => {
    vi.stubGlobal('window', makeStubWindow('', false))
    expect(isWebGLWindUsable()).toBe(false)
  })
})
