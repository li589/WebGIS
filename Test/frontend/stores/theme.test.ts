/**
 * W3.4e：theme store 测试（node 环境 + stubGlobal window/document）。
 *
 * 覆盖初始偏好读取（存储值/默认 system）、系统主题解析、setTheme/toggle、
 * localStorage 持久化、system 模式下媒体查询变化联动与 onScopeDispose 清理。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { nextTick } from 'vue'
import { createPinia, setActivePinia } from 'pinia'

import { useThemeStore } from '@/stores/theme'

function makeMatchMedia(matches: boolean) {
  const listeners: Array<(e: { matches: boolean }) => void> = []
  return {
    mq: {
      matches,
      addEventListener: (_: string, fn: never) => listeners.push(fn),
      removeEventListener: (_: string, fn: never) => {
        const i = listeners.indexOf(fn)
        if (i >= 0) listeners.splice(i, 1)
      },
      trigger: (next: boolean) => listeners.forEach((fn) => fn({ matches: next })),
    },
    listeners,
  }
}

function stubEnv(opts: { stored?: string | null; systemLight?: boolean } = {}) {
  const storage = new Map<string, string>()
  if (opts.stored != null) storage.set('cgda-theme', opts.stored)
  const { mq, listeners } = makeMatchMedia(opts.systemLight ?? false)
  const docAttrs: Record<string, string> = {}
  vi.stubGlobal('window', {
    localStorage: {
      getItem: (k: string) => storage.get(k) ?? null,
      setItem: (k: string, v: string) => storage.set(k, v),
    },
    matchMedia: () => mq,
  })
  vi.stubGlobal('document', {
    documentElement: { setAttribute: (k: string, v: string) => (docAttrs[k] = v) },
  })
  return { storage, mq, docAttrs, listeners }
}

beforeEach(() => {
  vi.clearAllMocks()
  setActivePinia(createPinia())
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('初始偏好与系统解析', () => {
  it('无存储值时默认 system，按系统偏好解析 dark', () => {
    const { docAttrs } = stubEnv({ stored: null, systemLight: false })
    const store = useThemeStore()
    expect(store.preference).toBe('system')
    expect(store.mode).toBe('dark')
    expect(docAttrs['data-theme']).toBe('dark')
  })

  it('系统偏好 light 时 system 解析为 light', () => {
    stubEnv({ stored: null, systemLight: true })
    expect(useThemeStore().mode).toBe('light')
  })

  it('存储值合法时直接采用（dark/light）', () => {
    for (const stored of ['dark', 'light'] as const) {
      stubEnv({ stored })
      setActivePinia(createPinia())
      const store = useThemeStore()
      expect(store.preference).toBe(stored)
      expect(store.mode).toBe(stored)
    }
  })

  it('存储值非法时回退 system', () => {
    stubEnv({ stored: 'neon' })
    expect(useThemeStore().preference).toBe('system')
  })

  it('window 未定义（SSR 防御）返回 dark', () => {
    vi.stubGlobal('window', undefined)
    const store = useThemeStore()
    expect(store.preference).toBe('dark')
    expect(store.mode).toBe('dark')
  })
})

describe('setTheme / toggle / 持久化', () => {
  it('setTheme 更新偏好、写 DOM 并持久化', async () => {
    const { storage, docAttrs } = stubEnv()
    const store = useThemeStore()
    store.setTheme('light')
    await nextTick()
    expect(store.mode).toBe('light')
    expect(docAttrs['data-theme']).toBe('light')
    expect(storage.get('cgda-theme')).toBe('light')
  })

  it('toggle 在 dark/light 间切换，不经过 system', async () => {
    stubEnv()
    const store = useThemeStore()
    store.toggle()
    await nextTick()
    expect(store.mode).toBe('light')
    store.toggle()
    await nextTick()
    expect(store.mode).toBe('dark')
    expect(store.preference).toBe('dark')
  })
})

describe('系统主题变化联动', () => {
  it('system 偏好下媒体查询变化切换模式', () => {
    const { mq } = stubEnv({ systemLight: false })
    const store = useThemeStore()
    expect(store.mode).toBe('dark')
    mq.trigger(true)
    expect(store.mode).toBe('light')
    mq.trigger(false)
    expect(store.mode).toBe('dark')
  })

  it('非 system 偏好下媒体查询变化被忽略', async () => {
    const { mq } = stubEnv({ systemLight: false })
    const store = useThemeStore()
    store.setTheme('dark')
    await nextTick()
    mq.trigger(true)
    expect(store.mode).toBe('dark')
  })
})

describe('监听器清理', () => {
  it('$dispose 触发 onScopeDispose 移除媒体查询监听，销毁后触发不再改模式', () => {
    const { mq, listeners } = stubEnv()
    const store = useThemeStore()
    expect(listeners.length).toBe(1)
    store.$dispose()
    expect(listeners.length).toBe(0)
    const before = store.mode
    mq.trigger(!before)
    expect(store.mode).toBe(before)
  })
})
