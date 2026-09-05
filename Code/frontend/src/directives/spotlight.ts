/**
 * v-spotlight — 卡片光标聚光灯微反馈指令
 *
 * 用法：
 * <div v-spotlight class="my-card">...</div>
 * 或自定义微光颜色：
 * <div v-spotlight="{ color: 'rgba(56, 189, 248, 0.12)' }" class="my-card">...</div>
 */
import type { Directive } from 'vue'
import { isReducedMotionActive } from '../services/motion-preference'

export interface SpotlightBindingOptions {
  color?: string
  disabled?: boolean
}

const cleanupMap = new WeakMap<HTMLElement, () => void>()

export const vSpotlight: Directive<HTMLElement, SpotlightBindingOptions | undefined> = {
  mounted(el, binding) {
    el.classList.add('cgda-spotlight-card')

    let isMoving = false
    let pendingEvent: PointerEvent | null = null
    let rafId: number | null = null

    const onPointerMove = (e: PointerEvent) => {
      if (binding.value?.disabled || isReducedMotionActive()) return
      if (e.pointerType === 'touch') return

      pendingEvent = e
      if (!isMoving) {
        isMoving = true
        rafId = requestAnimationFrame(() => {
          isMoving = false
          if (!pendingEvent) return
          const rect = el.getBoundingClientRect()
          const x = pendingEvent.clientX - rect.left
          const y = pendingEvent.clientY - rect.top
          el.style.setProperty('--spotlight-x', `${x}px`)
          el.style.setProperty('--spotlight-y', `${y}px`)
          el.style.setProperty('--spotlight-opacity', '1')
          if (binding.value?.color) {
            el.style.setProperty('--spotlight-color', binding.value.color)
          }
        })
      }
    }

    const onPointerLeave = () => {
      if (rafId !== null) {
        cancelAnimationFrame(rafId)
        rafId = null
        isMoving = false
      }
      el.style.setProperty('--spotlight-opacity', '0')
    }

    el.addEventListener('pointermove', onPointerMove, { passive: true })
    el.addEventListener('pointerleave', onPointerLeave, { passive: true })

    cleanupMap.set(el, () => {
      el.removeEventListener('pointermove', onPointerMove)
      el.removeEventListener('pointerleave', onPointerLeave)
      if (rafId !== null) cancelAnimationFrame(rafId)
    })
  },
  updated(el, binding) {
    if (binding.value?.color) {
      el.style.setProperty('--spotlight-color', binding.value.color)
    }
  },
  unmounted(el) {
    const cleanup = cleanupMap.get(el)
    if (cleanup) {
      cleanup()
      cleanupMap.delete(el)
    }
  },
}
