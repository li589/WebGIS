<script setup lang="ts">
/**
 * PanelDock — 统一浮层面板壳（设计系统 §3.1）
 *
 * 合并原 ControlPanel + BasePanel + CompositePanel 的全部能力：
 * 拖拽、缩放、折叠、隐藏/恢复（胶囊）、复位、localStorage 持久化。
 * 所有颜色/间距/字号引用 tokens.css，禁止内联 hex。
 *
 * 用法（兼容原 ControlPanel API）：
 *   <PanelDock
 *     panel-label="图层"
 *     panel-key="layers"
 *     handle-position="bottom-right"
 *     :default-width="320"
 *     :min-width="240"
 *   >
 *     ...内容...
 *   </PanelDock>
 */

import { computed, ref, onMounted, onUnmounted } from 'vue'
import { usePanelDragResize } from './usePanelDragResize'

const props = withDefaults(
  defineProps<{
    /** 面板标题 */
    panelLabel: string
    /** 面板唯一标识（用于 localStorage 持久化） */
    panelKey?: string
    /** 是否可拖拽 */
    draggable?: boolean
    /** 是否可折叠 */
    collapsible?: boolean
    /** 默认折叠状态 */
    defaultCollapsed?: boolean
    /** 最大水平偏移（px） */
    maxOffsetX?: number
    /** 最大垂直偏移（px） */
    maxOffsetY?: number
    /** 默认宽度（px，0 = 自适应） */
    defaultWidth?: number
    /** 默认高度（px，0 = 自适应） */
    defaultHeight?: number
    /** 最小宽度（px） */
    minWidth?: number
    /** 最小高度（px） */
    minHeight?: number
    /** 最大宽度（px） */
    maxWidth?: number
    /** 最大高度（px） */
    maxHeight?: number
    /** 是否可缩放 */
    resizable?: boolean
    /** 缩放手柄位置 */
    handlePosition?: 'bottom-right' | 'bottom-left' | 'top-right' | 'top-left'
    /** 是否显示缩放手柄 */
    showResizeHandle?: boolean
    /** 内容区溢出策略 */
    bodyOverflow?: 'auto' | 'hidden'
    /** 布局位置提示（影响圆角裁剪） */
    position?: 'left' | 'right' | 'bottom' | 'float'
  }>(),
  {
    draggable: true,
    collapsible: true,
    defaultCollapsed: false,
    maxOffsetX: 120,
    maxOffsetY: 100,
    defaultWidth: 0,
    defaultHeight: 0,
    minWidth: 200,
    minHeight: 80,
    maxWidth: 600,
    maxHeight: 800,
    resizable: true,
    handlePosition: 'bottom-right',
    showResizeHandle: true,
    bodyOverflow: 'auto',
    position: 'float',
  },
)

const emit = defineEmits<{
  'update:collapsed': [value: boolean]
}>()

const {
  visible,
  collapsed,
  dragging,
  resizeEnabled,
  frameStyle,
  panelSizeStyle,
  anchorClass,
  startDragging,
  startPillDragging,
  startResizing,
  toggleCollapsed,
  hidePanel,
  showPanel,
  resetPanel,
} = usePanelDragResize({
  panelKey: props.panelKey,
  draggable: props.draggable,
  collapsible: props.collapsible,
  defaultCollapsed: props.defaultCollapsed,
  maxOffsetX: props.maxOffsetX,
  maxOffsetY: props.maxOffsetY,
  defaultWidth: props.defaultWidth,
  defaultHeight: props.defaultHeight,
  minWidth: props.minWidth,
  minHeight: props.minHeight,
  maxWidth: props.maxWidth,
  maxHeight: props.maxHeight,
  resizable: props.resizable,
  handlePosition: props.handlePosition,
  showResizeHandle: props.showResizeHandle,
})

const _viewportWidth = ref(typeof window !== 'undefined' ? window.innerWidth : 1280)
const isMobile = computed(() => _viewportWidth.value < 820)

function _onResize() {
  _viewportWidth.value = window.innerWidth
}
onMounted(() => window.addEventListener('resize', _onResize, { passive: true }))
onUnmounted(() => window.removeEventListener('resize', _onResize))

/** Mobile: suppress inline panel size styles so CSS media-query rules take effect */
const effectivePanelSizeStyle = computed(() => (isMobile.value ? {} : panelSizeStyle.value))
/** Mobile: suppress anchor transform so CSS media-query reset takes effect */
const effectiveFrameStyle = computed(() => (isMobile.value ? {} : frameStyle.value))

