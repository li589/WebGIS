/**
 * usePanelDragResize — 浮层面板拖拽 / 缩放 / 持久化 composable
 *
 * 从 ControlPanel.vue 与 TimelinePanel.vue 提取的共享逻辑。
 * 管理：拖动位移、尺寸缩放、折叠/隐藏/复位、localStorage 持久化。
 *
 * 约定：
 * - 拖动只改 offset（位置记忆），永不改 width/height
 * - 缩放只改 width/height；对边是否钉住由布局（CSS dock）或 offset 补偿决定
 * - 持久化写入 debounce 120ms，避免高频拖拽时频繁写 localStorage
 */

import { computed, onBeforeUnmount, ref, watch, type ComputedRef, type Ref } from 'vue'
import {
  clampPanelDim,
  clampPanelOffset,
  isRightDockedPanel,
  nextSizeFromResizeDelta,
  offsetXToPinRightEdge,
  offsetYToPinBottomEdge,
  shouldCompensateOffsetOnResize,
} from '../control-panel-geometry'

// ── 类型定义 ──────────────────────────────────────────────────────────

export interface UsePanelDragResizeOptions {
  /** 面板唯一标识，用于 localStorage 持久化 */
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
}

interface PersistedPanelState {
  visible: boolean
  collapsed: boolean
  offsetX: number
  offsetY: number
  width?: number
  height?: number
  pillOffsetX?: number
  pillOffsetY?: number
}

interface VisibleLayoutSnapshot {
  offsetX: number
  offsetY: number
  width: number
  height: number
  collapsed: boolean
  userResized: boolean
}

export interface PanelDragResizeReturn {
  // 反应式状态
  visible: Ref<boolean>
  collapsed: Ref<boolean>
  offsetX: Ref<number>
  offsetY: Ref<number>
  panelWidth: Ref<number>
  panelHeight: Ref<number>
  dragging: Ref<boolean>
  resizing: Ref<boolean>
  draggingPill: Ref<boolean>

  // 计算属性
  resizeEnabled: ComputedRef<boolean>
  layoutPinsRightEdge: ComputedRef<boolean>
  frameStyle: ComputedRef<{ transform: string }>
  panelSizeStyle: ComputedRef<Record<string, string>>
  anchorClass: ComputedRef<Record<string, boolean>>

  // 拖拽
  startDragging: (event: PointerEvent) => void
  startPillDragging: (event: PointerEvent) => void

  // 缩放
  startResizing: (event: PointerEvent) => void

  // 操作
  toggleCollapsed: () => void
  hidePanel: () => void
  showPanel: () => void
  resetPanel: () => void
}

// ── 常量 ──────────────────────────────────────────────────────────────

const PILL_DRAG_THRESHOLD_PX = 5
const PERSIST_DEBOUNCE_MS = 120

// ── 持久化辅助 ────────────────────────────────────────────────────────

function getStorageKey(panelKey: string | undefined): string {
  return panelKey ? `geo-panel:${panelKey}` : ''
}

function readPersistedState(panelKey: string | undefined): PersistedPanelState | null {
  if (typeof window === 'undefined' || !panelKey) return null
  try {
    const raw = window.localStorage.getItem(getStorageKey(panelKey))
    return raw ? (JSON.parse(raw) as PersistedPanelState) : null
  } catch {
    return null
  }
}

// ── composable ────────────────────────────────────────────────────────

