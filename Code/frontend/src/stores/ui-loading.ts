/**
 * 全局 UI Loading 状态管理
 *
 * 两档动效（由 LoadingOverlay 渲染）：
 * - hero：全屏「地球+卫星」— 启动、大面板首次打开、大范围切换
 * - compact：顶栏细进度 — 普通 API 请求等轻量等待（默认 show）
 *
 * 并发计数：全部完成后才隐藏；短请求 300ms 延迟显示避免闪烁。
 * 组件内局部等待请用 InlineLoader，不要走本 store。
 */
import { defineStore } from 'pinia'
import { ref } from 'vue'

export type UiLoadingMode = 'hero' | 'compact'

const SHOW_DELAY_MS = 300

export const useUiLoadingStore = defineStore('ui-loading', () => {
  let _counter = 0
  let _showTimer: ReturnType<typeof setTimeout> | null = null
  let _pendingMessage = ''
  let _pendingMode: UiLoadingMode = 'compact'

  const isVisible = ref(false)
  const message = ref('')
  /** 当前展示档位：hero=全屏地球卫星，compact=顶栏细条 */
  const mode = ref<UiLoadingMode>('compact')

  function clearShowTimer() {
    if (_showTimer !== null) {
      clearTimeout(_showTimer)
      _showTimer = null
    }
  }

  function applyVisible(nextMode: UiLoadingMode, msg: string) {
    isVisible.value = true
    mode.value = nextMode
    message.value = msg
    _pendingMessage = msg
    _pendingMode = nextMode
  }

  /**
   * 轻量 loading（默认 compact）。短请求 &lt;300ms 不显示。
   * 已在 hero 全屏时只更新文案，不降级打断大动画。
   */
  function show(msg: string = '', nextMode: UiLoadingMode = 'compact') {
    _counter++
    if (msg) _pendingMessage = msg
    if (isVisible.value) {
      if (msg) message.value = msg
      // hero 进行中不降级为 compact
      if (mode.value !== 'hero' && nextMode === 'hero') {
        mode.value = 'hero'
      }
      return
    }
    _pendingMode = nextMode
    if (_showTimer !== null) return
    _showTimer = setTimeout(() => {
      _showTimer = null
      if (_counter <= 0) return
      applyVisible(_pendingMode, _pendingMessage)
    }, SHOW_DELAY_MS)
  }

  function hide() {
    _counter = Math.max(0, _counter - 1)
    if (_counter > 0) return
    clearShowTimer()
    isVisible.value = false
    message.value = ''
    _pendingMessage = ''
    mode.value = 'compact'
    _pendingMode = 'compact'
  }

  /**
   * 立即全屏 hero（地球+卫星）。用于启动 / 大面板首开。
   */
  function showImmediate(msg: string = '', nextMode: UiLoadingMode = 'hero') {
    clearShowTimer()
    _counter++
    applyVisible(nextMode, msg)
  }

  /** 强制清空（异常恢复 / 面板挂载完成） */
  function hideImmediate() {
    _counter = 0
    clearShowTimer()
    isVisible.value = false
    message.value = ''
    _pendingMessage = ''
    mode.value = 'compact'
    _pendingMode = 'compact'
  }

  return {
    isVisible,
    message,
    mode,
    show,
    hide,
    showImmediate,
    hideImmediate,
  }
})