const dockClass = computed(() => [
  'panel-dock',
  `panel-dock--${props.position}`,
  {
    'panel-dock--collapsed': collapsed.value,
    'panel-dock--mobile': isMobile.value,
    'panel-dock--timeline': props.panelKey === 'timeline',
  },
])

const resizeHandleClass = computed(() => [
  'resize-handle',
  `resize-handle--${props.handlePosition}`,
  `resize-handle--${props.panelKey ?? 'generic'}`,
])

const bodyClass = computed(() => [
  'panel-dock__body',
  {
    'panel-dock__body--mobile': isMobile.value,
    'panel-dock__body--hidden': props.bodyOverflow === 'hidden',
  },
])

function handleToggleCollapsed() {
  toggleCollapsed()
  emit('update:collapsed', collapsed.value)
}

defineExpose({ showPanel, hidePanel, resetPanel, toggleCollapsed })
</script>

<template>
  <div
    class="panel-anchor"
    :class="[anchorClass, { 'panel-anchor--hidden': !visible }]"
    :style="effectiveFrameStyle"
  >
    <!-- 隐藏态：恢复胶囊 -->
    <button
      v-if="!visible"
      class="restore-pill"
      type="button"
      :class="{ 'restore-pill--dragging': dragging }"
      :title="`${panelLabel} · 拖动自由移动 / 点击展开并恢复原布局`"
      @pointerdown="startPillDragging"
      @click.prevent
    >
      <svg viewBox="0 0 16 16" aria-hidden="true">
        <path
          d="M2 8s2.2-3.5 6-3.5S14 8 14 8s-2.2 3.5-6 3.5S2 8 2 8Zm6 1.8A1.8 1.8 0 1 0 8 6.2a1.8 1.8 0 0 0 0 3.6Z"
        />
      </svg>
      <span>{{ panelLabel }}</span>
    </button>

    <!-- 显示态：面板壳 -->
    <section v-else class="panel-dock__frame" :class="dockClass" :style="effectivePanelSizeStyle">
      <!-- 标题栏 -->
      <header class="panel-dock__head" :class="{ 'panel-dock__head--dragging': dragging }">
        <button
          v-if="draggable"
          class="panel-dock__grip"
          type="button"
          title="拖动"
          aria-label="拖动面板"
          @pointerdown.prevent="startDragging"
        >
          <span></span><span></span><span></span>
        </button>
        <span class="panel-dock__label">{{ panelLabel }}</span>
        <div class="panel-dock__actions">
          <button
            v-if="collapsible"
            class="panel-dock__btn"
            type="button"
            :title="collapsed ? '展开' : '收起'"
            :aria-label="collapsed ? '展开面板' : '折叠面板'"
            :aria-expanded="!collapsed"
            @click="handleToggleCollapsed"
          >
            <svg v-if="collapsed" viewBox="0 0 16 16" aria-hidden="true">
              <path d="M3 8h10M8 3l5 5-5 5" />
            </svg>
            <svg v-else viewBox="0 0 16 16" aria-hidden="true">
              <path d="M3 8h10M8 13 3 8l5-5" />
            </svg>
          </button>
          <button
            class="panel-dock__btn"
            type="button"
            title="复位"
            aria-label="复位面板位置与尺寸"
            @click="resetPanel"
          >
            <svg viewBox="0 0 16 16" aria-hidden="true">
              <path d="M3 8a5 5 0 1 0 1.5-3.6M3 3v3.4h3.4" />
            </svg>
          </button>
          <button
            class="panel-dock__btn"
            type="button"
            title="隐藏"
            aria-label="隐藏面板"
            @click="hidePanel"
          >
            <svg viewBox="0 0 16 16" aria-hidden="true">
              <path
                d="m2.4 2.4 11.2 11.2M6.2 6.2A2.6 2.6 0 0 0 10 9.8M3 8s2.2-3.5 5-3.5c.8 0 1.5.1 2.2.4M13 8s-1.1 1.8-3 2.8"
              />
            </svg>
          </button>
        </div>
      </header>

      <!-- 内容区 -->
      <div v-show="!collapsed" :class="bodyClass">
        <slot />
      </div>

      <!-- 缩放手柄 -->
      <button
        v-if="resizeEnabled"
        :class="resizeHandleClass"
        type="button"
        title="拖动调整尺寸 · 双击恢复默认"
        aria-label="调整面板尺寸"
        @pointerdown.prevent="startResizing"
        @dblclick="resetPanel"
      >
        <span class="resize-corner resize-corner--one"></span>
        <span class="resize-corner resize-corner--two"></span>
      </button>
    </section>
  </div>
