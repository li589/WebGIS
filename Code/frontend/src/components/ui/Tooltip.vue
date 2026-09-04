<script setup lang="ts">
/**
 * Tooltip — 悬停提示（Teleport 到 body，始终顶置）
 *
 * - 配色：专用 `--tooltip-*` token（浅/深主题一致对比度）
 * - 层级：`--z-tooltip`（高于设置/工作流面板，避免被遮挡）
 * - 定位：fixed + 视口边界翻转；短文案优先，过长省略
 */
import { computed, nextTick, onUnmounted, ref, watch } from 'vue'

const props = withDefaults(
  defineProps<{
    text: string
    /** 位置偏好：top / bottom / left / right */
    position?: 'top' | 'bottom' | 'left' | 'right'
    /** 延迟显示毫秒数 */
    delayMs?: number
    /** 最大宽度（默认 14rem；wrap 时默认 16rem） */
    maxWidth?: string
    /** 允许换行（默认单行省略） */
    wrap?: boolean
    /** 触发器按块级撑满（卡片等） */
    block?: boolean
  }>(),
  {
    position: 'top',
    delayMs: 200,
    wrap: false,
    block: false,
  },
)

const showTooltip = ref(false)
const triggerRef = ref<HTMLElement | null>(null)
const boxRef = ref<HTMLElement | null>(null)
const coords = ref({ top: 0, left: 0, placement: props.position })

let showTimeoutId: number | null = null
let hideTimeoutId: number | null = null

const resolvedMaxWidth = computed(() => props.maxWidth ?? (props.wrap ? '16rem' : '14rem'))

const boxStyle = computed(() => ({
  top: `${coords.value.top}px`,
  left: `${coords.value.left}px`,
  maxWidth: resolvedMaxWidth.value,
}))

function clearTimeouts() {
  if (showTimeoutId != null) window.clearTimeout(showTimeoutId)
  if (hideTimeoutId != null) window.clearTimeout(hideTimeoutId)
  showTimeoutId = null
  hideTimeoutId = null
}

function clamp(n: number, min: number, max: number) {
  return Math.min(Math.max(n, min), max)
}

function updatePosition() {
  const trigger = triggerRef.value
  const box = boxRef.value
  if (!trigger || !box) return

  const gap = 8
  const pad = 8
  const rect = trigger.getBoundingClientRect()
  const bw = box.offsetWidth
  const bh = box.offsetHeight
  const vw = window.innerWidth
  const vh = window.innerHeight

  type Placement = 'top' | 'bottom' | 'left' | 'right'
  const order: Placement[] = [props.position, 'top', 'bottom', 'left', 'right'].filter(
    (v, i, a) => a.indexOf(v) === i,
  ) as Placement[]

  const fits = (p: Placement) => {
    if (p === 'top') return rect.top - gap - bh >= pad
    if (p === 'bottom') return rect.bottom + gap + bh <= vh - pad
    if (p === 'left') return rect.left - gap - bw >= pad
    return rect.right + gap + bw <= vw - pad
  }

  const placement = order.find(fits) ?? props.position

  let top: number
  let left: number
  if (placement === 'top') {
    top = rect.top - gap - bh
    left = rect.left + rect.width / 2 - bw / 2
  } else if (placement === 'bottom') {
    top = rect.bottom + gap
    left = rect.left + rect.width / 2 - bw / 2
  } else if (placement === 'left') {
    top = rect.top + rect.height / 2 - bh / 2
    left = rect.left - gap - bw
  } else {
    top = rect.top + rect.height / 2 - bh / 2
    left = rect.right + gap
  }

  coords.value = {
    placement,
    top: clamp(top, pad, Math.max(pad, vh - bh - pad)),
    left: clamp(left, pad, Math.max(pad, vw - bw - pad)),
  }
}

async function open() {
  showTooltip.value = true
  await nextTick()
  updatePosition()
  // 二次测量：字体/换行后尺寸可能变化
  requestAnimationFrame(() => updatePosition())
}

