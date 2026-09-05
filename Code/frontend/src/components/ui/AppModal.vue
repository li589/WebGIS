<script setup lang="ts">
/**
 * AppModal — 统一对话框壳（Teleport + Transition + 遮罩）
 *
 * 用法：
 *   <AppModal :open="open" aria-label="标题" @close="open = false">
 *     <header>...</header>
 *     <div class="body">...</div>
 *   </AppModal>
 *
 * 子内容落在 `.cgda-modal-panel` 内；动效名 `cgda-modal`（见 styles/motion.css）。
 * 开启「减少动效」时 Transition 仍挂载，但时长被 token 压到 0ms。
 */
import { computed, onMounted, onUnmounted, watch } from 'vue'

const props = withDefaults(
  defineProps<{
    open: boolean
    /** dialog 可访问名称 */
    ariaLabel?: string
    /** 点击遮罩是否关闭（默认 true） */
    closeOnBackdrop?: boolean
    /** Escape 关闭（默认 true） */
    closeOnEscape?: boolean
    /** 面板最大宽度（CSS 值） */
    maxWidth?: string
    /** 额外 mask class */
    maskClass?: string
    /** 额外 panel class */
    panelClass?: string
    zIndex?: number | string
  }>(),
  {
    ariaLabel: '对话框',
    closeOnBackdrop: true,
    closeOnEscape: true,
    maxWidth: 'min(640px, 92vw)',
    maskClass: '',
    panelClass: '',
    zIndex: 'var(--z-modal)',
  },
)

const emit = defineEmits<{
  close: []
}>()

const maskStyle = computed(() => ({
  zIndex: props.zIndex,
}))

const panelStyle = computed(() => ({
  maxWidth: props.maxWidth,
}))

function onBackdropClick() {
  if (props.closeOnBackdrop) emit('close')
}

function onKeydown(e: KeyboardEvent) {
  if (!props.open || !props.closeOnEscape) return
  if (e.key === 'Escape') {
    e.stopPropagation()
    emit('close')
  }
}

onMounted(() => {
  window.addEventListener('keydown', onKeydown)
})

onUnmounted(() => {
  window.removeEventListener('keydown', onKeydown)
})

watch(
  () => props.open,
  (open) => {
    if (typeof document === 'undefined') return
    document.documentElement.classList.toggle('cgda-modal-open', open)
  },
)
</script>

<template>
  <Teleport to="body">
    <Transition name="cgda-modal">
      <div
        v-if="open"
        class="cgda-modal-mask"
        :class="maskClass"
        :style="maskStyle"
        role="presentation"
        @click.self="onBackdropClick"
      >
        <div
          class="cgda-modal-panel"
          :class="panelClass"
          :style="panelStyle"
          role="dialog"
          aria-modal="true"
          :aria-label="ariaLabel"
        >
          <slot />
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.cgda-modal-mask {
  position: fixed;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 1rem;
  background: color-mix(in srgb, var(--surface-base) 65%, transparent);
}

.cgda-modal-panel {
  width: 100%;
  max-height: min(86vh, 900px);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  border-radius: var(--radius-xl);
  border: 1px solid var(--border-strong);
  background: var(--surface-2);
  color: var(--text-primary);
  box-shadow: var(--elevation-modal);
}
</style>