</template>

<style scoped>
/* ═══ 面板级 CSS 变量（从 tokens 派生） ═══ */
.panel-anchor {
  --panel-title-height: 2.35rem;
  --panel-padding: 0.4rem;
  --panel-body-padding: 0.45rem;
  --panel-collapsed-height: 2.9rem;
  --panel-scrollbar-track: var(--surface-hover);
  --panel-scrollbar-thumb: var(--border-strong);
  --panel-backdrop-blur: 12px;

  position: relative;
  pointer-events: auto;
  will-change: transform;
  transition: transform var(--motion-base) var(--ease-standard);
  width: fit-content;
  height: fit-content;
  max-width: 100%;
  display: block;
  min-width: 200px;
}

.panel-anchor--dock-right {
  max-width: calc(100vw - 1.6rem);
  margin-inline-start: auto;
}

/* 隐藏态：anchor 收缩到恢复胶囊本身宽度（去掉 200px min-width 占位），
   使 dock-right 面板的胶囊右缘与顶栏右缘对齐、dock-left 的胶囊左缘与顶栏左缘对齐 */
.panel-anchor--hidden {
  min-width: 0;
}

.panel-anchor--dock-right :deep(.panel-dock__frame) {
  margin-inline-start: auto;
}

.panel-anchor--interacting {
  transition: none;
}

/* ═══ 恢复胶囊 ═══ */
.restore-pill {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  border: 1px solid var(--border-accent);
  border-radius: var(--radius-pill);
  padding: var(--space-2) var(--space-3);
  background: var(--surface-1);
  color: var(--text-primary);
  cursor: grab;
  font: inherit;
  font-size: var(--font-size-caption);
  box-shadow: var(--elevation-2);
  opacity: 0.72;
  backdrop-filter: blur(var(--panel-backdrop-blur));
  -webkit-backdrop-filter: blur(var(--panel-backdrop-blur));
  user-select: none;
  touch-action: none;
  transition:
    opacity var(--motion-base) var(--ease-standard),
    border-color var(--motion-base) var(--ease-standard),
    box-shadow var(--motion-base) var(--ease-standard);
}

.restore-pill:hover {
  opacity: 1;
  border-color: var(--border-strong);
  box-shadow:
    var(--elevation-3),
    0 0 12px var(--accent-surface);
}

.restore-pill--dragging {
  cursor: grabbing;
  opacity: 1;
}

.restore-pill svg {
  width: 0.86rem;
  height: 0.86rem;
  fill: none;
  stroke: currentColor;
  stroke-width: 1.5;
  stroke-linecap: round;
  stroke-linejoin: round;
}

/* ═══ 面板壳 ═══ */
.panel-dock__frame {
  position: relative;
  min-width: 0;
  display: flex;
  flex-direction: column;
  transition:
    opacity var(--motion-slow) var(--ease-decelerate),
    transform var(--motion-slow) var(--ease-standard),
    box-shadow var(--motion-slow) var(--ease-standard);
  overflow: visible;
  min-height: 0;
  border: 1px solid var(--border-default);
  border-radius: var(--radius-lg);
  background:
    linear-gradient(180deg, var(--surface-2), var(--surface-1)),
    radial-gradient(circle at top left, var(--surface-hover), transparent 34%),
    radial-gradient(circle at bottom right, var(--accent-surface), transparent 42%);
  box-shadow: var(--elevation-2);
  backdrop-filter: blur(var(--glass-blur)) saturate(1.08);
  -webkit-backdrop-filter: blur(var(--glass-blur)) saturate(1.08);
  contain: layout paint;
}

/* 顶部高光条 */
.panel-dock__frame::before {
  content: '';
  position: absolute;
  top: 0;
  left: 12%;
  right: 12%;
  height: 1px;
  background: linear-gradient(90deg, transparent, var(--border-accent), transparent);
  border-radius: 50%;
  pointer-events: none;
  z-index: 3;
}

.panel-dock__frame:hover {
  box-shadow: var(--elevation-3);
}

/* 折叠态 */
.panel-dock__frame.panel-dock--collapsed {
  opacity: 0.55;
  background: var(--surface-1);
  box-shadow: var(--elevation-1);
}

