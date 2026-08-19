import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { effectScope, ref } from 'vue'
import {
  useUnsavedChangesGuard,
  _unsavedGuardListenerCount,
} from '@/composables/useUnsavedChangesGuard'

/**
 * useUnsavedChangesGuard — 未保存修改的 beforeunload 拦截（引用计数）。
 *
 * 验证：
 * - dirty 变化激活/解除全局监听
 * - 多守卫并存时引用计数（全部解除后才移除监听）
 * - 作用域销毁自动释放
 * - 监听器行为（preventDefault + returnValue）
 */

describe('useUnsavedChangesGuard', () => {
  let addSpy: ReturnType<typeof vi.fn>
  let removeSpy: ReturnType<typeof vi.fn>
  let registered: ((e: BeforeUnloadEvent) => void) | null

  beforeEach(() => {
    registered = null
    addSpy = vi.fn((_, listener: (e: BeforeUnloadEvent) => void) => {
      registered = listener
    })
    removeSpy = vi.fn()
    vi.stubGlobal('window', {
      addEventListener: addSpy,
      removeEventListener: removeSpy,
    })
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('dirty 翻转激活/解除全局 beforeunload 监听', () => {
    const scope = effectScope()
    scope.run(() => {
      const dirty = ref(false)
      useUnsavedChangesGuard(() => dirty.value)
      expect(_unsavedGuardListenerCount()).toBe(0)
      expect(addSpy).not.toHaveBeenCalled()

      dirty.value = true
      expect(_unsavedGuardListenerCount()).toBe(1)
      expect(addSpy).toHaveBeenCalledWith('beforeunload', expect.any(Function))

      dirty.value = false
      expect(_unsavedGuardListenerCount()).toBe(0)
      expect(removeSpy).toHaveBeenCalledWith('beforeunload', registered)
    })
    scope.stop()
  })

  it('多守卫引用计数：全部解除后才移除监听', () => {
    const scope = effectScope()
    scope.run(() => {
      const a = ref(false)
      const b = ref(false)
      useUnsavedChangesGuard(() => a.value)
      useUnsavedChangesGuard(() => b.value)

      a.value = true
      b.value = true
      expect(_unsavedGuardListenerCount()).toBe(2)
      expect(removeSpy).not.toHaveBeenCalled()

      a.value = false
      expect(_unsavedGuardListenerCount()).toBe(1)
      expect(removeSpy).not.toHaveBeenCalled()

      b.value = false
      expect(_unsavedGuardListenerCount()).toBe(0)
      expect(removeSpy).toHaveBeenCalled()
    })
    scope.stop()
  })

  it('作用域销毁自动释放守卫', () => {
    const scope = effectScope()
    scope.run(() => {
      const dirty = ref(true)
      useUnsavedChangesGuard(() => dirty.value)
      expect(_unsavedGuardListenerCount()).toBe(1)
    })
    scope.stop()
    expect(_unsavedGuardListenerCount()).toBe(0)
    expect(removeSpy).toHaveBeenCalled()
  })

  it('监听器触发 preventDefault + returnValue（浏览器原生确认提示）', () => {
    const scope = effectScope()
    scope.run(() => {
      const dirty = ref(true)
      useUnsavedChangesGuard(() => dirty.value)
    })
    expect(registered).not.toBeNull()
    const event = {
      preventDefault: vi.fn(),
      returnValue: undefined as string | undefined,
    }
    registered!(event as unknown as BeforeUnloadEvent)
    expect(event.preventDefault).toHaveBeenCalled()
    expect(event.returnValue).toBe('')
    scope.stop()
  })

  it('守卫交错生命周期：第一个销毁后第二个仍拦截', () => {
    const scopeA = effectScope()
    const scopeB = effectScope()
    scopeA.run(() => {
      useUnsavedChangesGuard(() => true)
    })
    scopeB.run(() => {
      useUnsavedChangesGuard(() => true)
    })
    expect(_unsavedGuardListenerCount()).toBe(2)
    scopeA.stop()
    expect(_unsavedGuardListenerCount()).toBe(1)
    expect(removeSpy).not.toHaveBeenCalled()
    scopeB.stop()
    expect(_unsavedGuardListenerCount()).toBe(0)
  })
})
