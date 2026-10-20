<script setup lang="ts">
/**
 * 数据集页签（2026-10-20 用户第 4 轮）
 *
 * 位置：「图层」标题行之下、「已添加图层」列表之上。
 * 交互：选中态**只把文字变主色**——用户明确否掉了「下面一条短蓝线」的方案，
 *       所以这里不画任何下划线/指示条；整行只有底部一条极淡通栏细线。
 *
 * 语义：
 * - `research` 科研数据：现有全部产品（工作流反演产物、导入栅格等）。
 * - `public`   公共数据：暂未接入真实目录，父组件渲染空态占位
 *               （用户选择「先只做界面，等以后接真实数据」）。
 *
 * 2026-10-20（用户第 6 轮）：两个页签前各加一个图标——
 * 科研数据 = 显微镜（实验/反演），公共数据 = 地球仪（公开共享的地理数据），
 * 图标颜色继承文字，选中时随文字一起变亮。
 */
import { Microscope, Globe } from '../ui/icons'

type DatasetScope = 'research' | 'public'

defineProps<{
  modelValue: DatasetScope
}>()

const emit = defineEmits<{
  'update:modelValue': [scope: DatasetScope]
}>()

const TABS: ReadonlyArray<{ value: DatasetScope; label: string; icon: typeof Microscope }> = [
  { value: 'research', label: '科研数据', icon: Microscope },
  { value: 'public', label: '公共数据', icon: Globe },
]
</script>

<template>
  <div class="dataset-tabs" role="tablist" aria-label="数据集范围">
    <button
      v-for="tab in TABS"
      :key="tab.value"
      class="dataset-tab"
      :class="{ active: modelValue === tab.value }"
      type="button"
      role="tab"
      :aria-selected="modelValue === tab.value"
      @click="emit('update:modelValue', tab.value)"
    >
      <component :is="tab.icon" class="dataset-tab-icon" aria-hidden="true" />
      <span class="dataset-tab-label">{{ tab.label }}</span>
    </button>
  </div>
</template>

<style scoped src="./LayerSidebar.styles.css"></style>
