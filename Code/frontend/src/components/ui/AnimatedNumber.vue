<script setup lang="ts">
/**
 * AnimatedNumber — 平滑过渡数字组件
 *
 * 专门用于百分比、计数器、数据量等动态数值的平滑滚动展示。
 * 具备 tabular-nums 防抖动排版与 reduce-motion 零延迟无障碍回退。
 */
import { computed } from 'vue'
import { useAnimatedNumber } from '../../composables/useAnimatedNumber'

const props = withDefaults(
  defineProps<{
    value: number
    duration?: number
    precision?: number
    prefix?: string
    suffix?: string
  }>(),
  {
    duration: 350,
    precision: 0,
    prefix: '',
    suffix: '',
  },
)

const { displayValue } = useAnimatedNumber(() => props.value, {
  duration: props.duration,
  precision: props.precision,
})

const formattedText = computed(() => {
  const numStr =
    props.precision > 0
      ? displayValue.value.toFixed(props.precision)
      : String(Math.round(displayValue.value))
  return `${props.prefix}${numStr}${props.suffix}`
})
</script>

<template>
  <span class="cgda-animated-number">{{ formattedText }}</span>
</template>

<style scoped>
.cgda-animated-number {
  font-variant-numeric: tabular-nums;
  display: inline-block;
}
</style>