/* 折叠态：header 继承 frame 圆角，避免底部方角露出 */
.panel-dock--collapsed .panel-dock__head {
  border-radius: var(--radius-lg);
}

.panel-dock--collapsed.panel-dock--left .panel-dock__head {
  border-radius: 0 var(--radius-lg) var(--radius-lg) 0;
}

.panel-dock--collapsed.panel-dock--right .panel-dock__head {
  border-radius: var(--radius-lg) 0 0 var(--radius-lg);
}

.panel-dock__frame.panel-dock--collapsed:hover {
  opacity: 1;
  transform: translateY(-2px);
  border-color: var(--border-strong);
  box-shadow:
    var(--elevation-3),
    0 0 14px var(--accent-surface);
}

/* 位置修饰 */
.panel-dock--left {
  border-top-left-radius: 0;
  border-bottom-left-radius: 0;
}

.panel-dock--right {
  border-top-right-radius: 0;
  border-bottom-right-radius: 0;
}

.panel-dock--bottom {
  border-bottom-left-radius: 0;
  border-bottom-right-radius: 0;
}

.panel-dock--mobile {
  width: 100%;
  max-width: none;
  min-width: 0;
}

.panel-dock--timeline {
  max-width: none;
  border-bottom-left-radius: var(--radius-lg);
  border-bottom-right-radius: var(--radius-lg);
}

.panel-dock--timeline .panel-dock__head {
  justify-content: space-between;
}

.panel-dock--timeline .panel-dock__body {
  overflow: hidden;
}

/* ═══ 标题栏 ═══ */
.panel-dock__head {
  position: relative;
  z-index: 2;
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-2);
  border: 1px solid var(--border-subtle);
  border-bottom-color: var(--border-subtle);
  border-radius: var(--radius-lg) var(--radius-lg) 0 0;
  background: linear-gradient(180deg, var(--surface-2), var(--surface-1));
  min-height: var(--panel-title-height);
  backdrop-filter: blur(var(--panel-backdrop-blur)) saturate(1.08);
  -webkit-backdrop-filter: blur(var(--panel-backdrop-blur)) saturate(1.08);
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.06),
    var(--elevation-1);
}

.panel-dock__head--dragging {
  cursor: grabbing;
}

/* 拖拽手柄 */
.panel-dock__grip {
  display: inline-flex;
  align-items: center;
  gap: 0.16rem;
  padding: 0.38rem 0.46rem;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-md);
  background: var(--surface-sunken);
  color: var(--text-secondary);
  cursor: grab;
  font: inherit;
  touch-action: none;
  flex: 0 0 auto;
  transition:
    border-color var(--motion-fast) var(--ease-soft),
    color var(--motion-fast) var(--ease-soft);
}

.panel-dock__grip:hover {
  border-color: var(--border-accent);
  background: var(--accent-surface);
  color: var(--text-strong);
}

.panel-dock__grip span {
  width: 0.2rem;
  height: 0.2rem;
  border-radius: var(--radius-pill);
  background: var(--surface-sunken);
}

.panel-dock__grip:hover span {
  background: var(--accent);
}

/* 标题文本 */
.panel-dock__label {
  min-width: 0;
  margin-right: 0;
  color: var(--text-primary);
  font-size: var(--font-size-caption);
  letter-spacing: 0.04em;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* 操作按钮组 */
.panel-dock__actions {
  display: inline-flex;
  gap: var(--space-1);
  margin-left: auto;
  flex: 0 0 auto;
}

.panel-dock__btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 1.95rem;
  height: 1.95rem;
  padding: 0;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-md);
  background: var(--surface-sunken);
  color: var(--text-primary);
  cursor: pointer;
  font: inherit;
  font-size: var(--font-size-caption);
  flex: 0 0 auto;
  transition:
    border-color var(--motion-fast) var(--ease-soft),
    color var(--motion-fast) var(--ease-soft),
    background-color var(--motion-fast) var(--ease-soft);
}

.panel-dock__btn:hover {
  border-color: var(--border-default);
  color: var(--text-strong);
  background: var(--surface-hover);
}

.panel-dock__btn:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}

.panel-dock__btn svg {
  width: 0.9rem;
  height: 0.9rem;
  fill: none;
  stroke: currentColor;
  stroke-width: 1.5;
  stroke-linecap: round;
  stroke-linejoin: round;
}

