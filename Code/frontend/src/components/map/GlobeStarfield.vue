<script setup lang="ts">
/**
 * GlobeStarfield — 3D globe 模式的深空星图背景层。
 *
 * - 程序化生成（globe-starfield.ts），不引入图片资源
 * - 主题感知：auto 模式下暗色主题=完整星图、浅色主题=淡化微尘
 * - mode：auto=跟随主题 / starfield=始终完整星图 / minimal=极简（无星图）
 * - active=false（2D 模式）时淡出，不拦截交互
 */
import { computed, ref, watch } from 'vue'
import { useThemeStore } from '../../stores/theme'
import { renderStarfieldCanvas, type StarfieldMode } from './globe-starfield'

const props = defineProps<{
  mode: 'auto' | 'starfield' | 'minimal'
  /** 是否处于 3D globe 模式（控制显隐） */
  active: boolean
}>()

const themeStore = useThemeStore()
const bgUrl = ref('')

/** 解析为渲染模式：auto→跟随主题；starfield→始终 full；minimal→无星图 */
const effectiveMode = computed<StarfieldMode>(() => {
  if (props.mode === 'minimal') return 'minimal'
  if (props.mode === 'starfield') return 'full'
  return themeStore.mode === 'dark' ? 'full' : 'soft'
})

watch(
  effectiveMode,
  (mode) => {
    if (mode === 'minimal') {
      bgUrl.value = ''
      return
    }
    try {
      const canvas = renderStarfieldCanvas({ mode })
      bgUrl.value = canvas.toDataURL('image/png')
    } catch {
      // canvas 不可用（极端环境）时退化为纯渐变背景
      bgUrl.value = ''
    }
  },
  { immediate: true },
)
</script>

<template>
  <div
    class="globe-starfield"
    :class="{ 'globe-starfield--visible': active && !!bgUrl }"
    :style="bgUrl ? { backgroundImage: `url(${bgUrl})` } : undefined"
    aria-hidden="true"
  ></div>
</template>

<style scoped>
.globe-starfield {
  position: absolute;
  inset: 0;
  z-index: 0;
  pointer-events: none;
  background-size: cover;
  background-position: center;
  background-repeat: no-repeat;
  opacity: 0;
  transition: opacity 0.6s var(--ease-standard);
}

.globe-starfield--visible {
  opacity: 1;
}
</style>
