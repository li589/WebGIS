/**
 * useSpotlight — 卡片光标聚光灯微反馈 Composable
 *
 * 在目标 DOM 元素上监听 pointermove，计算局部相对坐标并赋给 CSS 变量：
 * --spotlight-x, --spotlight-y, --spotlight-opacity
 * 结合 CSS radial-gradient 呈现柔和现代的边缘光晕。
 * 遵循无障碍约定与性能守卫：后台或 reduce-motion 下自动跳过。
 */
import { onBeforeUnmount, watch, type Ref } from 'vue'
import { isReducedMotionActive } from '../services/motion-preference'

export interface SpotlightOptions {
  color?: string
  disabled?: boolean
}

export function useSpotlight(
  targetRef: Ref<HTMLElement | null | undefined>,
  options: SpotlightOptions = {},
) {
  let isMoving = false
  let pendingEvent: PointerEvent | null = null
  let rafId: number | null = null

  function onPointerMove(e: PointerEvent) {
    if (isReducedMotionActive() || options.disabled) return
    // 触控笔/手指触屏不产生连续聚光灯，避免移动端无谓开销
    if (e.pointerType === 'touch') return

    pendingEvent = e
    if (!isMoving) {
      isMoving = true
      rafId = requestAnimationFrame(updateSpotlight)
    }
  }

  function updateSpotlight() {
    isMoving = false
    const el = targetRef.value
    if (!el || !pendingEvent) return

    const rect = el.getBoundingClientRect()
    const x = pendingEvent.clientX - rect.left
    const y = pendingEvent.clientY - rect.top

    el.style.setProperty('--spotlight-x', `${x}px`)
    el.style.setProperty('--spotlight-y', `${y}px`)
    el.style.setProperty('--spotlight-opacity', '1')
    if (options.color) {
      el.style.setProperty('--spotlight-color', options.color)
    }
  }

  function onPointerLeave() {
    const el = targetRef.value
    if (!el) return
    if (rafId !== null) {
      cancelAnimationFrame(rafId)
      rafId = null
      isMoving = false
    }
    el.style.setProperty('--spotlight-opacity', '0')
  }

  function bindEvents(el: HTMLElement) {
    el.classList.add('cgda-spotlight-card')
    el.addEventListener('pointermove', onPointerMove, { passive: true })
    el.addEventListener('pointerleave', onPointerLeave, { passive: true })
  }

  function unbindEvents(el: HTMLElement) {
    el.removeEventListener('pointermove', onPointerMove)
    el.removeEventListener('pointerleave', onPointerLeave)
    if (rafId !== null) {
      cancelAnimationFrame(rafId)
      rafId = null
      isMoving = false
    }
  }

  watch(
    targetRef,
    (newEl, oldEl) => {
      if (oldEl) unbindEvents(oldEl)
      if (newEl) bindEvents(newEl)
    },
    { immediate: true },
  )

  onBeforeUnmount(() => {
    if (targetRef.value) {
      unbindEvents(targetRef.value)
    }
  })
}