/* ═══ 内容区 ═══ */
.panel-dock__body {
  margin-top: 0;
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  position: relative;
  z-index: 1;
  padding: var(--panel-body-padding) calc(var(--panel-body-padding) - 0.07rem)
    var(--panel-body-padding);
  border: 1px solid var(--border-subtle);
  border-top: 0;
  border-radius: 0 0 var(--radius-lg) var(--radius-lg);
  background: linear-gradient(180deg, var(--accent-surface), transparent);
  box-shadow:
    inset 0 1px 0 var(--surface-hover),
    var(--elevation-1);
  scrollbar-width: thin;
  scrollbar-color: var(--panel-scrollbar-thumb) var(--panel-scrollbar-track);
}

.panel-dock__body::-webkit-scrollbar {
  width: 4px;
}

.panel-dock__body::-webkit-scrollbar-track {
  background: var(--panel-scrollbar-track);
}

.panel-dock__body::-webkit-scrollbar-thumb {
  background: var(--panel-scrollbar-thumb);
  border-radius: var(--radius-pill);
}

.panel-dock__body--mobile {
  overflow-y: auto;
  -webkit-overflow-scrolling: touch;
}

.panel-dock__body--hidden {
  overflow: hidden;
}

/* ═══ 缩放手柄 ═══ */
.resize-handle {
  position: absolute;
  width: 1rem;
  height: 1rem;
  border: none;
  background: transparent;
  opacity: 0;
  transition:
    opacity var(--motion-fast) var(--ease-soft),
    transform var(--motion-fast) var(--ease-soft);
  z-index: 10;
  padding: 0;
  display: grid;
  place-items: center;
  cursor: nwse-resize;
}

.panel-dock__frame:hover .resize-handle,
.panel-anchor:focus-within .resize-handle {
  opacity: 0.86;
}

.resize-handle--bottom-right {
  right: -0.02rem;
  bottom: -0.02rem;
}

.resize-handle--bottom-left {
  left: -0.02rem;
  bottom: -0.02rem;
  cursor: nesw-resize;
}

.resize-handle--top-right {
  right: -0.02rem;
  top: -0.02rem;
  cursor: nesw-resize;
  transform: rotate(180deg);
}

.resize-handle--top-left {
  left: -0.02rem;
  top: -0.02rem;
  cursor: nwse-resize;
}

/* 面板特定缩放手柄装饰 */
.resize-handle--layers .resize-corner--one {
  right: 0.04rem;
  bottom: 0.18rem;
  width: 0.66rem;
  height: 2px;
  transform: rotate(45deg);
  transform-origin: right bottom;
}

.resize-handle--layers .resize-corner--two {
  right: 0.18rem;
  bottom: 0.04rem;
  width: 2px;
  height: 0.66rem;
  transform: rotate(45deg);
  transform-origin: right bottom;
}

.resize-handle--analysis .resize-corner--one {
  left: 0.04rem;
  bottom: 0.18rem;
  width: 0.66rem;
  height: 2px;
  transform: rotate(-45deg);
  transform-origin: left bottom;
}

.resize-handle--analysis .resize-corner--two {
  left: 0.18rem;
  bottom: 0.04rem;
  width: 2px;
  height: 0.66rem;
  transform: rotate(-45deg);
  transform-origin: left bottom;
}

.resize-corner {
  position: absolute;
  background: var(--accent);
  border-radius: var(--radius-pill);
  box-shadow: inset 0 0 0 1px var(--surface-hover);
}

.resize-corner--one {
  right: 0.12rem;
  bottom: 0.24rem;
  width: 0.42rem;
  height: 2px;
}

.resize-corner--two {
  right: 0.24rem;
  bottom: 0.12rem;
  width: 2px;
  height: 0.42rem;
}

.panel-anchor:hover .resize-handle {
  transform: scale(1.02);
}

/* ═══ 响应式：移动端禁用拖拽/缩放 ═══ */
@media (max-width: 768px) {
  .panel-anchor {
    transform: none;
  }

  .panel-dock__grip {
    display: none;
  }

  .panel-dock__head {
    padding: var(--space-2) var(--space-3);
  }

  .panel-dock__body {
    padding: var(--space-3);
  }

  .resize-handle {
    display: none;
  }
}

/* ═══ 减弱动效 ═══ */
@media (prefers-reduced-motion: reduce) {
  .panel-anchor,
  .panel-dock__frame,
  .panel-dock__grip,
  .panel-dock__btn,
  .restore-pill,
  .resize-handle {
    transition: none;
  }

  .panel-dock__frame {
    backdrop-filter: none;
    -webkit-backdrop-filter: none;
  }
}
</style>