export function usePanelDragResize(options: UsePanelDragResizeOptions): PanelDragResizeReturn {
  const {
    panelKey,
    draggable = true,
    collapsible = true,
    defaultCollapsed = false,
    maxOffsetX = 120,
    maxOffsetY = 100,
    defaultWidth = 0,
    defaultHeight = 0,
    minWidth = 200,
    minHeight = 80,
    maxWidth = 600,
    maxHeight = 800,
    resizable = true,
    handlePosition = 'bottom-right',
    showResizeHandle = true,
  } = options

  // ── 从 localStorage 恢复状态 ────────────────────────────────────────
  const persistedState = readPersistedState(panelKey)

  const visible = ref(persistedState?.visible ?? true)
  const collapsed = ref(persistedState?.collapsed ?? defaultCollapsed)
  // 恢复路径同样 clamp：拖拽中的 clamp 不覆盖持久化值——越界 offset（异常
  // 写入/旧版本数据）一旦持久化，面板每次刷新都跑到屏幕外回不来
  // （2026-08-23 "分析面板消失"排查发现的恢复缺口）
  const offsetX = ref(
    clampPanelOffset(
      !visible.value && typeof persistedState?.pillOffsetX === 'number'
        ? persistedState.pillOffsetX
        : (persistedState?.offsetX ?? 0),
      maxOffsetX,
    ),
  )
  const offsetY = ref(
    clampPanelOffset(
      !visible.value && typeof persistedState?.pillOffsetY === 'number'
        ? persistedState.pillOffsetY
        : (persistedState?.offsetY ?? 0),
      maxOffsetY,
    ),
  )
  const panelWidth = ref(persistedState?.width ?? defaultWidth)
  const panelHeight = ref(persistedState?.height ?? defaultHeight)
  const userResized = ref(Boolean(persistedState?.width || persistedState?.height))
  const persistTimer = ref<number | null>(null)

  const visibleLayoutSnapshot = ref<VisibleLayoutSnapshot | null>(
    persistedState
      ? {
          offsetX: persistedState.offsetX ?? 0,
          offsetY: persistedState.offsetY ?? 0,
          width: persistedState.width ?? defaultWidth,
          height: persistedState.height ?? defaultHeight,
          collapsed: persistedState.collapsed ?? defaultCollapsed,
          userResized: Boolean(persistedState.width || persistedState.height),
        }
      : null,
  )

  // ── 拖拽状态 ────────────────────────────────────────────────────────
  let dragStartX = 0
  let dragStartY = 0
  let baseOffsetX = 0
  let baseOffsetY = 0
  const dragging = ref(false)
  const draggingPill = ref(false)
  let pillGestureMoved = false

  /** 显隐切换时短暂关闭 transform 过渡，避免卡顿感 */
  const suppressTransformTransition = ref(false)

  // ── 缩放状态 ────────────────────────────────────────────────────────
  let resizeStartX = 0
  let resizeStartY = 0
  let baseWidth = 0
  let baseHeight = 0
  let baseResizeOffsetX = 0
  let baseResizeOffsetY = 0
  const resizing = ref(false)

  // ── 计算属性 ────────────────────────────────────────────────────────
  const resolvedMinWidth = computed(() => Math.max(220, minWidth))
  const resolvedMinHeight = computed(() => Math.max(120, minHeight))
  const resolvedMaxWidth = computed(() => Math.max(resolvedMinWidth.value, maxWidth))
  const resolvedMaxHeight = computed(() => Math.max(resolvedMinHeight.value, maxHeight))
  const resizeEnabled = computed(() => resizable && !collapsed.value && showResizeHandle)
  const layoutPinsRightEdge = computed(() => isRightDockedPanel(panelKey))

  const frameStyle = computed(() => ({
    transform: `translate(${offsetX.value}px, ${offsetY.value}px)`,
  }))

  const anchorClass = computed(() => ({
    'panel-anchor--dock-right': layoutPinsRightEdge.value,
    'panel-anchor--interacting':
      dragging.value || resizing.value || suppressTransformTransition.value,
  }))

  function clampPanelWidth(value: number): number {
    return clampPanelDim(value, resolvedMinWidth.value, resolvedMaxWidth.value)
  }

  function clampPanelHeight(value: number): number {
    return clampPanelDim(value, resolvedMinHeight.value, resolvedMaxHeight.value)
  }

  const panelSizeStyle = computed<Record<string, string>>(() => {
    const style: Record<string, string> = {}
    if (collapsed.value) {
      style.height = 'var(--panel-collapsed-height)'
      style.minHeight = 'var(--panel-collapsed-height)'
      style.maxHeight = 'var(--panel-collapsed-height)'
      const w = panelWidth.value > 0 ? panelWidth.value : defaultWidth
      if (w > 0) style.width = `${clampPanelWidth(w)}px`
      style.minWidth = `${resolvedMinWidth.value}px`
      style.maxWidth = `${resolvedMaxWidth.value}px`
      return style
    }
    const w = panelWidth.value > 0 ? panelWidth.value : defaultWidth
    const h = panelHeight.value > 0 ? panelHeight.value : defaultHeight
    if (w > 0) style.width = `${clampPanelWidth(w)}px`
    if (h > 0) style.height = `${clampPanelHeight(h)}px`
    style.minWidth = `${resolvedMinWidth.value}px`
    style.maxWidth = `${resolvedMaxWidth.value}px`
    style.minHeight = `${resolvedMinHeight.value}px`
    style.maxHeight = `${resolvedMaxHeight.value}px`
    return style
  })

  // ── 布局快照 ────────────────────────────────────────────────────────

  function captureVisibleLayout(): VisibleLayoutSnapshot {
    return {
      offsetX: offsetX.value,
      offsetY: offsetY.value,
      width: panelWidth.value,
      height: panelHeight.value,
      collapsed: collapsed.value,
      userResized: userResized.value,
    }
  }

  function applyVisibleLayout(snap: VisibleLayoutSnapshot): void {
    offsetX.value = snap.offsetX
    offsetY.value = snap.offsetY
    panelWidth.value = snap.width
    panelHeight.value = snap.height
    collapsed.value = snap.collapsed
    userResized.value = snap.userResized
  }

  // ── 显隐 / 折叠 / 复位 ──────────────────────────────────────────────

  function toggleCollapsed(): void {
    if (!collapsible) return
    collapsed.value = !collapsed.value
  }

  function hidePanel(): void {
    visibleLayoutSnapshot.value = captureVisibleLayout()
    suppressTransformTransition.value = true
    visible.value = false
    window.requestAnimationFrame(() => {
      suppressTransformTransition.value = false
    })
  }

  function showPanel(): void {
    suppressTransformTransition.value = true
    if (visibleLayoutSnapshot.value) {
      applyVisibleLayout(visibleLayoutSnapshot.value)
    }
    visible.value = true
    window.requestAnimationFrame(() => {
      suppressTransformTransition.value = false
    })
  }

  function resetPanel(): void {
    offsetX.value = 0
    offsetY.value = 0
    panelWidth.value = defaultWidth || 0
    panelHeight.value = defaultHeight || 0
    collapsed.value = defaultCollapsed
    visible.value = true
    userResized.value = false
    visibleLayoutSnapshot.value = captureVisibleLayout()
  }

  // ── 拖拽 ────────────────────────────────────────────────────────────

  function handlePointerMove(event: PointerEvent): void {
    if (!dragging.value) return
    const dx = event.clientX - dragStartX
    const dy = event.clientY - dragStartY
    if (Math.abs(dx) > PILL_DRAG_THRESHOLD_PX || Math.abs(dy) > PILL_DRAG_THRESHOLD_PX) {
      pillGestureMoved = true
    }
    if (draggingPill.value || !visible.value) {
      offsetX.value = baseOffsetX + dx
      offsetY.value = baseOffsetY + dy
      return
    }
    offsetX.value = clampPanelOffset(baseOffsetX + dx, maxOffsetX)
    offsetY.value = clampPanelOffset(baseOffsetY + dy, maxOffsetY)
  }

  function stopDragging(): void {
    dragging.value = false
    draggingPill.value = false
    window.removeEventListener('pointermove', handlePointerMove)
    window.removeEventListener('pointerup', stopDragging)
  }

  function startDragging(event: PointerEvent): void {
    if (!draggable || window.innerWidth < 900) return
    pillGestureMoved = false
    draggingPill.value = false
    dragging.value = true
    dragStartX = event.clientX
    dragStartY = event.clientY
    baseOffsetX = offsetX.value
    baseOffsetY = offsetY.value
    window.addEventListener('pointermove', handlePointerMove)
    window.addEventListener('pointerup', stopDragging)
  }

  function stopPillDragging(): void {
    const moved = pillGestureMoved
    dragging.value = false
    draggingPill.value = false
    window.removeEventListener('pointermove', handlePointerMove)
    window.removeEventListener('pointerup', stopPillDragging)
    if (!moved) showPanel()
  }

  function startPillDragging(event: PointerEvent): void {
    if (!draggable) {
      showPanel()
      return
    }
    if (event.button !== 0) return
    event.preventDefault()
    pillGestureMoved = false
    draggingPill.value = true
    dragging.value = true
    dragStartX = event.clientX
    dragStartY = event.clientY
    baseOffsetX = offsetX.value
    baseOffsetY = offsetY.value
    window.addEventListener('pointermove', handlePointerMove)
    window.addEventListener('pointerup', stopPillDragging)
  }

  // ── 缩放 ────────────────────────────────────────────────────────────

  function handleResizeMove(event: PointerEvent): void {
    if (!resizing.value) return
    userResized.value = true
    const deltaX = event.clientX - resizeStartX
    const deltaY = event.clientY - resizeStartY
    const raw = nextSizeFromResizeDelta({
      handlePosition,
      baseWidth,
      baseHeight,
      deltaX,
      deltaY,
    })
    const clampedWidth = clampPanelWidth(raw.width)
    const clampedHeight = clampPanelHeight(raw.height)
    panelWidth.value = clampedWidth
    panelHeight.value = clampedHeight

    if (
      !shouldCompensateOffsetOnResize({
        panelKey,
        handlePosition,
        layoutPinsRightEdge: layoutPinsRightEdge.value,
      })
    ) {
      return
    }

    const fromLeft = handlePosition === 'bottom-left' || handlePosition === 'top-left'
    const fromTop = handlePosition === 'top-left' || handlePosition === 'top-right'
    if (fromLeft) {
      offsetX.value = offsetXToPinRightEdge(baseResizeOffsetX, baseWidth, clampedWidth, maxOffsetX)
    }
    if (fromTop) {
      offsetY.value = offsetYToPinBottomEdge(
        baseResizeOffsetY,
        baseHeight,
        clampedHeight,
        maxOffsetY,
      )
    }
  }

  function stopResizing(): void {
    resizing.value = false
    window.removeEventListener('pointermove', handleResizeMove)
    window.removeEventListener('pointerup', stopResizing)
  }

  function startResizing(event: PointerEvent): void {
    if (!resizeEnabled.value) return
    event.preventDefault()
    resizing.value = true
    resizeStartX = event.clientX
    resizeStartY = event.clientY
    baseWidth = panelWidth.value || defaultWidth || resolvedMinWidth.value
    baseHeight = panelHeight.value || defaultHeight || resolvedMinHeight.value
    baseResizeOffsetX = offsetX.value
    baseResizeOffsetY = offsetY.value
    window.addEventListener('pointermove', handleResizeMove)
    window.addEventListener('pointerup', stopResizing)
  }

  // ── 持久化 ──────────────────────────────────────────────────────────

  watch(
    [visible, collapsed, offsetX, offsetY, panelWidth, panelHeight, visibleLayoutSnapshot],
    () => {
      if (typeof window === 'undefined' || !panelKey) return
      if (persistTimer.value !== null) window.clearTimeout(persistTimer.value)
      persistTimer.value = window.setTimeout(() => {
        const snap = visibleLayoutSnapshot.value
        const layoutOffsetX = visible.value ? offsetX.value : (snap?.offsetX ?? offsetX.value)
        const layoutOffsetY = visible.value ? offsetY.value : (snap?.offsetY ?? offsetY.value)
        const layoutWidth = visible.value
          ? userResized.value
            ? panelWidth.value
            : undefined
          : snap?.userResized
            ? snap.width
            : undefined
        const layoutHeight = visible.value
          ? userResized.value
            ? panelHeight.value
            : undefined
          : snap?.userResized
            ? snap.height
            : undefined
        const nextState: PersistedPanelState = {
          visible: visible.value,
          collapsed: visible.value ? collapsed.value : (snap?.collapsed ?? collapsed.value),
          offsetX: layoutOffsetX,
          offsetY: layoutOffsetY,
          width: layoutWidth,
          height: layoutHeight,
          pillOffsetX: visible.value ? undefined : offsetX.value,
          pillOffsetY: visible.value ? undefined : offsetY.value,
        }
        window.localStorage.setItem(getStorageKey(panelKey), JSON.stringify(nextState))
        persistTimer.value = null
      }, PERSIST_DEBOUNCE_MS)
    },
  )

  // ── 清理 ────────────────────────────────────────────────────────────

  onBeforeUnmount(() => {
    stopDragging()
    stopPillDragging()
    stopResizing()
    if (persistTimer.value !== null) window.clearTimeout(persistTimer.value)
  })

  return {
    visible,
    collapsed,
    offsetX,
    offsetY,
    panelWidth,
    panelHeight,
    dragging,
    resizing,
    draggingPill,
    resizeEnabled,
    layoutPinsRightEdge,
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
  }
}
