<script setup lang="ts">
/**
 * 流编辑器参数组合框：可输入筛选 + 下拉选择。
 * 菜单 Teleport 到 body，fixed 锚定输入框，点击外部 / Esc 关闭。
 */
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'

const props = withDefaults(
  defineProps<{
    modelValue: string
    options: string[]
    disabled?: boolean
    /** false 时只能选列表项；输入仅用于筛选 */
    allowCustom?: boolean
    placeholder?: string
    error?: boolean
  }>(),
  {
    disabled: false,
    allowCustom: true,
    placeholder: '',
    error: false,
  },
)

const emit = defineEmits<{
  'update:modelValue': [value: string]
}>()

const open = ref(false)
const rootRef = ref<HTMLElement | null>(null)
const menuRef = ref<HTMLElement | null>(null)
const inputRef = ref<HTMLInputElement | null>(null)
const filterText = ref('')
const menuStyle = ref<Record<string, string>>({})
const activeIndex = ref(-1)

const filtered = computed(() => {
  const q = filterText.value.trim().toLowerCase()
  if (!q) return props.options
  return props.options.filter((o) => o.toLowerCase().includes(q))
})

const showCustomHint = computed(() => {
  if (!props.allowCustom || !open.value) return false
  const q = filterText.value.trim()
  if (!q) return false
  return !props.options.some((o) => o.toLowerCase() === q.toLowerCase())
})

function updateMenuPosition() {
  const el = rootRef.value
  if (!el) return
  const r = el.getBoundingClientRect()
  const maxH = 168
  const estimated = Math.min(
    maxH,
    Math.max(32, filtered.value.length * 22 + (showCustomHint.value ? 22 : 0) + 6),
  )
  const spaceBelow = window.innerHeight - r.bottom - 8
  const openUp = spaceBelow < estimated && r.top > spaceBelow
  const left = Math.max(8, Math.min(r.left, window.innerWidth - Math.max(r.width, 120) - 8))
  const width = Math.max(r.width, 120)

  menuStyle.value = openUp
    ? {
        position: 'fixed',
        left: `${left}px`,
        width: `${width}px`,
        bottom: `${window.innerHeight - r.top + 2}px`,
        top: 'auto',
        maxHeight: `${Math.min(maxH, Math.max(48, r.top - 8))}px`,
        zIndex: '12000',
      }
    : {
        position: 'fixed',
        left: `${left}px`,
        width: `${width}px`,
        top: `${r.bottom + 2}px`,
        bottom: 'auto',
        maxHeight: `${Math.min(maxH, Math.max(48, spaceBelow))}px`,
        zIndex: '12000',
      }
}

function openMenu() {
  if (props.disabled) return
  filterText.value = props.modelValue
  activeIndex.value = -1
  open.value = true
  void nextTick(() => {
    updateMenuPosition()
    inputRef.value?.focus()
  })
}

function closeMenu() {
  open.value = false
  filterText.value = ''
  activeIndex.value = -1
}

function commit(value: string) {
  emit('update:modelValue', value)
  closeMenu()
}

function onInput(e: Event) {
  const v = (e.target as HTMLInputElement).value
  filterText.value = v
  if (props.allowCustom) {
    emit('update:modelValue', v)
  }
  if (!open.value) openMenu()
  else void nextTick(updateMenuPosition)
  activeIndex.value = filtered.value.length ? 0 : -1
}

function onFocus() {
  if (!props.disabled) openMenu()
}

function pick(opt: string) {
  commit(opt)
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape') {
    e.stopPropagation()
    closeMenu()
    return
  }
  if (e.key === 'ArrowDown') {
    e.preventDefault()
    if (!open.value) openMenu()
    else if (filtered.value.length) {
      activeIndex.value = (activeIndex.value + 1) % filtered.value.length
    }
    return
  }
  if (e.key === 'ArrowUp') {
    e.preventDefault()
    if (filtered.value.length) {
      activeIndex.value = activeIndex.value <= 0 ? filtered.value.length - 1 : activeIndex.value - 1
    }
    return
  }
  if (e.key === 'Enter') {
    e.preventDefault()
    if (open.value && activeIndex.value >= 0 && filtered.value[activeIndex.value]) {
      pick(filtered.value[activeIndex.value])
    } else if (props.allowCustom) {
      commit(filterText.value)
    } else if (filtered.value[0]) {
      pick(filtered.value[0])
    } else {
      closeMenu()
    }
  }
}

function onDocPointerDown(e: PointerEvent) {
  if (!open.value) return
  const t = e.target as Node
  if (rootRef.value?.contains(t) || menuRef.value?.contains(t)) return
  // 不允许自定义时，关闭前若当前值不在列表则回退到最近匹配/首项
  if (!props.allowCustom && props.modelValue && !props.options.includes(props.modelValue)) {
    const q = props.modelValue.toLowerCase()
    const hit = props.options.find((o) => o.toLowerCase().includes(q)) ?? props.options[0]
    if (hit) emit('update:modelValue', hit)
  }
  closeMenu()
}

