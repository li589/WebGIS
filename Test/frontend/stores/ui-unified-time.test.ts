import { describe, expect, it, beforeEach, vi } from 'vitest'
import { nextTick } from 'vue'
import { createPinia, setActivePinia } from 'pinia'

/**
 * ui store 统一时间持久化：
 * - 统一模式下选定日期+钟点写入 localStorage，刷新后恢复
 * - 关闭统一模式清除持久化（回退逐层记忆机制）
 */

const UNIFIED_TIME_KEY = 'cgda.timeline.unified-time'
const UNIFIED_FLAG_KEY = 'cgda.timeline.unified'

function setupStorage(initial: Record<string, string> = {}) {
  const store = new Map<string, string>(Object.entries(initial))
  vi.stubGlobal('window', {
    localStorage: {
      getItem: (k: string) => store.get(k) ?? null,
      setItem: (k: string, v: string) => void store.set(k, v),
      removeItem: (k: string) => void store.delete(k),
      clear: () => store.clear(),
    },
  })
  return store
}

async function makeUiStore() {
  const { useUiStore } = await import('@/stores/ui')
  return useUiStore()
}

describe('ui store 统一时间持久化', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.resetModules()
  })

  it('统一模式 + 已持久化时刻：store 创建即恢复选定日期与钟点', async () => {
    setupStorage({
      [UNIFIED_FLAG_KEY]: '1',
      [UNIFIED_TIME_KEY]: JSON.stringify({ dateKey: '2025-06-15', hour: 14 }),
    })
    const ui = await makeUiStore()
    expect(ui.unifiedTimeLock).toBe(true)
    expect(ui.currentDate.getFullYear()).toBe(2025)
    expect(ui.currentDate.getMonth()).toBe(5) // 6 月（0 基）
    expect(ui.currentDate.getDate()).toBe(15)
    expect(ui.currentHour).toBe(14)
  })

  it('统一模式选定时刻变化：持久化写入 localStorage', async () => {
    const store = setupStorage({ [UNIFIED_FLAG_KEY]: '1' })
    const ui = await makeUiStore()
    ui.setHour(9)
    await nextTick() // watch 异步 flush
    const saved = store.get(UNIFIED_TIME_KEY)
    expect(saved).toBeTruthy()
    expect(JSON.parse(saved!)).toEqual({
      dateKey: expect.stringMatching(/^\d{4}-\d{2}-\d{2}$/),
      hour: 9,
    })
  })

  it('非统一模式选定时刻变化：不持久化', async () => {
    const store = setupStorage({ [UNIFIED_FLAG_KEY]: '0' })
    const ui = await makeUiStore()
    ui.setHour(7)
    await nextTick()
    expect(store.has(UNIFIED_TIME_KEY)).toBe(false)
  })

  it('关闭统一模式：清除已持久化的选定时刻', async () => {
    const store = setupStorage({
      [UNIFIED_FLAG_KEY]: '1',
      [UNIFIED_TIME_KEY]: JSON.stringify({ dateKey: '2025-06-15', hour: 14 }),
    })
    const ui = await makeUiStore()
    ui.setUnifiedTimeLock(false)
    await nextTick() // watch 异步 flush
    expect(store.has(UNIFIED_TIME_KEY)).toBe(false)
    expect(store.get(UNIFIED_FLAG_KEY)).toBe('0')
  })

  it('持久化值非法（hour 越界）：忽略并保持当前时间', async () => {
    setupStorage({
      [UNIFIED_FLAG_KEY]: '1',
      [UNIFIED_TIME_KEY]: JSON.stringify({ dateKey: '2025-06-15', hour: 99 }),
    })
    const ui = await makeUiStore()
    expect(ui.currentHour).toBeLessThanOrEqual(23)
    expect(ui.currentHour).toBeGreaterThanOrEqual(0)
  })
})
