import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useUiLoadingStore } from './ui-loading'

describe('ui-loading store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.useFakeTimers()
  })

  it('hides after showImmediate + nested delayed show/hide (init catalog race)', () => {
    const loading = useUiLoadingStore()

    loading.showImmediate('初始化地图数据...')
    expect(loading.isVisible).toBe(true)
    expect(loading.mode).toBe('hero')

    loading.show()
    loading.hide()
    expect(loading.isVisible).toBe(true)
    expect(loading.mode).toBe('hero')

    loading.hide()
    expect(loading.isVisible).toBe(false)
    expect(loading.message).toBe('')
    expect(loading.mode).toBe('compact')
  })

  it('hideImmediate clears overlay regardless of counter', () => {
    const loading = useUiLoadingStore()
    loading.showImmediate('初始化地图数据...')
    loading.show()
    loading.hideImmediate()
    expect(loading.isVisible).toBe(false)
  })

  it('short delayed show never flashes if hidden before delay', () => {
    const loading = useUiLoadingStore()
    loading.show('短暂请求')
    loading.hide()
    vi.advanceTimersByTime(500)
    expect(loading.isVisible).toBe(false)
  })

  it('delayed show uses compact mode by default', () => {
    const loading = useUiLoadingStore()
    loading.show('拉取配置')
    vi.advanceTimersByTime(300)
    expect(loading.isVisible).toBe(true)
    expect(loading.mode).toBe('compact')
    loading.hide()
    expect(loading.isVisible).toBe(false)
  })
})
