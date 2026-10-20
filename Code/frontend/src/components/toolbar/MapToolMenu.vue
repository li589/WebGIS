<script setup lang="ts">
/**
 * MapToolMenu.vue — 顶栏「地图工具」下拉
 *
 * 2026-10-20：原来顶栏平铺 4 个图标按钮（移动 / 点查 / 测量 / 绘制），
 * 挤压后整行被挤成两行。改为一个下拉，分组收敛，腾出一行宽度。
 * 交互与「数据」下拉一致（图标 + 标题 + 说明，选完自动收起）。
 */
import { computed } from 'vue'
import { Check, Crosshair, Move, Pen, Ruler, Trash2 } from '../ui/icons'
import ToolbarMenu from './ToolbarMenu.vue'
import { useUiStore } from '../../stores/ui'
import { useLogStore } from '../../stores/log'
import { useDrawSessionTransition } from '../../composables/useDrawSessionTransition'
import type { InteractionMode } from '../../stores/ui'

const uiStore = useUiStore()
const logStore = useLogStore()
const { requestInteractionMode } = useDrawSessionTransition()

/** 「浏览」与「量算」两组，视觉上用一条淡灰实线分开 */
const browseTools = [
  { mode: 'move' as InteractionMode, label: '移动', desc: '拖动平移地图', icon: Move },
  {
    mode: 'select' as InteractionMode,
    label: '点查',
    desc: '点击地图查询要素属性',
    icon: Crosshair,
  },
]

const measureTools = [
  {
    mode: 'measure' as InteractionMode,
    label: '测量',
    desc: '点击打点，双击完成量算',
    icon: Ruler,
  },
  { mode: 'draw' as InteractionMode, label: '绘制', desc: '点击加顶点，双击闭合成面', icon: Pen },
]

const hasMeasurePoints = computed(() => uiStore.measureState.points.length > 0)
const currentMode = computed(() => uiStore.interactionMode)

/** 当前是否处于非默认工具（用于触发按钮高亮） */
const isNonDefaultMode = computed(() => currentMode.value !== 'move')

const modeLabel = computed(
  () =>
    [...browseTools, ...measureTools].find((t) => t.mode === currentMode.value)?.label ?? '移动',
)

async function pickMode(mode: InteractionMode, close: () => void) {
  close()
  const ok = await requestInteractionMode(mode)
  if (!ok) return
  const label =
    mode === 'move' ? '移动' : mode === 'select' ? '选择' : mode === 'measure' ? '测量' : '绘制'
  logStore.logOperation('mode-switch', `切换到${label}模式`)
}

function clearMeasure(close: () => void) {
  close()
  uiStore.clearMeasure()
  logStore.logOperation('measure-clear', '清除测量路径')
}
</script>

<template>
  <ToolbarMenu
    label="地图工具"
    :icon="Crosshair"
    :title="`地图工具 · 当前：${modeLabel}`"
    :active="isNonDefaultMode"
  >
    <template #default="{ close }">
      <button
        v-for="tool in browseTools"
        :key="tool.mode"
        class="tm-item"
        :class="{ 'is-current': currentMode === tool.mode }"
        type="button"
        @click="pickMode(tool.mode, close)"
      >
        <component :is="tool.icon" :size="14" class="tm-item-icon" aria-hidden="true" />
        <span class="tm-item-body">
          <span class="tm-item-title">{{ tool.label }}</span>
          <span class="tm-item-desc">{{ tool.desc }}</span>
        </span>
        <Check
          v-if="currentMode === tool.mode"
          :size="14"
          class="tm-item-check"
          aria-hidden="true"
        />
      </button>

      <div class="tm-sep" role="separator" />

      <button
        v-for="tool in measureTools"
        :key="tool.mode"
        class="tm-item"
        :class="{ 'is-current': currentMode === tool.mode }"
        type="button"
        @click="pickMode(tool.mode, close)"
      >
        <component :is="tool.icon" :size="14" class="tm-item-icon" aria-hidden="true" />
        <span class="tm-item-body">
          <span class="tm-item-title">{{ tool.label }}</span>
          <span class="tm-item-desc">{{ tool.desc }}</span>
        </span>
        <Check
          v-if="currentMode === tool.mode"
          :size="14"
          class="tm-item-check"
          aria-hidden="true"
        />
      </button>

      <button
        class="tm-item"
        :class="{ 'is-disabled': !hasMeasurePoints }"
        type="button"
        :disabled="!hasMeasurePoints"
        @click="clearMeasure(close)"
      >
        <Trash2 :size="14" class="tm-item-icon" aria-hidden="true" />
        <span class="tm-item-body">
          <span class="tm-item-title">清除测量</span>
          <span class="tm-item-desc">
            {{ hasMeasurePoints ? '清空当前测量路径' : '暂无测量点，先在图上打点' }}
          </span>
        </span>
      </button>

      <p class="tm-hint">提示：测量与绘制点完请双击结束；用完切回「移动」即可继续浏览地图</p>
    </template>
  </ToolbarMenu>
</template>
