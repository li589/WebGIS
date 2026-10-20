<script setup lang="ts">
/**
 * ToolbarMenu.vue — 顶栏下拉菜单通用容器
 *
 * 2026-10-20：顶栏导航栏改造时新增。把「触发按钮 + 定位 + 点击外部关闭」这套
 * 重复逻辑收在一处，地图工具 / 底图两个下拉共用；视觉规格全部来自
 * styles/toolbar-menu.css 的 .tm-* 类，与「数据」下拉保持一致。
 */
import { nextTick, onBeforeUnmount, ref, watch, type Component } from 'vue'
import { ChevronDown } from '../ui/icons'

const props = withDefaults(
  defineProps<{
    /** 触发按钮文字 */
    label: string
    /** 触发按钮图标 */
    icon: Component
    /** 悬停提示（不传用 label） */
    title?: string
    /** 按钮是否处于「有活动状态」的高亮（如地图工具选中了非默认工具） */
    active?: boolean
    /** 面板加宽（底图这类条目较长的菜单用） */
    wide?: boolean
    /** 面板可滚动（条目不固定数量时用） */
    scrollable?: boolean
  }>(),
  { title: undefined, active: false, wide: false, scrollable: false },
)

const menuOpen = ref(false)
const triggerRef = ref<HTMLButtonElement | null>(null)
const dropdownRef = ref<HTMLElement | null>(null)
const dropdownPos = ref({ top: 0, left: 0 })

async function openMenu() {
  const trigger = triggerRef.value
  if (!trigger) return
  const rect = trigger.getBoundingClientRect()
  dropdownPos.value = { top: rect.bottom + 4, left: rect.left }
  menuOpen.value = true
  // 先渲染再量，避免菜单右侧/底部出屏
  await nextTick()
  const el = dropdownRef.value
  if (!el) return
  const margin = 8
  const width = el.offsetWidth
  const height = el.offsetHeight
  let left = rect.left
  let top = rect.bottom + 4
  if (left + width > window.innerWidth - margin) {
    left = Math.max(margin, window.innerWidth - width - margin)
  }
  if (top + height > window.innerHeight - margin) {
    top = Math.max(margin, rect.top - height - 4)
  }
  dropdownPos.value = { top, left }
}

function closeMenu() {
  menuOpen.value = false
}

function toggleMenu() {
  if (menuOpen.value) closeMenu()
  else void openMenu()
}

function handleDocumentClick(e: MouseEvent) {
  if (!menuOpen.value) return
  const target = e.target as Node
  if (triggerRef.value?.contains(target)) return
  if (dropdownRef.value?.contains(target)) return
  closeMenu()
}

watch(menuOpen, (open) => {
  if (open) {
    document.addEventListener('click', handleDocumentClick, { capture: true })
  } else {
    document.removeEventListener('click', handleDocumentClick, { capture: true })
  }
})

onBeforeUnmount(() => {
  document.removeEventListener('click', handleDocumentClick, { capture: true })
})

defineExpose({ closeMenu })
</script>

<template>
  <div class="toolbar-menu">
    <button
      ref="triggerRef"
      class="tm-trigger"
      :class="{ 'is-active': props.active || menuOpen }"
      type="button"
      :title="title ?? label"
      :aria-expanded="menuOpen"
      @click="toggleMenu"
    >
      <component :is="icon" :size="14" class="tm-btn-icon" aria-hidden="true" />
      <span class="tm-btn-label">{{ label }}</span>
      <ChevronDown :size="14" class="tm-caret" aria-hidden="true" />
    </button>

    <Teleport to="body">
      <div
        v-if="menuOpen"
        ref="dropdownRef"
        class="tm-dropdown"
        :class="{ 'is-wide': wide, 'is-scrollable': scrollable }"
        :style="{ top: dropdownPos.top + 'px', left: dropdownPos.left + 'px' }"
        @click.stop
      >
        <slot :close="closeMenu" />
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
.toolbar-menu {
  position: relative;
  display: inline-flex;
  align-items: center;
}
</style>
