/**
 * 全局 UI Loading 状态管理
 *
 * 设计要点：
 * 1. 并发计数器：多个请求同时进行时，全部完成才隐藏（counter-- 到 0）
 * 2. 300ms 延迟显示：短请求（< 300ms）不显示 loading，避免闪烁
 * 3. showImmediate：用于首次加载等明确需要立即显示的场景（跳过延迟）
 * 4. 轮询请求应传 silent=true 跳过 loading（在 runtime-api.ts 中处理）
 */
import { defineStore } from 'pinia'
import { ref } from 'vue'

// 延迟显示阈值（毫秒）：请求耗时超过此值才显示 loading
const SHOW_DELAY_MS = 300

export const useUiLoadingStore = defineStore('ui-loading', () => {
  // 并发计数器：正在进行的 loading 触发数
  let _counter = 0
  // 延迟显示定时器
  let _showTimer: ReturnType<typeof setTimeout> | null = null
  // 延迟期间暂存的消息（真正显示时使用）
  let _pendingMessage = ''

  const isVisible = ref(false)
  const message = ref('')

  /**
   * 显示 loading（带 300ms 延迟）。
   * 短请求在 300ms 内调用 hide() 则不会显示。
   * @param msg 可选提示文字
   */
  function show(msg: string = '') {
    _counter++
    if (msg) _pendingMessage = msg
    // 已由 showImmediate 显示时，只记账，不要再挂延迟定时器（否则 hide 归零会误吞 isVisible）
    if (isVisible.value) {
      if (msg) message.value = msg
      return
    }
    // 如果已在等待显示，只需更新消息
    if (_showTimer !== null) return
    // 启动延迟显示
    _showTimer = setTimeout(() => {
      _showTimer = null
      // 定时器触发时若计数已归零，不再显示
      if (_counter <= 0) return
      isVisible.value = true
      message.value = _pendingMessage
    }, SHOW_DELAY_MS)
  }

  /**
   * 隐藏 loading（计数器递减，到 0 才真正隐藏）。
   */
  function hide() {
    _counter = Math.max(0, _counter - 1)
    if (_counter > 0) return
    // counter 归零：取消待显示定时器，并强制关掉遮罩
    // （即便此前是 showImmediate 已显示，也不能只清 timer 而留下 isVisible=true）
    if (_showTimer !== null) {
      clearTimeout(_showTimer)
      _showTimer = null
    }
    isVisible.value = false
    message.value = ''
    _pendingMessage = ''
  }

  /**
   * 立即显示 loading（跳过 300ms 延迟）。
   * 用于首次加载等明确需要立即反馈的场景。
   */
  function showImmediate(msg: string = '') {
    // 取消任何待执行的延迟显示
    if (_showTimer !== null) {
      clearTimeout(_showTimer)
      _showTimer = null
    }
    _counter++
    isVisible.value = true
    message.value = msg
    _pendingMessage = msg
  }

  /**
   * 立即隐藏 loading（重置计数器）。
   * 用于异常恢复或组件卸载时清理。
   */
  function hideImmediate() {
    _counter = 0
    if (_showTimer !== null) {
      clearTimeout(_showTimer)
      _showTimer = null
    }
    isVisible.value = false
    message.value = ''
    _pendingMessage = ''
  }

  return {
    isVisible,
    message,
    show,
    hide,
    showImmediate,
    hideImmediate,
  }
})