function onMouseEnter() {
  clearTimeouts()
  showTimeoutId = window.setTimeout(() => {
    void open()
  }, props.delayMs)
}

function onMouseLeave() {
  clearTimeouts()
  hideTimeoutId = window.setTimeout(() => {
    showTooltip.value = false
  }, 80)
}

function onFocus() {
  clearTimeouts()
  showTimeoutId = window.setTimeout(() => {
    void open()
  }, props.delayMs)
}

function onBlur() {
  clearTimeouts()
  showTooltip.value = false
}

function onViewportChange() {
  if (showTooltip.value) updatePosition()
}

watch(showTooltip, (visible) => {
  if (visible) {
    window.addEventListener('scroll', onViewportChange, true)
    window.addEventListener('resize', onViewportChange)
  } else {
    window.removeEventListener('scroll', onViewportChange, true)
    window.removeEventListener('resize', onViewportChange)
  }
})

onUnmounted(() => {
  clearTimeouts()
  window.removeEventListener('scroll', onViewportChange, true)
  window.removeEventListener('resize', onViewportChange)
})
</script>

<template>
  <span
    ref="triggerRef"
    class="tooltip-trigger"
    :class="{ 'tooltip-trigger--block': block }"
    @mouseenter="onMouseEnter"
    @mouseleave="onMouseLeave"
    @focusin="onFocus"
    @focusout="onBlur"
  >
    <slot />
  </span>
  <Teleport to="body">
    <transition name="tooltip-fade">
      <div
        v-if="showTooltip && text"
        ref="boxRef"
        class="tooltip-box"
        :class="[`tooltip-${coords.placement}`, { 'tooltip-wrap': wrap }]"
        :style="boxStyle"
        role="tooltip"
      >
        {{ text }}
      </div>
    </transition>
  </Teleport>
</template>

<style scoped>
.tooltip-trigger {
  display: inline-flex;
  max-width: 100%;
  vertical-align: middle;
  align-items: center;
}

.tooltip-trigger--block {
  display: block;
  width: 100%;
}

.tooltip-box {
  position: fixed;
  z-index: var(--z-tooltip);
  box-sizing: border-box;
  padding: 0.3rem 0.55rem;
  border-radius: var(--radius-sm);
  background: var(--tooltip-bg);
  border: 1px solid var(--tooltip-border);
  box-shadow: var(--tooltip-shadow);
  color: var(--tooltip-fg);
  font-family: var(--font-sans);
  font-size: var(--font-size-caption);
  font-weight: var(--font-weight-medium);
  line-height: 1.35;
  letter-spacing: 0.01em;
  text-align: center;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  pointer-events: none;
}

.tooltip-box.tooltip-wrap {
  white-space: normal;
  text-align: left;
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 3;
  line-clamp: 3;
  overflow: hidden;
  word-break: break-word;
}

/* 进场微位移（placement 在 open 后写入） */
.tooltip-fade-enter-active,
.tooltip-fade-leave-active {
  transition:
    opacity var(--motion-fast) var(--ease-soft),
    transform var(--motion-fast) var(--ease-soft);
}

.tooltip-fade-enter-from,
.tooltip-fade-leave-to {
  opacity: 0;
}

.tooltip-fade-enter-from.tooltip-top,
.tooltip-fade-leave-to.tooltip-top {
  transform: translateY(4px);
}

.tooltip-fade-enter-from.tooltip-bottom,
.tooltip-fade-leave-to.tooltip-bottom {
  transform: translateY(-4px);
}

.tooltip-fade-enter-from.tooltip-left,
.tooltip-fade-leave-to.tooltip-left {
  transform: translateX(4px);
}

.tooltip-fade-enter-from.tooltip-right,
.tooltip-fade-leave-to.tooltip-right {
  transform: translateX(-4px);
}

@media (prefers-reduced-motion: reduce) {
  .tooltip-fade-enter-active,
  .tooltip-fade-leave-active {
    transition: opacity var(--motion-fast);
  }

  .tooltip-fade-enter-from,
  .tooltip-fade-leave-to {
    transform: none;
  }
}
</style>
