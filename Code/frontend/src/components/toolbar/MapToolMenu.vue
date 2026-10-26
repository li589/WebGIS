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

/**
 * 地图是否可用（由 DashboardView 直接透传 MapCanvas 的真源，不另造状态）。
 * 返回 undefined = 未知（如 3D 实验模式没有 MapCanvas），此时不拦用户。
 */
const props = defineProps<{
  getMapReady?: () => boolean | undefined
  getMapError?: () => string | null
}>()

function mapBlocked(): boolean {
  return props.getMapReady?.() === false
}

function mapBlockedHint(): string {
  const err = String(props.getMapError?.() ?? '').trim()
  return err ? `地图未就绪：${err}` : '地图尚未初始化完成，暂不可用'
}

/** 「浏览」与「量算」两组，视觉上用一条淡灰实线分开 */
const browseTools = [
  {
    mode: 'move' as InteractionMode,
    label: '移动',
    desc: '拖动平移地图',
    icon: Move,
    needsMap: true,
  },
  {
    mode: 'select' as InteractionMode,
    label: '点查',
    desc: '点击地图查询要素属性',
    icon: Crosshair,
    needsMap: true,
  },
]

const measureTools = [
  {
    mode: 'measure' as InteractionMode,
    label: '测量',
    desc: '点击打点，双击完成量算',
    icon: Ruler,
    needsMap: true,
  },
  {
    mode: 'draw' as InteractionMode,
    label: '绘制',
    desc: '点击加顶点，双击闭合成面',
    icon: Pen,
    needsMap: true,
  },
]

/** 依赖地图的工具在地图未就绪时置灰（报告优先4：不让用户进入无反馈的点查状态） */
function toolDisabled(tool: { needsMap?: boolean }): boolean {
  return Boolean(tool.needsMap) && mapBlocked()
}

function toolDesc(tool: { desc: string; needsMap?: boolean }): string {
  return toolDisabled(tool) ? mapBlockedHint() : tool.desc
}

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
  // 兜底：即使按钮状态没刷新，点到依赖地图的工具也要明确拒绝并留痕
  if (mode !== 'move' && mapBlocked()) {
    logStore.logOperation('map-tool-blocked', `${mode} 不可用：${mapBlockedHint()}`)
    return
  }
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
        :class="{ 'is-current': currentMode === tool.mode, 'is-disabled': toolDisabled(tool) }"
        type="button"
        :disabled="toolDisabled(tool)"
        :title="toolDisabled(tool) ? toolDesc(tool) : undefined"
        @click="pickMode(tool.mode, close)"
      >
        <component :is="tool.icon" :size="14" class="tm-item-icon" aria-hidden="true" />
        <span class="tm-item-body">
          <span class="tm-item-title">{{ tool.label }}</span>
          <span class="tm-item-desc">{{ toolDesc(tool) }}</span>
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
        :class="{ 'is-current': currentMode === tool.mode, 'is-disabled': toolDisabled(tool) }"
        type="button"
        :disabled="toolDisabled(tool)"
        :title="toolDisabled(tool) ? toolDesc(tool) : undefined"
        @click="pickMode(tool.mode, close)"
      >
        <component :is="tool.icon" :size="14" class="tm-item-icon" aria-hidden="true" />
        <span class="tm-item-body">
          <span class="tm-item-title">{{ tool.label }}</span>
          <span class="tm-item-desc">{{ toolDesc(tool) }}</span>
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

      <p v-if="mapBlocked()" class="tm-hint">
        {{ mapBlockedHint() }}。点查 / 测量 / 绘制暂不可用；坐标查询仍可在助手对话框里用。
      </p>
      <p v-else class="tm-hint">提示：测量与绘制点完请双击结束；用完切回「移动」即可继续浏览地图</p>
    </template>
  </ToolbarMenu>
</template>
