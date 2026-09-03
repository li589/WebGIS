import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  getGlobeBackgroundMode,
  getGlobeRenderEngine,
  is3DViewExperimentalEnabled,
  set3DViewExperimentalEnabled,
  setGlobeBackgroundMode,
  setGlobeRenderEngine,
  subscribe3DViewExperimental,
  subscribeGlobeScene,
} from '@/services/settings-local'

function makeMemoryStorage(): Storage {
  const map = new Map<string, string>()
  return {
    get length() {
      return map.size
    },
    clear() {
      map.clear()
    },
    getItem(key: string) {
      return map.has(key) ? map.get(key)! : null
    },
    key(index: number) {
      return [...map.keys()][index] ?? null
    },
    removeItem(key: string) {
      map.delete(key)
    },
    setItem(key: string, value: string) {
      map.set(key, String(value))
    },
  }
}

beforeEach(() => {
  const local = makeMemoryStorage()
  const session = makeMemoryStorage()
  vi.stubGlobal('localStorage', local)
  vi.stubGlobal('sessionStorage', session)
  vi.stubGlobal('window', { localStorage: local, sessionStorage: session })
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('3D 实验视图本地偏好', () => {
  it('默认关闭（opt-in 实验功能）', () => {
    expect(is3DViewExperimentalEnabled()).toBe(false)
  })

  it('勾选后持久化并可读回', () => {
    set3DViewExperimentalEnabled(true)
    expect(is3DViewExperimentalEnabled()).toBe(true)
    set3DViewExperimentalEnabled(false)
    expect(is3DViewExperimentalEnabled()).toBe(false)
  })

  it('勾选状态变化时通知订阅者（DashboardView 实时响应）', () => {
    const seen: boolean[] = []
    const unsubscribe = subscribe3DViewExperimental(() => {
      seen.push(is3DViewExperimentalEnabled())
    })
    set3DViewExperimentalEnabled(true)
    set3DViewExperimentalEnabled(false)
    unsubscribe()
    // 退订后不再触发
    set3DViewExperimentalEnabled(true)
    expect(seen).toEqual([true, false])
    expect(is3DViewExperimentalEnabled()).toBe(true)
  })

  it('订阅者抛异常不阻断其它监听与写入', () => {
    let secondCalled = false
    const bad = subscribe3DViewExperimental(() => {
      throw new Error('listener boom')
    })
    const good = subscribe3DViewExperimental(() => {
      secondCalled = true
    })
    expect(() => set3DViewExperimentalEnabled(true)).not.toThrow()
    expect(secondCalled).toBe(true)
    expect(is3DViewExperimentalEnabled()).toBe(true)
    bad()
    good()
  })

  it('持久化太阳系背景模式', () => {
    expect(getGlobeBackgroundMode()).toBe('auto')
    setGlobeBackgroundMode('solar_system')
    expect(getGlobeBackgroundMode()).toBe('solar_system')
    setGlobeBackgroundMode('starfield')
    expect(getGlobeBackgroundMode()).toBe('starfield')
  })

  it('3D 渲染引擎默认 maplibre，可切换并回退非法值', () => {
    expect(getGlobeRenderEngine()).toBe('maplibre')
    setGlobeRenderEngine('cesium')
    expect(getGlobeRenderEngine()).toBe('cesium')
    setGlobeRenderEngine('maplibre')
    expect(getGlobeRenderEngine()).toBe('maplibre')

    // 非法值回退
    const raw = JSON.parse(localStorage.getItem('cgda.settings_ui') || '{}') as Record<
      string,
      unknown
    >
    raw.globeRenderEngine = 'unity'
    localStorage.setItem('cgda.settings_ui', JSON.stringify(raw))
    expect(getGlobeRenderEngine()).toBe('maplibre')
  })

  it('渲染引擎变更通知 globe scene 订阅者', () => {
    const seen: string[] = []
    const unsubscribe = subscribeGlobeScene(() => {
      seen.push(getGlobeRenderEngine())
    })
    setGlobeRenderEngine('cesium')
    setGlobeRenderEngine('maplibre')
    unsubscribe()
    setGlobeRenderEngine('cesium')
    expect(seen).toEqual(['cesium', 'maplibre'])
  })
})
