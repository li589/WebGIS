<script setup lang="ts">
/**
 * 数据集页签（2026-10-20 用户第 4 轮）
 *
 * 位置：「图层」标题行之下、「已添加图层」列表之上。
 * 交互：选中态**只把文字变主色**——用户明确否掉了「下面一条短蓝线」的方案，
 *       所以这里不画任何下划线/指示条；整行只有底部一条极淡通栏细线。
 *
 * 语义：
 * - `research` 研发产品：现有全部产品（工作流反演产物、导入栅格等）。
 * - `public`   公共数据：暂未接入真实目录，父组件渲染空态占位
 *               （用户选择「先只做界面，等以后接真实数据」）。
 *
 * 2026-10-20（用户第 6 轮）：两个页签前各加一个图标——
 * 研发产品 = 显微镜（实验/反演），公共数据 = 地球仪（公开共享的地理数据），
 * 图标颜色继承文字，选中时随文字一起变亮。
 *
 * 2026-10-20（用户第 7 轮）：文案「科研数据」→「研发产品」（内部 value 仍为
 * `research`，只改显示文字，不动数据分流逻辑与接口）。
 *
 * 2026-10-21（用户第 10 轮）：新增第三个页签「收藏」，并改为**三等分均匀排开**
 * （原先靠固定 gap 左对齐，三个页签会挤在左边）。收藏与公共数据一样，
 * 当前只有界面占位，父组件渲染空态。
 */
import { Microscope, Globe, Star } from '../ui/icons'

type DatasetScope = 'research' | 'public' | 'favorite'

defineProps<{
  modelValue: DatasetScope
}>()

const emit = defineEmits<{
  'update:modelValue': [scope: DatasetScope]
}>()

const TABS: ReadonlyArray<{ value: DatasetScope; label: string; icon: typeof Microscope }> = [
  { value: 'research', label: '研发产品', icon: Microscope },
  { value: 'public', label: '公共数据', icon: Globe },
  { value: 'favorite', label: '收藏', icon: Star },
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
