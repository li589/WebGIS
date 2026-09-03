<script setup lang="ts">
/**
 * 资源选择输入框（ACL 配置专用）：可搜索下拉选择已有资源 + 手动输入任意 ID。
 *
 * - 输入即过滤（匹配 id 或 label），↑/↓ 选择、Enter 确认、Esc 关闭；
 * - 选中的选项自动把 id 填入输入框（v-model 绑定 id，而非 label）；
 * - 输入了目录中不存在的 id 时提示「自定义 ID」（仍可保存），不强制收录。
 */
import { computed, ref, watch } from 'vue'

import type { ResourceOption } from '../../services/permission-resources'

const props = withDefaults(
  defineProps<{
    modelValue: string
    options: ResourceOption[]
    placeholder?: string
    disabled?: boolean
  }>(),
  { placeholder: '资源 ID（可输入或从下拉选择）', disabled: false },
)

const emit = defineEmits<{ 'update:modelValue': [value: string] }>()

const inputText = ref(props.modelValue)
const open = ref(false)
const activeIndex = ref(0)

watch(
  () => props.modelValue,
  (value) => {
    if (value !== inputText.value) inputText.value = value
  },
)

const filteredOptions = computed(() => {
  const q = inputText.value.trim().toLowerCase()
  if (!q) return props.options.slice(0, 50)
  return props.options
    .filter(
      (option) => option.id.toLowerCase().includes(q) || option.label.toLowerCase().includes(q),
    )
    .slice(0, 50)
})

const exactMatch = computed(() =>
  props.options.some((option) => option.id === inputText.value.trim()),
)

function onInput(event: Event) {
  inputText.value = (event.target as HTMLInputElement).value
  activeIndex.value = 0
  open.value = true
  emit('update:modelValue', inputText.value)
}

function select(option: ResourceOption) {
  inputText.value = option.id
  open.value = false
  emit('update:modelValue', option.id)
}

function onKeydown(event: KeyboardEvent) {
  if (!open.value || filteredOptions.value.length === 0) return
  if (event.key === 'ArrowDown') {
    event.preventDefault()
    activeIndex.value = (activeIndex.value + 1) % filteredOptions.value.length
  } else if (event.key === 'ArrowUp') {
    event.preventDefault()
    activeIndex.value =
      (activeIndex.value - 1 + filteredOptions.value.length) % filteredOptions.value.length
  } else if (event.key === 'Enter') {
    event.preventDefault()
    select(filteredOptions.value[activeIndex.value]!)
  } else if (event.key === 'Escape') {
    open.value = false
  }
}

function onOptionMousedown(option: ResourceOption, event: MouseEvent) {
  // mousedown 早于 input blur，避免点击选项时下拉先被收起
  event.preventDefault()
  select(option)
}
</script>

<template>
  <div class="rpi" :class="{ 'rpi--open': open && filteredOptions.length }">
    <input
      :value="inputText"
      :disabled="disabled"
      :placeholder="placeholder"
      type="text"
      class="rpi-input"
      autocomplete="off"
      @input="onInput"
      @focus="open = true"
      @blur="open = false"
      @keydown="onKeydown"
    />
    <span
      v-if="inputText.trim() && !exactMatch"
      class="rpi-custom-tag"
      title="目录中未收录，将按自定义 ID 保存"
    >
      自定义 ID
    </span>
    <ul v-if="open && filteredOptions.length" class="rpi-dropdown" @mousedown.prevent>
      <li
        v-for="(option, index) in filteredOptions"
        :key="option.id"
        :class="{ 'rpi-option--active': index === activeIndex }"
        class="rpi-option"
        @mousemove="activeIndex = index"
        @mousedown="onOptionMousedown(option, $event)"
      >
        <code class="rpi-option-id">{{ option.id }}</code>
        <span class="rpi-option-label">{{ option.label }}</span>
        <span v-if="option.hint" class="rpi-option-hint">{{ option.hint }}</span>
      </li>
    </ul>
  </div>
</template>

<style scoped>
.rpi {
  position: relative;
  flex: 1;
  min-width: 0;
}
.rpi-input {
  width: 100%;
  height: 2.1rem;
  padding: 0 0.6rem;
  padding-right: 4.2rem;
  border: 1px solid var(--border-default);
  border-radius: 6px;
  background: var(--surface-1);
  color: var(--text-primary);
  font-family: inherit;
  font-size: var(--font-size-caption);
}
.rpi-input:focus {
  outline: none;
  border-color: var(--accent);
  box-shadow: 0 0 0 3px rgba(90, 213, 255, 0.15);
}
.rpi-custom-tag {
  position: absolute;
  top: 50%;
  right: 0.4rem;
  transform: translateY(-50%);
  font-size: 0.62rem;
  padding: 0.05rem 0.35rem;
  border-radius: 999px;
  border: 1px solid var(--border-accent);
  color: var(--accent);
  background: var(--accent-surface);
  pointer-events: none;
}
.rpi-dropdown {
  position: absolute;
  z-index: 30;
  top: calc(100% + 0.25rem);
  left: 0;
  right: 0;
  max-height: 14rem;
  overflow: auto;
  margin: 0;
  padding: 0.25rem;
  list-style: none;
  border: 1px solid var(--border-accent);
  border-radius: 8px;
  background: var(--surface-2, var(--surface-1));
  box-shadow: 0 18px 40px rgba(0, 0, 0, 0.45);
}
.rpi-option {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.32rem 0.5rem;
  border-radius: 6px;
  cursor: pointer;
  font-size: var(--font-size-caption);
  color: var(--text-secondary);
}
.rpi-option--active {
  background: var(--accent-surface);
  color: var(--text-primary);
}
.rpi-option-id {
  font-family: var(--font-mono, ui-monospace, monospace);
  font-size: 0.74rem;
  color: var(--text-strong);
  flex-shrink: 0;
}
.rpi-option-label {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.rpi-option-hint {
  margin-left: auto;
  font-size: 0.66rem;
  color: var(--text-faint);
  flex-shrink: 0;
}
</style>