function bindOutside(on: boolean) {
  if (on) {
    document.addEventListener('pointerdown', onDocPointerDown, true)
    window.addEventListener('resize', updateMenuPosition)
    window.addEventListener('scroll', updateMenuPosition, true)
  } else {
    document.removeEventListener('pointerdown', onDocPointerDown, true)
    window.removeEventListener('resize', updateMenuPosition)
    window.removeEventListener('scroll', updateMenuPosition, true)
  }
}

watch(open, (v) => bindOutside(v))
watch(filtered, () => {
  if (open.value) void nextTick(updateMenuPosition)
})

onBeforeUnmount(() => bindOutside(false))
</script>

<template>
  <div ref="rootRef" class="param-combobox" :class="{ open, disabled, error }">
    <input
      ref="inputRef"
      class="combo-input"
      type="text"
      :value="open ? filterText : modelValue"
      :disabled="disabled"
      :placeholder="placeholder || (allowCustom ? '输入或选择…' : '选择…')"
      :readonly="disabled"
      autocomplete="off"
      spellcheck="false"
      @focus="onFocus"
      @input="onInput"
      @keydown="onKeydown"
    />
    <button
      type="button"
      class="combo-toggle"
      tabindex="-1"
      :disabled="disabled"
      :aria-expanded="open"
      aria-label="打开选项"
      @click.stop="open ? closeMenu() : openMenu()"
    >
      <span class="chevron" :class="{ up: open }">▾</span>
    </button>

    <Teleport to="body">
      <ul
        v-if="open"
        ref="menuRef"
        class="param-combo-menu"
        role="listbox"
        :style="menuStyle"
        @mousedown.prevent
      >
        <li
          v-for="(opt, idx) in filtered"
          :key="opt"
          class="param-combo-option"
          :class="{ active: idx === activeIndex, selected: opt === modelValue }"
          role="option"
          :aria-selected="opt === modelValue"
          @mouseenter="activeIndex = idx"
          @click="pick(opt)"
        >
          {{ opt }}
        </li>
        <li v-if="!filtered.length && !showCustomHint" class="param-combo-empty">无匹配选项</li>
        <li
          v-if="showCustomHint"
          class="param-combo-option custom"
          role="option"
          @click="commit(filterText.trim())"
        >
          使用自定义「{{ filterText.trim() }}」
        </li>
      </ul>
    </Teleport>
  </div>
</template>

<style scoped>
.param-combobox {
  display: flex;
  align-items: stretch;
  width: 100%;
  border: 1px solid rgba(136, 192, 255, 0.22);
  border-radius: 0.32rem;
  background: rgba(8, 17, 31, 0.55);
  overflow: hidden;
}

.param-combobox.open {
  border-color: rgba(90, 213, 255, 0.55);
}

.param-combobox.error {
  border-color: rgba(255, 120, 120, 0.55);
}

.param-combobox.disabled {
  opacity: 0.55;
  pointer-events: none;
}

.combo-input {
  flex: 1;
  min-width: 0;
  border: none;
  background: transparent;
  color: #e8f3fc;
  font: inherit;
  font-size: 0.6rem;
  padding: 0.28rem 0.4rem;
  outline: none;
}

.combo-toggle {
  flex: 0 0 1.35rem;
  border: none;
  border-left: 1px solid rgba(136, 192, 255, 0.15);
  background: rgba(10, 132, 255, 0.08);
  color: #8aa8bf;
  cursor: pointer;
  font-size: 0.55rem;
  padding: 0;
}

.combo-toggle:hover {
  background: rgba(10, 132, 255, 0.18);
  color: #5ad5ff;
}

.chevron {
  display: inline-block;
  transition: transform 0.12s ease;
}

.chevron.up {
  transform: rotate(180deg);
}
</style>

<style>
/* Teleport 菜单不在 scoped 内 */
.param-combo-menu {
  margin: 0;
  padding: 0.2rem 0;
  list-style: none;
  overflow-y: auto;
  border: 1px solid rgba(136, 192, 255, 0.28);
  border-radius: 0.36rem;
  background: rgba(10, 18, 32, 0.97);
  box-shadow: 0 6px 18px rgba(0, 0, 0, 0.45);
  backdrop-filter: blur(6px);
}

.param-combo-option {
  padding: 0.22rem 0.5rem;
  font-size: 0.58rem;
  line-height: 1.35;
  color: #d5e6f5;
  cursor: pointer;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.param-combo-option:hover,
.param-combo-option.active {
  background: rgba(10, 132, 255, 0.22);
  color: #fff;
}

.param-combo-option.selected {
  color: #9ff8cf;
}

.param-combo-option.custom {
  border-top: 1px solid rgba(136, 192, 255, 0.12);
  color: #5ad5ff;
  font-style: italic;
}

.param-combo-empty {
  padding: 0.35rem 0.5rem;
  font-size: 0.55rem;
  color: #6e8ba0;
}
</style>
