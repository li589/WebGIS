/**
 * useAnimatedNumber — 平滑滚动数值 Composable
 *
 * 核心特性：
 * 1. 基于 requestAnimationFrame 与自然物理阻尼（easeOutCubic）插值过渡；
 * 2. 严格遵循无障碍减少动效约定（isReducedMotionActive），开启时瞬时切换最终值，无任何延迟与动画；
 * 3. 完善的并发安全与清理机制：数值连续更新或组件销毁时自动 cancel 上一帧 rAF。
 */
import { ref, watch, onBeforeUnmount, getCurrentInstance, type Ref } from 'vue'
import { isReducedMotionActive } from '../services/motion-preference'

export interface AnimatedNumberOptions {
  duration?: number // 毫秒，默认 350
  precision?: number // 小数位数，默认 0
  easing?: (t: number) => number // 缓动函数，默认 easeOutCubic
}

/** 经典自然阻尼 ease-out cubic 缓动 */
export function easeOutCubic(t: number): number {
  return 1 - Math.pow(1 - t, 3)
}

export function useAnimatedNumber(
  source: Ref<number> | (() => number),
  options: AnimatedNumberOptions = {},
) {
  const { duration = 350, precision = 0, easing = easeOutCubic } = options

  const getSourceValue = typeof source === 'function' ? source : () => source.value
  const initial = Number(getSourceValue()) || 0
  const displayValue = ref(initial)

  let rafId: number | null = null
  let startTime = 0
  let startVal = initial
  let targetVal = initial

  function cancelAnimation() {
    if (rafId !== null) {
      cancelAnimationFrame(rafId)
      rafId = null
    }
  }

  function step(timestamp: number) {
    if (!startTime) startTime = timestamp
    const elapsed = timestamp - startTime
    const progress = Math.min(1, elapsed / duration)
    const eased = easing(progress)
    const current = startVal + (targetVal - startVal) * eased

    const factor = Math.pow(10, precision)
    displayValue.value = Math.round(current * factor) / factor

    if (progress < 1) {
      rafId = requestAnimationFrame(step)
    } else {
      displayValue.value = targetVal
      rafId = null
    }
  }

  watch(getSourceValue, (newVal) => {
    const target = Number(newVal) || 0
    if (isReducedMotionActive() || duration <= 0) {
      cancelAnimation()
      displayValue.value = target
      return
    }

    cancelAnimation()
    startVal = displayValue.value
    targetVal = target
    startTime = 0
    rafId = requestAnimationFrame(step)
  })

  if (getCurrentInstance()) {
    onBeforeUnmount(() => {
      cancelAnimation()
    })
  }

  return {
    displayValue,
    cancelAnimation,
  }
}
