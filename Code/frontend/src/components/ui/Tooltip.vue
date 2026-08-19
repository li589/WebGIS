<script setup lang="ts">
/**
 * Tooltip — 悬停提示框（设计系统 §3.1）
 *
 * 规格：12px，surface-3 + elevation-2，延迟 200ms 显示
 * 位置：自动选择上/下/左/右，避免窗口溢出
 * 触发：鼠标进入/离开，支持键盘焦点
 */
import { ref, onUnmounted } from 'vue'

const props = withDefaults(
  defineProps<{
    text: string
    /** 位置优先级：top, bottom, left, right */
    position?: 'top' | 'bottom' | 'left' | 'right'
    /** 延迟显示毫秒数 */
    delayMs?: number
    /** 最大宽度 */
    maxWidth?: string
  }>(),
  {
    position: 'top',
    delayMs: 200,
    maxWidth: '240px',
  },
)

const showTooltip = ref(false)
let showTimeoutId: number | null = null
let hideTimeoutId: number | null = null

function clearTimeouts() {
  if (showTimeoutId) window.clearTimeout(showTimeoutId)
  if (hideTimeoutId) window.clearTimeout(hideTimeoutId)
}

function onMouseEnter() {
  clearTimeouts()
  showTimeoutId = window.setTimeout(() => {
    showTooltip.value = true
  }, props.delayMs)
}

function onMouseLeave() {
  clearTimeouts()
  hideTimeoutId = window.setTimeout(() => {
    showTooltip.value = false
  }, 100)
}

function onFocus() {
  clearTimeouts()
  showTimeoutId = window.setTimeout(() => {
    showTooltip.value = true
  }, props.delayMs)
}

function onBlur() {
  clearTimeouts()
  showTooltip.value = false
}

onUnmounted(() => {
  clearTimeouts()
})
</script>

<template>
  <div class="tooltip-wrapper">
    <div
      class="tooltip-trigger"
      @mouseenter="onMouseEnter"
      @mouseleave="onMouseLeave"
      @focus="onFocus"
      @blur="onBlur"
    >
      <slot />
    </div>
    <transition name="tooltip-fade">
      <div
        v-if="showTooltip && text"
        class="tooltip-box"
        :class="[`tooltip-${position}`]"
        :style="{ maxWidth }"
        role="tooltip"
      >
        {{ text }}
      </div>
    </transition>
  </div>
</template>

<style scoped>
.tooltip-wrapper {
  display: inline-block;
  position: relative;
}

.tooltip-trigger {
  display: contents;
}

.tooltip-box {
  position: absolute;
  z-index: var(--z-popover);
  padding: 0.35rem 0.6rem;
  border-radius: var(--radius-md);
  background: var(--surface-3);
  border: 1px solid var(--border-default);
  box-shadow: var(--elevation-2);
  font-size: var(--font-size-caption);
  font-weight: var(--font-weight-regular);
  color: var(--text-primary);
  line-height: 1.4;
  text-align: center;
  white-space: nowrap;
  word-break: break-word;
  pointer-events: none;
  backdrop-filter: blur(var(--glass-blur));
  -webkit-backdrop-filter: blur(var(--glass-blur));
}

/* 位置变体 */
.tooltip-top {
  bottom: calc(100% + 0.5rem);
  left: 50%;
  transform: translateX(-50%) translateY(0);
}

.tooltip-bottom {
  top: calc(100% + 0.5rem);
  left: 50%;
  transform: translateX(-50%) translateY(0);
}

.tooltip-left {
  right: calc(100% + 0.5rem);
  top: 50%;
  transform: translateX(0) translateY(-50%);
}

.tooltip-right {
  left: calc(100% + 0.5rem);
  top: 50%;
  transform: translateX(0) translateY(-50%);
}

/* 过渡动画 — 根据位置调整方向 */
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
  transform: translateX(-50%) translateY(4px);
}

.tooltip-fade-enter-from.tooltip-bottom,
.tooltip-fade-leave-to.tooltip-bottom {
  transform: translateX(-50%) translateY(-4px);
}

.tooltip-fade-enter-from.tooltip-left,
.tooltip-fade-leave-to.tooltip-left {
  transform: translateX(4px) translateY(-50%);
}

.tooltip-fade-enter-from.tooltip-right,
.tooltip-fade-leave-to.tooltip-right {
  transform: translateX(-4px) translateY(-50%);
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
