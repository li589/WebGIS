import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useUiLoadingStore } from '@/stores/ui-loading'

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

describe('ui-loading 看门狗（2026-08-25 顶栏光带永久加载反馈）', () => {
  it('计数泄漏时 150s 后强制复位', () => {
    const loading = useUiLoadingStore()
    // 模拟泄漏：show 两次但只 hide 一次
    loading.show()
    loading.show()
    loading.hide()
    vi.advanceTimersByTime(300)
    expect(loading.isVisible).toBe(true) // counter=1 仍显示

    vi.advanceTimersByTime(150_000)
    expect(loading.isVisible).toBe(false)
    expect(loading.message).toBe('')
  })

  it('看门狗触发后计数归零，新 show/hide 对恢复平衡', () => {
    const loading = useUiLoadingStore()
    loading.show() // 泄漏：永不 hide
    vi.advanceTimersByTime(300)
    vi.advanceTimersByTime(150_000)
    expect(loading.isVisible).toBe(false)

    // 复位后正常配对使用
    loading.show('新请求')
    loading.hide()
    expect(loading.isVisible).toBe(false)
  })

  it('hide 正常配对完成后看门狗解除，不误伤后续', () => {
    const loading = useUiLoadingStore()
    loading.show('正常请求')
    loading.hide()
    // 看门狗到期时 counter=0 且不可见 → 无操作不报错
    vi.advanceTimersByTime(150_000)
    expect(loading.isVisible).toBe(false)
  })
})
