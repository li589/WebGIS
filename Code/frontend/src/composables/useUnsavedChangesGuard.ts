/**
 * useUnsavedChangesGuard — 未保存修改的页面离开拦截。
 *
 * 多处状态（工作流编辑器 dirty、绘制要素、定时器草稿等）各自注册守卫，
 * 模块级引用计数保证只要任一来源仍处于「有未保存修改」状态，刷新/关闭
 * 页面就会触发浏览器原生确认提示（preventDefault + returnValue）。
 *
 * 浏览器限制：提示文案由浏览器统一显示（无法自定义），这是平台约束。
 *
 * 用法（响应式）：
 *   const { dirty } = useUnsavedChangesGuard(() => dirtyRef.value)
 *
 * 用法（手动）：
 *   const guard = useUnsavedChangesGuard()
 *   guard.setActive(true)   // 激活拦截
 *   guard.setActive(false)  // 解除拦截
 */

import { onScopeDispose, watch, type WatchSource } from 'vue'

type Listener = (e: BeforeUnloadEvent) => void

let _listener: Listener | null = null
let _listenerCount = 0

function _ensureListener(): void {
  if (typeof window === 'undefined' || _listener) return
  _listener = (e: BeforeUnloadEvent) => {
    // Chromium 系需要 returnValue 非空 + preventDefault；Firefox 只认 preventDefault
    e.preventDefault()
    e.returnValue = ''
  }
  window.addEventListener('beforeunload', _listener)
}

function _maybeRemoveListener(): void {
  if (_listener && _listenerCount === 0) {
    window.removeEventListener('beforeunload', _listener)
    _listener = null
  }
}

function _acquire(): void {
  _listenerCount += 1
  _ensureListener()
}

function _release(): void {
  _listenerCount = Math.max(0, _listenerCount - 1)
  _maybeRemoveListener()
}

export interface UnsavedChangesGuard {
  /** 手动激活/解除拦截 */
  setActive: (active: boolean) => void
}

/**
 * 基于响应式来源的守卫：source 为 truthy 时激活拦截。
 * 传入 getter 函数（`() => ref.value`）以保持响应性。
 */
export function useUnsavedChangesGuard(source: WatchSource<boolean>): UnsavedChangesGuard {
  let active = false

  const setActive = (next: boolean) => {
    if (next === active) return
    active = next
    if (active) _acquire()
    else _release()
  }

  watch(source, (value) => setActive(Boolean(value)), { immediate: true, flush: 'sync' })

  // 组件/作用域卸载时释放（编辑状态随组件销毁丢弃，继续拦截无意义）
  onScopeDispose(() => setActive(false))

  return { setActive }
}

/** 供测试/特殊场景直接检查全局监听态 */
export function _unsavedGuardListenerCount(): number {
  return _listenerCount
}
