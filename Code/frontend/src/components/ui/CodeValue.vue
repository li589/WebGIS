<script setup lang="ts">
/**
 * CodeValue — 超长配置值（路径/URL/密钥串）的统一展示：
 * 单行省略 → 点击展开全量换行 → 一键复制。
 * 用于部署配置中心状态条 / 三方对比元信息 / diff 表等密集展示位。
 */
import { computed, ref } from 'vue'
import { Check, Copy } from './icons'

const props = withDefaults(
  defineProps<{
    value: string
    /** 折叠态单行最大宽度 */
    maxWidth?: string
    /** 超过该长度才显示展开按钮 */
    truncatableThreshold?: number
    /** 空值占位 */
    placeholder?: string
  }>(),
  { maxWidth: '24rem', truncatableThreshold: 40, placeholder: '—' },
)

const expanded = ref(false)
const copied = ref(false)
const copyFailed = ref(false)

const truncatable = computed(
  () => !expanded.value && props.value.length > props.truncatableThreshold,
)

async function copyValue(): Promise<void> {
  const text = props.value
  if (!text) return
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text)
    } else {
      const ta = document.createElement('textarea')
      ta.value = text
      ta.style.position = 'fixed'
      ta.style.opacity = '0'
      document.body.appendChild(ta)
      ta.select()
      document.execCommand('copy')
      ta.remove()
    }
    copied.value = true
    setTimeout(() => (copied.value = false), 1200)
  } catch {
    copyFailed.value = true
    setTimeout(() => (copyFailed.value = false), 1500)
  }
}
</script>

<template>
  <span class="code-value" :class="{ 'code-value--open': expanded }">
    <span
      class="cv-text"
      :class="{ 'cv-text--clip': truncatable }"
      :style="truncatable ? { maxWidth } : undefined"
      :title="truncatable ? '点击展开完整内容' : value || placeholder"
      :role="truncatable ? 'button' : undefined"
      :tabindex="truncatable ? 0 : undefined"
      @click="truncatable && (expanded = true)"
      @keydown.enter.prevent="truncatable && (expanded = true)"
    >
      {{ value || placeholder }}
    </span>
    <button v-if="expanded" type="button" class="cv-act" title="收起" @click="expanded = false">
      收起
    </button>
    <button
      v-if="value"
      type="button"
      class="cv-act"
      :title="copyFailed ? '复制失败（浏览器限制）' : copied ? '已复制' : '复制'"
      @click="copyValue"
    >
      <Check v-if="copied" :size="12" aria-hidden="true" />
      <Copy v-else :size="12" aria-hidden="true" />
    </button>
  </span>
</template>

<style scoped>
.code-value {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  min-width: 0;
  max-width: 100%;
  vertical-align: middle;
}
.code-value--open {
  display: flex;
  flex-wrap: wrap;
}
.cv-text {
  font-family: var(--font-mono, ui-monospace, 'Cascadia Mono', Consolas, monospace);
  font-size: 0.72rem;
  color: var(--text-secondary, #a9bccb);
  min-width: 0;
}
.cv-text--clip {
  cursor: zoom-in;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.cv-text--clip:hover {
  color: var(--accent-strong, #9fe4ff);
}
.code-value--open .cv-text {
  white-space: normal;
  word-break: break-all;
  line-height: 1.45;
  flex: 1 1 auto;
}
.cv-act {
  display: inline-flex;
  align-items: center;
  border: 1px solid var(--border-subtle, #223140);
  background: transparent;
  color: var(--text-muted, #8fa3b3);
  border-radius: 0.22rem;
  padding: 0 0.26rem;
  font-size: 0.66rem;
  line-height: 1.35;
  cursor: pointer;
  flex: none;
}
.cv-act:hover {
  color: var(--accent-strong, #9fe4ff);
  border-color: var(--border-default, #2a3a48);
}
</style>
