<script setup lang="ts">
/**
 * WorkflowCanvas.vue
 *
 * 基于 LiteGraph.js 的工作流画布组件。
 * 提供节点编辑、连线、序列化/反序列化能力。
 *
 * 使用方式：
 *   <WorkflowCanvas
 *     :definition="currentDefinition"
 *     :readonly="isReadonly"
 *     @change="handleGraphChange"
 *     @node-select="handleNodeSelect"
 *   />
 */
import { onMounted, onBeforeUnmount, ref, shallowRef, watch } from 'vue'
import { AlertTriangle } from '../ui/icons'
import InlineLoader from '../common/InlineLoader.vue'
import {
  LGraph,
  LGraphCanvas,
  LiteGraph,
  getEngineColor,
  registerWorkflowNodeTypes,
  graphDataToWorkflowNodes,
  syncGraphSlotsWithTemplates,
  getGraphNodes,
  liteGraphTheme,
  asLGraphCanvasRuntime,
} from './litegraph-setup'
import type {
  LGraphClass,
  LGraphCanvasClass,
  LGraphNodeClass,
  serializedLGraph,
} from './litegraph-setup'
import type {
  WorkflowDefinition,
  WorkflowDefinitionNode,
  WorkflowDefinitionLink,
  NodeTemplate,
} from '../../services/workflow-definition-api'
import {
  resolveCanvasColor,
  getGridColors,
  getLiteGraphColors,
  getCanvasClearColor,
  invalidateCanvasThemeCache,
} from './canvas-theme'
import { useThemeStore } from '../../stores/theme'
// P1-5: composables 从 God Component 拆分
import { useAlignmentGuides, SNAP_GRID_SIZE } from './composables/useAlignmentGuides'
import { usePortTooltip } from './composables/usePortTooltip'
import { useMinimap } from './composables/useMinimap'
import { useNodeOperations } from './composables/useNodeOperations'

const props = defineProps<{
  /** 当前加载的工作流定义 */
  definition: WorkflowDefinition | null
  /** 所有可用的节点模板（用于注册节点类型） */
  nodeTemplates: NodeTemplate[]
  /** 是否只读模式（系统预设工作流） */
  readonly?: boolean
}>()

const emit = defineEmits<{
  /** 图结构发生变化（节点增删、连线变化） */
  change: [payload: { nodes: WorkflowDefinitionNode[]; links: WorkflowDefinitionLink[] }]
  /** 选中节点变化 */
  nodeSelect: [node: LGraphNodeClass | null]
}>()

const canvasContainerRef = ref<HTMLDivElement | null>(null)
const canvasRef = ref<HTMLCanvasElement | null>(null)
const minimapRef = ref<HTMLCanvasElement | null>(null)

const graphInstance = shallowRef<LGraphClass | null>(null)
const canvasInstance = shallowRef<LGraphCanvasClass | null>(null)
const isReady = ref(false)
const errorMsg = ref<string | null>(null)
let resizeObserver: ResizeObserver | null = null

// P1-5: 对齐辅助线 / 端口提示 / 小地图 / 节点操作 — 从 composables 导入
const { alignmentGuides, clearAlignmentGuides, applySnapWhileDragging, computeAlignmentGuides } =
  useAlignmentGuides(graphInstance)

const { portTooltip, portTooltipStyle, hidePortTooltip, updatePortTooltipFromEvent } =
  usePortTooltip(graphInstance, canvasRef, () => props.nodeTemplates)

const { bindMinimapInteractions, startMinimapTimer, disposeMinimap } = useMinimap(
  minimapRef,
  graphInstance,
  canvasInstance,
  canvasRef,
)

// emitChange 节流：节点拖动时 onNodeMoved 每秒触发 30-60 次，
// 全图 serialize() + graphDataToWorkflowNodes() 是 O(n) 操作，
// 用 requestAnimationFrame 节流到每帧最多一次，与浏览器渲染同步避免阻塞 UI。
let _emitChangeScheduled = false
function emitChange() {
  if (!graphInstance.value) return
  if (_emitChangeScheduled) return
  _emitChangeScheduled = true
  requestAnimationFrame(() => {
    _emitChangeScheduled = false
    if (!graphInstance.value) return
    try {
      const graphData = graphInstance.value.serialize<serializedLGraph>()
      const { nodes, links } = graphDataToWorkflowNodes(graphData)
      emit('change', { nodes, links })
    } catch (err) {
      console.error('[WorkflowCanvas] Failed to serialize graph:', err)
    }
  })
}

const {
  selectAllNodes,
  copySelectedNodes,
  pasteNodes,
  duplicateSelectedNodes,
  loadDefinitionIntoGraph,
  getSerializedGraph,
  clearGraph,
  arrangeNodes,
  fitView,
  addNodeByType,
  removeNode,
  applyBoundMainTimeline,
} = useNodeOperations(
  graphInstance,
  canvasInstance,
  canvasRef,
  () => props.nodeTemplates,
  emitChange,
)

// ─── 主题切换：刷新 Canvas 颜色缓存并重绘 ──────────────────────────────────
const themeStore = useThemeStore()

function updateGraphNodesTheme(theme: 'dark' | 'light') {
  const graph = graphInstance.value
  if (!graph) return
  const nodes = getGraphNodes(graph)
  for (const node of nodes) {
    const nodeAny = node as unknown as {
      type: string
      color?: string
      bgcolor?: string
      boxcolor?: string
    }
    const template = props.nodeTemplates.find((t) => t.type === nodeAny.type)
    const ec = getEngineColor(nodeAny.type, template?.engine, theme)
    nodeAny.color = ec.nodeBg
    nodeAny.bgcolor = ec.nodeHeader
    nodeAny.boxcolor = ec.accent
  }
}

function applyLiteGraphThemeColors(canvas?: LGraphCanvasClass | null) {
  invalidateCanvasThemeCache()
  const clearColor = getCanvasClearColor()
  if (canvas) {
    ;(canvas as unknown as { clear_background_color: string }).clear_background_color = clearColor
  }
  if (LiteGraph) {
    const lg = liteGraphTheme()
    const c = getLiteGraphColors()
    LiteGraph.NODE_DEFAULT_COLOR = c.nodeBg
    LiteGraph.NODE_DEFAULT_BGCOLOR = c.nodeBg
    LiteGraph.NODE_DEFAULT_BOXCOLOR = c.nodeBox
    LiteGraph.NODE_TITLE_COLOR = c.nodeTitle
    LiteGraph.NODE_TEXT_COLOR = c.nodeText
    lg.NODE_SELECTED_TITLE_COLOR = c.selectedTitle
    lg.NODE_BOX_OUTLINE_COLOR = c.boxOutline
    LiteGraph.LINK_COLOR = c.link
    LiteGraph.CONNECTING_LINK_COLOR = c.connectingLink
    LiteGraph.EVENT_LINK_COLOR = c.eventLink
    lg.LINK_HOVER_COLOR = c.linkHover
    ;(LiteGraph as unknown as Record<string, unknown>).WIDGET_BGCOLOR = c.widgetBg
    ;(LiteGraph as unknown as Record<string, unknown>).WIDGET_TEXT_COLOR = c.widgetText
    ;(LiteGraph as unknown as Record<string, unknown>).WIDGET_OUTLINE_COLOR = c.widgetOutline
  }
  updateGraphNodesTheme(themeStore.mode)
}

watch(
  () => themeStore.mode,
  () => {
    applyLiteGraphThemeColors(canvasInstance.value)
    // 触发画布重绘（背景清屏色随主题切换）
    canvasInstance.value?.setDirty(true, true)
  },
)

// P1-5: portTooltipStyle 已移入 usePortTooltip composable

// P1-5: minimap 定时刷新、剪贴板、handler refs 已移入对应 composables
// 模块级剪贴板仍在 useNodeOperations 内部管理

// keydown 监听句柄（组件销毁时需移除）
let _keydownHandlerRef: ((e: KeyboardEvent) => void) | null = null
let _floatingUiObserver: MutationObserver | null = null
let _floatingPointerDownRef: ((e: PointerEvent) => void) | null = null
let _globalEscRef: ((e: KeyboardEvent) => void) | null = null

/** 将 canvas 容器内的 graphdialog 挪到 body，并用 viewport 坐标固定，避免 overflow 裁切 */
function rehomeGraphDialog(el: HTMLElement) {
  if (el.dataset.wfRehomed === '1') return
  const rect = el.getBoundingClientRect()
  if (el.parentElement !== document.body) {
    document.body.appendChild(el)
  }
  el.style.position = 'fixed'
  const w = rect.width || 160
  const h = rect.height || 36
  const left = Math.max(8, Math.min(rect.left, window.innerWidth - w - 8))
  const top = Math.max(8, Math.min(rect.top, window.innerHeight - h - 8))
  el.style.left = `${left}px`
  el.style.top = `${top}px`
  el.style.zIndex = '11000'
  el.dataset.wfRehomed = '1'
}

function setupLiteGraphFloatingUiGuards() {
  const container = canvasContainerRef.value
  if (!container || _floatingUiObserver) return

  _floatingUiObserver = new MutationObserver((mutations) => {
    for (const m of mutations) {
      m.addedNodes.forEach((node) => {
        if (!(node instanceof HTMLElement)) return
        if (node.classList.contains('graphdialog') || node.classList.contains('dialog')) {
          rehomeGraphDialog(node)
        }
        node.querySelectorAll?.('.graphdialog, .litegraph.dialog').forEach((child) => {
          rehomeGraphDialog(child as HTMLElement)
        })
      })
    }
  })
  _floatingUiObserver.observe(container, { childList: true, subtree: true })

  // 点击菜单/对话框外部 → 关闭
  _floatingPointerDownRef = (e: PointerEvent) => {
    const t = e.target as HTMLElement | null
    if (!t) return
    if (
      t.closest(
        '.litecontextmenu, .graphdialog, .litesearchbox, .param-combo-menu, .param-combobox',
      )
    ) {
      return
    }
    const hasMenu = document.querySelector('.litecontextmenu, .graphdialog, .litesearchbox')
    if (hasMenu) {
      disposeLiteGraphFloatingUi()
    }
  }
  document.addEventListener('pointerdown', _floatingPointerDownRef, true)

  // 全局 Esc（只读画布也能关浮层）
  _globalEscRef = (e: KeyboardEvent) => {
    if (e.key !== 'Escape') return
    const hasMenu = document.querySelector('.litecontextmenu, .graphdialog, .litesearchbox')
    if (hasMenu) {
      e.stopPropagation()
      disposeLiteGraphFloatingUi()
    }
  }
  document.addEventListener('keydown', _globalEscRef, true)
}

// mouseup 监听句柄（用于清空对齐辅助线）— P1-5: alignmentGuides 从 composable 引入

// 多选拖拽：mousedown capture + mouseup 处理器
let _multiSelectMousedownRef: ((e: MouseEvent) => void) | null = null
let _multiSelectMouseupRef: ((e: MouseEvent) => void) | null = null

// P1-5: minimap 事件 handler 已移入 useMinimap composable
// _portMousemoveHandlerRef 保留在组件内：combine snap + tooltip + minimap 判定
let _portMousemoveHandlerRef: ((e: MouseEvent) => void) | null = null
let _mouseupHandlerRef: (() => void) | null = null

// ─── 初始化 ────────────────────────────────────────────────────────────────

function initializeCanvas() {
  if (!canvasRef.value || !canvasContainerRef.value) return

  // 注册节点类型
  if (props.nodeTemplates.length > 0) {
    registerWorkflowNodeTypes(
      props.nodeTemplates.map((t) => ({
        type: t.type,
        title: t.title,
        engine: t.engine,
        inputs: t.inputs,
        outputs: t.outputs,
        params: t.params,
      })),
    )
  }

  try {
    // 显式设置 canvas 绘图缓冲区尺寸（关键：LiteGraph 依赖 canvas.width/height 做坐标映射）
    syncCanvasSize()

    // 创建 Graph 实例
    const graph = new LGraph()
    graphInstance.value = graph

    // 创建 Canvas 实例
    // autoresize=false：禁用 LiteGraph 内置的 autoresize（每次 mousemove 调用 resize()），
    // 改用下方 ResizeObserver + syncCanvasSize 精确控制，避免面板动画过渡时缓冲区被重置为 0
    const canvas = new LGraphCanvas(canvasRef.value, graph, {
      autoresize: false,
    })
    canvasInstance.value = canvas

    // 配置 Canvas
    configureCanvas(canvas)

    // 再次同步尺寸，确保 LGraphCanvas 内部状态正确
    syncCanvasSize()

    // 加载初始定义
    if (props.definition) {
      loadDefinitionIntoGraph(props.definition, graph)
    }

    // 启动渲染循环
    graph.start()

    // 监听容器尺寸变化
    resizeObserver = new ResizeObserver(() => {
      syncCanvasSize()
      if (canvasInstance.value) {
        canvasInstance.value.setDirty(true, true)
      }
    })
    resizeObserver.observe(canvasContainerRef.value)

    // P1-5: 启动 minimap 定时刷新（5 FPS，节流避免阻塞主画布）
    startMinimapTimer(200)

    // 绑定 minimap 点击/拖动事件：同步主画布视口
    bindMinimapInteractions()

    isReady.value = true
    errorMsg.value = null
  } catch (err) {
    console.error('[WorkflowCanvas] Failed to initialize LiteGraph:', err)
    errorMsg.value = err instanceof Error ? err.message : String(err)
  }
}

/**
 * 将 canvas 绘图缓冲区尺寸同步为容器的 CSS 尺寸。
 * LiteGraph 依赖 canvas.width/height（非 CSS）做鼠标坐标映射，
 * 若缓冲区为 0 则所有交互（拖拽、选中）都会失效。
 *
 * 关键：当容器尺寸为 0（面板收起/动画过渡中）时跳过更新，
 * 保留之前的有效尺寸，避免 draw() 因 width==0 提前返回导致
 * visible_nodes 为空 → 节点点击检测失败 → 拖动画布而非节点。
 */
function syncCanvasSize() {
  const canvas = canvasRef.value
  const container = canvasContainerRef.value
  if (!canvas || !container) return
  const rect = container.getBoundingClientRect()
  // 容器尺寸为 0 时跳过（面板动画过渡中），保留之前的缓冲区尺寸
  if (rect.width <= 0 || rect.height <= 0) return
  const w = Math.max(1, Math.floor(rect.width))
  const h = Math.max(1, Math.floor(rect.height))
  if (canvas.width !== w || canvas.height !== h) {
    canvas.width = w
    canvas.height = h
  }
}

function configureCanvas(canvas: LGraphCanvasClass) {
  // 基本配置：关闭点阵图，改由 onDrawBackground 绘制可缩放吸附网格
  canvas.background_image = ''
  canvas.clear_background = true
  // LiteGraph 默认 clear_background_color="#222"，不跟主题 → 浅色下工作区「卡住」不变
  ;(canvas as unknown as { clear_background_color: string }).clear_background_color =
    getCanvasClearColor()
  canvas.allow_searchbox = true
  // 交互核心：允许拖动节点、允许交互（选中/缩放/连接）、允许拖动画布
  // read_only 必须为 false，否则所有节点交互（拖动/选中/缩放/连接）都会被 LiteGraph 拦截
  // read_only 不在类型定义中但运行时存在，用 as 断言
  ;(canvas as unknown as { read_only: boolean }).read_only = false
  canvas.allow_dragnodes = true
  canvas.allow_dragcanvas = true
  canvas.allow_interaction = true
  // 只读模式仅禁止重连连线，其他交互（拖动/选中/缩放）保持启用
  canvas.allow_reconnect_links = !props.readonly
  ;(canvas as unknown as { roundradius: number }).roundradius = 8
  // 启用内置网格吸附（若运行时支持）
  ;(canvas as unknown as { align_to_grid?: boolean }).align_to_grid = true
  if (graphInstance.value) {
    ;(graphInstance.value as unknown as { config: Record<string, unknown> }).config = {
      ...((graphInstance.value as unknown as { config?: Record<string, unknown> }).config ?? {}),
      align_to_grid: true,
    }
  }

  // 主题色适配：Canvas 2D 不支持 var()，需解析为字面量颜色
  applyLiteGraphThemeColors(canvas)
  if (LiteGraph) {
    const lg = liteGraphTheme()
    // 标题栏高度 / 槽位 / 字号（与节点默认尺寸联动，避免溢出）
    LiteGraph.NODE_DEFAULT_SHAPE = 'round'
    LiteGraph.NODE_TITLE_HEIGHT = 24
    LiteGraph.NODE_SLOT_HEIGHT = 22
    LiteGraph.NODE_WIDGET_HEIGHT = 22
    LiteGraph.NODE_TEXT_SIZE = 15
    // 连线宽度
    lg.LINK_WIDTH = 2.2
  }

  // 选区回调
  const origOnNodeSelected = canvas.onNodeSelected?.bind(canvas)
  canvas.onNodeSelected = (node: LGraphNodeClass) => {
    emit('nodeSelect', node)
    if (origOnNodeSelected) origOnNodeSelected(node)
  }

  const origOnNodeDeselected = canvas.onNodeDeselected?.bind(canvas)
  canvas.onNodeDeselected = (node: LGraphNodeClass) => {
    emit('nodeSelect', null)
    if (origOnNodeDeselected) origOnNodeDeselected(node)
  }

  // 图变更后通知父组件
  const origOnConnectionChange = (
    canvas as unknown as {
      onConnectionChange?: (...args: unknown[]) => void
    }
  ).onConnectionChange
  ;(canvas as unknown as { onConnectionChange?: (...args: unknown[]) => void }).onConnectionChange =
    (...args: unknown[]) => {
      emitChange()
      if (origOnConnectionChange) origOnConnectionChange(...args)
    }

  // 拖动过程中实时吸附 + 辅助线（LiteGraph 的 onNodeMoved 仅在 mouseup 触发，不跟手）
  const canvasAny = canvas as unknown as {
    processMouseMove?: (e: MouseEvent) => unknown
    processNodeSelected?: (node: LGraphNodeClass, e: MouseEvent) => void
    selectNode?: (node: LGraphNodeClass, addToCurrent?: boolean) => void
    node_dragged?: LGraphNodeClass | null
    selected_nodes?: Record<string, LGraphNodeClass>
    onNodeMoved?: (node: LGraphNodeClass) => void
    onDrawOverlay?: (ctx: CanvasRenderingContext2D) => void
    onDrawBackground?: (
      ctx: CanvasRenderingContext2D,
      visibleArea?: Float32Array | number[],
    ) => void
    convertOffsetToCanvas?: (pos: number[], out?: number[]) => number[]
    ds?: { offset: [number, number]; scale: number; visible_area?: Float32Array | number[] }
  }

  // ─── 多选拖拽修复 ─────────────────────────────────────────────────────────
  // 根因：LiteGraph 的 processMouseDown → processNodeSelected → selectNode(node, false)
  // 会 deselectAllNodes 清空多选，导致 processMouseMove 内置的多选拖循环只看到 1 个节点。
  // 修复：覆写 selectNode（processMouseDown 内部通过 this. 动态查找），
  // 当目标节点已属于多选且无修饰键时跳过 deselectAllNodes，让内置多选拖自然生效。
  // mouseup 时若鼠标未显著移动（纯点击）则恢复单选。
  let _multiSelectDownPos: [number, number] | null = null
  const DRAG_THRESHOLD = 4 // 像素阈值，小于此距离视为点击

  const origSelectNode = canvasAny.selectNode?.bind(canvas)
  if (origSelectNode && !props.readonly) {
    canvasAny.selectNode = function (node: LGraphNodeClass, addToCurrent?: boolean) {
      // 仅在非追加选择且节点已属于多选时跳过 deselection
      if (
        !addToCurrent &&
        node?.is_selected &&
        !(node as unknown as { _skipDeselect?: boolean })._skipDeselect
      ) {
        const selectedMap = canvasAny.selected_nodes ?? {}
        if (Object.keys(selectedMap).length > 1) {
          // 记录 mousedown 位置，mouseup 时判断是点击还是拖拽
          _multiSelectDownPos = _multiSelectDownPos ?? [0, 0]
          return // 跳过 deselectAllNodes，保持多选状态
        }
      }
      return origSelectNode(node, addToCurrent)
    }
  }

  // mousedown 时记录起始位置（capture 阶段，先于 LiteGraph 处理）
  _multiSelectMouseupRef = (e: MouseEvent) => {
    if (!_multiSelectDownPos) {
      return
    }
    const dx = Math.abs(e.clientX - _multiSelectDownPos[0])
    const dy = Math.abs(e.clientY - _multiSelectDownPos[1])
    _multiSelectDownPos = null
    // 鼠标移动 < 阈值 → 纯点击 → 恢复单选
    if (dx < DRAG_THRESHOLD && dy < DRAG_THRESHOLD) {
      const selectedMap = canvasAny.selected_nodes ?? {}
      const firstSelected = Object.values(selectedMap)[0]
      if (firstSelected) {
        // 用原始 selectNode 恢复单选，不经过覆写逻辑
        origSelectNode?.(firstSelected, false)
      }
    }
    // 鼠标移动 >= 阈值 → 拖拽 → 保持多选，不干预
  }

  // 用 capture 阶段 mousedown 记录起始位置
  _multiSelectMousedownRef = (e: MouseEvent) => {
    const selectedMap = canvasAny.selected_nodes ?? {}
    if (Object.keys(selectedMap).length > 1) {
      _multiSelectDownPos = [e.clientX, e.clientY]
    } else {
      _multiSelectDownPos = null
    }
  }
  canvasRef.value?.addEventListener('mousedown', _multiSelectMousedownRef, {
    capture: true,
    passive: true,
  })
  canvasRef.value?.addEventListener('mouseup', _multiSelectMouseupRef)

  // 实时吸附 + 辅助线：用 capture 阶段 mousemove 监听
  // （processMouseMove 覆写无效，因为 LiteGraph 用 .bind() 绑定 DOM 监听器）
  _portMousemoveHandlerRef = (e: MouseEvent) => {
    if (!canvasInstance.value) return
    const target = e.target as HTMLElement | null
    if (target?.closest?.('.workflow-minimap')) {
      hidePortTooltip()
      return
    }
    const dragged = canvasAny.node_dragged
    if (dragged) {
      // 拖动中：实时吸附 + 辅助线
      if (!props.readonly) {
        applySnapWhileDragging(dragged, canvasAny.selected_nodes ?? { [dragged.id]: dragged })
        computeAlignmentGuides(dragged)
        canvas.setDirty(true, true)
      }
      hidePortTooltip()
      return
    }
    // 非拖动：更新端口悬停提示
    updatePortTooltipFromEvent(e, canvasInstance.value)
  }
  const tipHost = canvasContainerRef.value ?? canvasRef.value
  if (tipHost) {
    tipHost.addEventListener('mousemove', _portMousemoveHandlerRef as EventListener, {
      passive: true,
      capture: true,
    })
    tipHost.addEventListener('mouseleave', hidePortTooltip)
  }

  const origOnNodeMoved = canvasAny.onNodeMoved
  canvasAny.onNodeMoved = (node: LGraphNodeClass) => {
    // 松手时再做一次硬吸附，保证落点落在网格/对齐线上；辅助线仅拖动中显示
    // applySnapWhileDragging 会将 snap delta 同步给所有选中节点
    applySnapWhileDragging(node, canvasAny.selected_nodes ?? { [node.id]: node }, true)
    alignmentGuides.value = []
    emitChange()
    if (origOnNodeMoved) origOnNodeMoved(node)
  }

  // 网格背景：先铺主题清屏色，再在 graph 坐标系中绘制网格
  canvasAny.onDrawBackground = (ctx: CanvasRenderingContext2D) => {
    const area = canvasAny.ds?.visible_area
    if (!area) return
    const left = Number(area[0])
    const top = Number(area[1])
    const width = Number(area[2])
    const height = Number(area[3])
    const scale = canvasAny.ds?.scale ?? 1
    ctx.save()
    // 保证浅/深主题背景真正切换（不只依赖 LiteGraph clear）
    ctx.fillStyle = getCanvasClearColor()
    ctx.fillRect(left - 2, top - 2, width + 4, height + 4)
    // 缩放很小时降采样网格密度，避免线条过密
    const step = scale < 0.5 ? SNAP_GRID_SIZE * 2 : SNAP_GRID_SIZE
    const startX = Math.floor(left / step) * step
    const startY = Math.floor(top / step) * step
    const gridColors = getGridColors()
    ctx.strokeStyle = gridColors.minor
    ctx.lineWidth = 1 / Math.max(scale, 0.01)
    ctx.beginPath()
    for (let x = startX; x <= left + width; x += step) {
      ctx.moveTo(x, top)
      ctx.lineTo(x, top + height)
    }
    for (let y = startY; y <= top + height; y += step) {
      ctx.moveTo(left, y)
      ctx.lineTo(left + width, y)
    }
    ctx.stroke()
    // 每 5 格加粗
    const major = step * 5
    const majorStartX = Math.floor(left / major) * major
    const majorStartY = Math.floor(top / major) * major
    ctx.strokeStyle = gridColors.major
    ctx.beginPath()
    for (let x = majorStartX; x <= left + width; x += major) {
      ctx.moveTo(x, top)
      ctx.lineTo(x, top + height)
    }
    for (let y = majorStartY; y <= top + height; y += major) {
      ctx.moveTo(left, y)
      ctx.lineTo(left + width, y)
    }
    ctx.stroke()
    ctx.restore()
  }

  // 对齐辅助线：onDrawOverlay 在 transform restore 后调用，必须用 convertOffsetToCanvas
  canvasAny.onDrawOverlay = (ctx: CanvasRenderingContext2D) => {
    if (!alignmentGuides.value.length) return
    const toScreen = (x: number, y: number): [number, number] => {
      if (canvasAny.convertOffsetToCanvas) {
        const out = canvasAny.convertOffsetToCanvas([x, y])
        return [out[0], out[1]]
      }
      const ds = canvasAny.ds
      if (!ds) return [x, y]
      // LiteGraph: screen = (graph + offset) * scale
      return [(x + ds.offset[0]) * ds.scale, (y + ds.offset[1]) * ds.scale]
    }
    ctx.save()
    ctx.strokeStyle = resolveCanvasColor('--accent', '#5ad5ff')
    ctx.globalAlpha = 0.5
    ctx.lineWidth = 1
    ctx.setLineDash([4, 6])
    for (const g of alignmentGuides.value) {
      ctx.beginPath()
      if (g.orientation === 'vertical') {
        const [x1, y1] = toScreen(g.pos, g.start)
        const [, y2] = toScreen(g.pos, g.end)
        ctx.moveTo(x1, y1)
        ctx.lineTo(x1, y2)
      } else {
        const [x1, y1] = toScreen(g.start, g.pos)
        const [x2] = toScreen(g.end, g.pos)
        ctx.moveTo(x1, y1)
        ctx.lineTo(x2, y1)
      }
      ctx.stroke()
    }
    ctx.restore()
  }

  // 松手即清除辅助线（仅拖动过程中显示）
  if (canvasRef.value) {
    _mouseupHandlerRef = () => {
      if (alignmentGuides.value.length) {
        alignmentGuides.value = []
        canvas.setDirty(true, true)
      }
    }
    canvasRef.value.addEventListener('mouseup', _mouseupHandlerRef)
    canvasRef.value.addEventListener('mouseleave', hidePortTooltip)
  }

  // 键盘快捷键：Delete 删除 + Ctrl+A/C/V/D 编辑快捷键 + Escape 取消选中
  if (!props.readonly) {
    asLGraphCanvasRuntime(canvas).bindKey = undefined // 不覆盖 LiteGraph 默认绑定
    const canvasEl = canvasRef.value
    if (canvasEl) {
      const keydownHandler = (e: KeyboardEvent) => {
        // 输入框/文本域/下拉框中不拦截快捷键
        const target = e.target as HTMLElement | null
        if (
          target &&
          (target.tagName === 'INPUT' ||
            target.tagName === 'TEXTAREA' ||
            target.tagName === 'SELECT' ||
            target.isContentEditable)
        ) {
          return
        }
        const mod = e.ctrlKey || e.metaKey
        const key = e.key.toLowerCase()
        if (mod && key === 'a') {
          e.preventDefault()
          selectAllNodes()
        } else if (mod && key === 'c') {
          e.preventDefault()
          copySelectedNodes()
        } else if (mod && key === 'v') {
          e.preventDefault()
          pasteNodes()
        } else if (mod && key === 'd') {
          e.preventDefault()
          duplicateSelectedNodes()
        } else if (e.key === 'Escape') {
          // 先关掉 LiteGraph 浮动菜单/输入框，再清选中
          disposeLiteGraphFloatingUi()
          clearAlignmentGuides()
          hidePortTooltip()
          if (graphInstance.value) {
            for (const n of getGraphNodes(graphInstance.value)) {
              n.selected = false
            }
            canvas.setDirty(true, true)
          }
        }
      }
      canvasEl.addEventListener('keydown', keydownHandler)
      _keydownHandlerRef = keydownHandler
    }
  }

  // 启用画布交互：左键空白框选 + 右键空白平移 + 右键节点菜单
  enableCanvasInteractions(canvas)

  // 将 graphdialog 挪到 body + fixed，避免被 canvas overflow 裁切；Esc/点外关闭
  setupLiteGraphFloatingUiGuards()

  // 监听节点删除：触发 emitChange 通知父组件
  // LiteGraph 的 graph.remove(node) 会自动清理该节点相关的所有连线
  // （L1573-L1620：遍历 inputs/outputs 调用 disconnectInput/disconnectOutput）
  // 删除完成后 onNodeRemoved 被调用，再触发 afterChange + change
  if (graphInstance.value) {
    const graphAny = graphInstance.value as unknown as {
      onNodeRemoved?: (node: LGraphNodeClass) => void
    }
    const origOnNodeRemoved = graphAny.onNodeRemoved
    graphAny.onNodeRemoved = (node: LGraphNodeClass) => {
      // 通知父组件当前选中节点可能已被删除
      // 父组件会清空 selectedNode 状态
      emit('nodeSelect', null)
      emitChange()
      if (origOnNodeRemoved) origOnNodeRemoved(node)
    }
  }
}

/**
 * 启用画布交互（ComfyUI 风格改进版）：
 *   - 左键空白区域拖动 → 框选多节点
 *   - 左键节点 → 选中/拖动节点
 *   - 中键拖动 → 平移视角
 *   - 右键 → 上下文菜单（节点菜单 / 画布菜单）
 *
 * 实现方式：monkey-patch LGraphCanvas._mousedown_callback
 *   1. 保持 allow_dragcanvas=true（LiteGraph processMouseWheel 依赖此属性，设 false 会禁用滚轮缩放）
 *   2. 左键空白：强制 ctrlKey=true 让 LiteGraph 进入 dragging_rectangle 框选模式（skip_action 阻止平移）；
 *      hack 失效时手动设置 dragging_rectangle 并清除 dragging_canvas 确保 box-selection 优先
 *   3. 中键空白：preventDefault + 强制 dragging_canvas=true 启动平移
 *   4. 右键：不干预，让 LiteGraph 原生 processContextMenu 处理（画布菜单 / 节点菜单）
 */
function enableCanvasInteractions(canvas: LGraphCanvasClass) {
  const canvasAny = canvas as unknown as {
    _mousedown_callback?: (e: MouseEvent) => void
    dragging_canvas?: boolean
    dragging_rectangle?: number[] | null
    allow_dragcanvas?: boolean
  }

  // 注意：不禁用 allow_dragcanvas，因为 LiteGraph 的 processMouseWheel 依赖此属性，
  // 设为 false 会导致滚轮缩放失效。左键平移已通过 ctrlKey hack 阻止（框选模式 skip_action）。

  const origCallback = canvasAny._mousedown_callback
  if (!origCallback || !canvasRef.value) return

  const wrappedCallback = (e: MouseEvent) => {
    const isLeftClick = e.button === 0
    const isMiddleClick = e.button === 1
    const onEmpty = isPointOnEmptyArea(e, canvas)

    // 点击空白：立即清除对齐辅助线
    if (onEmpty) {
      clearAlignmentGuides()
      hidePortTooltip()
    }

    // 中键：阻止浏览器自动滚动，启动平移
    if (isMiddleClick) {
      e.preventDefault()
      if (onEmpty) {
        origCallback(e)
        canvasAny.dragging_canvas = true
        return
      }
    }

    // 左键空白 → 框选：让 LiteGraph 进入 dragging_rectangle 模式
    const wantBoxSelection = isLeftClick && shouldTriggerBoxSelection(e, canvas)
    if (wantBoxSelection) {
      try {
        Object.defineProperty(e, 'ctrlKey', { get: () => true, configurable: true })
      } catch {
        // monkey-patch 失败时，手动初始化框选矩形
        const rect = canvasRef.value?.getBoundingClientRect()
        if (rect) {
          const ds = (canvas as unknown as { ds?: { offset: [number, number]; scale: number } }).ds
          if (ds) {
            const cx = (e.clientX - rect.left) / ds.scale - ds.offset[0]
            const cy = (e.clientY - rect.top) / ds.scale - ds.offset[1]
            canvasAny.dragging_rectangle = [cx, cy, 0, 0]
          }
        }
      }
    }

    const result = origCallback(e)

    // 框选保底：如果 ctrlKey hack 成功，LiteGraph 已设 dragging_rectangle 且 skip_action=true；
    // 如果 hack 失效，LiteGraph 可能同时设了 dragging_canvas 和未设 dragging_rectangle。
    // 此处确保 dragging_rectangle 存在且 dragging_canvas 被清除，让 processMouseMove 优先走框选分支。
    if (wantBoxSelection) {
      if (!canvasAny.dragging_rectangle) {
        const rect = canvasRef.value?.getBoundingClientRect()
        if (rect) {
          const ds = (canvas as unknown as { ds?: { offset: [number, number]; scale: number } }).ds
          if (ds) {
            const cx = (e.clientX - rect.left) / ds.scale - ds.offset[0]
            const cy = (e.clientY - rect.top) / ds.scale - ds.offset[1]
            canvasAny.dragging_rectangle = [cx, cy, 0, 0]
          }
        }
      }
      // 清除平移标志，确保框选优先于平移
      canvasAny.dragging_canvas = false
    }

    // 右键：不干预，LiteGraph 原生 processMouseDown 会调用 processContextMenu 显示菜单

    return result
  }

  canvasAny._mousedown_callback = wrappedCallback
  // 重新注册 listener：移除原 callback，添加 wrapped 版本（capture=true 与 LiteGraph 一致）
  canvasRef.value.removeEventListener('mousedown', origCallback, true)
  canvasRef.value.addEventListener('mousedown', wrappedCallback, true)

  // 双保险：容器 capture 阶段也清线（避免 LiteGraph 绑定方式变化导致 wrap 失效）
  const container = canvasContainerRef.value
  if (container) {
    const onPointerDownCapture = (e: Event) => {
      const me = e as MouseEvent
      if (me.button != null && me.button !== 0 && me.button !== 1 && me.button !== 2) return
      // 点在 minimap 上不处理
      const target = e.target as HTMLElement | null
      if (target?.closest?.('.workflow-minimap')) return
      if (isPointOnEmptyArea(me, canvas)) {
        clearAlignmentGuides()
        hidePortTooltip()
      }
    }
    container.addEventListener('mousedown', onPointerDownCapture, true)
    ;(container as unknown as { __clearGuidesHandler?: (e: Event) => void }).__clearGuidesHandler =
      onPointerDownCapture
  }
}

/**
 * 判断当前 mousedown 事件是否应触发框选模式。
 * 条件：
 *   1. 左键（button === 0）
 *   2. 无任何修饰键
 *   3. 非只读模式
 *   4. 点击位置不在任何节点上（getNodeOnPos 返回 null）
 *   5. canvas 状态正常（已初始化、有 graph）
 */
function shouldTriggerBoxSelection(e: MouseEvent, canvas: LGraphCanvasClass): boolean {
  if (e.button !== 0) return false
  if (e.ctrlKey || e.shiftKey || e.altKey || e.metaKey) return false
  if (props.readonly) return false
  return isPointOnEmptyArea(e, canvas)
}

/**
 * 判断鼠标点击位置是否在空白区域（不在任何节点上）。
 * 共用工具函数，供框选判断使用。
 */
function isPointOnEmptyArea(e: MouseEvent, canvas: LGraphCanvasClass): boolean {
  if (!graphInstance.value) return false
  const canvasEl = canvasRef.value
  if (!canvasEl) return false

  // 将屏幕坐标转换为 graph 坐标（与 LiteGraph 一致：graph = screen/scale - offset）
  const rect = canvasEl.getBoundingClientRect()
  const x = e.clientX - rect.left
  const y = e.clientY - rect.top
  const ds = (canvas as unknown as { ds?: { offset: [number, number]; scale: number } }).ds
  if (!ds || !ds.scale) return false
  const canvasX = x / ds.scale - ds.offset[0]
  const canvasY = y / ds.scale - ds.offset[1]

  // 检查是否点中节点
  const graphAny = graphInstance.value as unknown as {
    getNodeOnPos?: (x: number, y: number, nodes?: LGraphNodeClass[]) => LGraphNodeClass | null
  }
  const visibleNodes = (canvas as unknown as { visible_nodes?: LGraphNodeClass[] }).visible_nodes
  const node = graphAny.getNodeOnPos?.(canvasX, canvasY, visibleNodes)
  // 点中节点：让 LiteGraph 处理（节点拖动/选中/右键菜单）
  if (node) return false

  return true
}

// P1-5: drawMinimap / bindMinimapInteractions / syncMinimapToViewport 已移入 useMinimap composable

// P1-5: hidePortTooltip / resolveSuggestTitles / clientToGraphCoords / updatePortTooltipFromEvent 已移入 usePortTooltip composable

// P1-5: snapToGrid / nodeBounds / applySnapWhileDragging / computeAlignmentGuides 已移入 useAlignmentGuides composable

// P1-5: selectAllNodes / copySelectedNodes / pasteNodes / duplicateSelectedNodes / loadDefinitionIntoGraph 已移入 useNodeOperations composable

// P1-5: _emitChangeScheduled + emitChange 重复定义已移除（使用顶部 composable 版本）

// P1-5: getSerializedGraph / clearGraph / arrangeNodes / fitView / addNodeByType / removeNode 已移入 useNodeOperations composable

/** 关闭编辑器时清理挂到 body / canvas 容器的 LiteGraph 浮动 UI，避免输入框泄漏到主界面 */
function disposeLiteGraphFloatingUi() {
  const canvas = canvasInstance.value as unknown as {
    search_box?: { close?: () => void } | null
    prompt_box?: { close?: () => void } | null
    closePanels?: () => void
  } | null

  try {
    canvas?.search_box?.close?.()
  } catch {
    /* ignore */
  }
  try {
    canvas?.prompt_box?.close?.()
  } catch {
    /* ignore */
  }
  try {
    canvas?.closePanels?.()
  } catch {
    /* ignore */
  }
  try {
    ;(
      LiteGraph as unknown as { closeAllContextMenus?: (w?: Window) => void }
    ).closeAllContextMenus?.(window)
  } catch {
    /* ignore */
  }

  // prompt / createDialog 挂在 canvas.parentNode；搜索框/菜单挂在 document.body
  canvasContainerRef.value
    ?.querySelectorAll(
      '.graphdialog, .litegraph.dialog, .litegraph.litesearchbox, .litegraph.litecontextmenu',
    )
    .forEach((el) => {
      try {
        el.parentNode?.removeChild(el)
      } catch {
        /* ignore */
      }
    })

  document
    .querySelectorAll(
      '.graphdialog, .litegraph.graphdialog, .litegraph.litesearchbox, .litegraph.litecontextmenu, .litegraph.dialog, #node-panel, #option-panel',
    )
    .forEach((el) => {
      try {
        el.parentNode?.removeChild(el)
      } catch {
        /* ignore */
      }
    })

  if (document.body.style.overflow === 'hidden') {
    document.body.style.overflow = ''
  }

  // 避免关闭后全局仍指向已销毁的 canvas
  const LGC = LGraphCanvas as unknown as { active_canvas?: unknown }
  if (LGC.active_canvas === canvasInstance.value) {
    LGC.active_canvas = null
  }
}

defineExpose({
  getSerializedGraph,
  clearGraph,
  arrangeNodes,
  fitView,
  addNodeByType,
  removeNode,
  applyBoundMainTimeline,
  isReady,
  disposeLiteGraphFloatingUi,
})

// ─── 生命周期 ───────────────────────────────────────────────────────────────

onMounted(() => {
  // 等待 DOM 渲染完成
  requestAnimationFrame(() => {
    initializeCanvas()
  })
})

onBeforeUnmount(() => {
  disposeLiteGraphFloatingUi()
  if (_floatingUiObserver) {
    _floatingUiObserver.disconnect()
    _floatingUiObserver = null
  }
  if (_floatingPointerDownRef) {
    document.removeEventListener('pointerdown', _floatingPointerDownRef, true)
    _floatingPointerDownRef = null
  }
  if (_globalEscRef) {
    document.removeEventListener('keydown', _globalEscRef, true)
    _globalEscRef = null
  }
  if (resizeObserver) {
    resizeObserver.disconnect()
    resizeObserver = null
  }
  // P1-5: 清理 minimap 定时器 + 事件监听（委托 composable）
  disposeMinimap()
  // 清理主画布事件监听
  const canvasEl = canvasRef.value
  const tipHost = canvasContainerRef.value ?? canvasEl
  if (tipHost) {
    if (_portMousemoveHandlerRef) {
      tipHost.removeEventListener('mousemove', _portMousemoveHandlerRef as EventListener, true)
      _portMousemoveHandlerRef = null
    }
    tipHost.removeEventListener('mouseleave', hidePortTooltip)
  }
  const container = canvasContainerRef.value as
    | (HTMLDivElement & {
        __clearGuidesHandler?: (e: Event) => void
      })
    | null
  if (container?.__clearGuidesHandler) {
    container.removeEventListener('mousedown', container.__clearGuidesHandler, true)
    delete container.__clearGuidesHandler
  }
  if (canvasEl) {
    if (_keydownHandlerRef) {
      canvasEl.removeEventListener('keydown', _keydownHandlerRef)
      _keydownHandlerRef = null
    }
    if (_mouseupHandlerRef) {
      canvasEl.removeEventListener('mouseup', _mouseupHandlerRef)
      _mouseupHandlerRef = null
    }
    // 清理多选拖拽监听器
    if (_multiSelectMousedownRef) {
      canvasEl.removeEventListener('mousedown', _multiSelectMousedownRef, true)
      _multiSelectMousedownRef = null
    }
    if (_multiSelectMouseupRef) {
      canvasEl.removeEventListener('mouseup', _multiSelectMouseupRef)
      _multiSelectMouseupRef = null
    }
    canvasEl.removeEventListener('mouseleave', hidePortTooltip)
  }
  hidePortTooltip()
  // 清空对齐辅助线状态
  alignmentGuides.value = []
  // 清空剪贴板
  // P1-5: _clipboard 已移入 useNodeOperations composable 内部管理
  if (graphInstance.value) {
    try {
      graphInstance.value.stop()
    } catch {
      // ignore
    }
  }
  if (canvasInstance.value) {
    try {
      canvasInstance.value.clear()
    } catch {
      // ignore
    }
  }
  graphInstance.value = null
  canvasInstance.value = null
})

// ─── 监听 props 变化 ────────────────────────────────────────────────────────

// 切换工作流定义时重新加载
watch(
  () => props.definition?.workflow_id,
  (newId, oldId) => {
    if (!isReady.value || !graphInstance.value) return
    if (newId === oldId) return
    if (props.definition) {
      graphInstance.value.clear()
      loadDefinitionIntoGraph(props.definition, graphInstance.value)
    }
  },
)

// 切换只读模式时更新 canvas 配置
watch(
  () => props.readonly,
  (readonly) => {
    if (!canvasInstance.value) return
    // 只读模式仅禁止重连连线，read_only 保持 false 以允许拖动/选中/缩放
    const canvasAny = canvasInstance.value as unknown as { read_only: boolean }
    canvasAny.read_only = false
    canvasInstance.value.allow_dragnodes = true
    canvasInstance.value.allow_interaction = true
    canvasInstance.value.allow_reconnect_links = !readonly
  },
)

// 节点模板异步到达或热更新时重新注册类型，并给已有节点补齐端口
watch(
  () => props.nodeTemplates.length,
  (len) => {
    if (len <= 0) return
    registerWorkflowNodeTypes(
      props.nodeTemplates.map((t) => ({
        type: t.type,
        title: t.title,
        engine: t.engine,
        inputs: t.inputs,
        outputs: t.outputs,
        params: t.params,
      })),
    )
    if (graphInstance.value) {
      syncGraphSlotsWithTemplates(
        graphInstance.value,
        props.nodeTemplates.map((t) => ({
          type: t.type,
          inputs: t.inputs,
          outputs: t.outputs,
          params: t.params,
        })),
      )
      canvasInstance.value?.setDirty(true, true)
    }
  },
)
</script>

<template>
  <div ref="canvasContainerRef" class="workflow-canvas-container">
    <canvas ref="canvasRef" class="workflow-canvas" tabindex="-1" />
    <div v-if="errorMsg" class="canvas-error">
      <AlertTriangle :size="14" class="error-icon" aria-hidden="true" />
      <span class="error-text">画布初始化失败：{{ errorMsg }}</span>
    </div>
    <div v-else-if="!isReady" class="canvas-loading">
      <InlineLoader label="正在加载画布..." />
    </div>

    <canvas ref="minimapRef" class="workflow-minimap" width="160" height="100" aria-hidden="true" />
  </div>

  <!-- Teleport 到 body，避免被 editor-canvas-area 的 overflow:hidden 裁剪 -->
  <Teleport to="body">
    <Transition name="cgda-pop">
      <div
        v-if="portTooltip.visible && portTooltip.model"
        class="wf-port-tooltip"
        :class="`tone-${portTooltip.model.tone}`"
        :style="portTooltipStyle"
        role="tooltip"
      >
        <div class="port-tip-head">
          <span class="port-tip-badge">{{ portTooltip.model.badge }}</span>
          <span class="port-tip-title">{{ portTooltip.model.title }}</span>
          <span class="port-tip-type">{{ portTooltip.model.typeLabel }}</span>
        </div>
        <p
          v-for="(para, idx) in portTooltip.model.body.split('\n\n')"
          :key="`p-${idx}`"
          class="port-tip-body"
        >
          {{ para }}
        </p>
        <ul v-if="portTooltip.model.tips.length" class="port-tip-tips">
          <li v-for="(tip, idx) in portTooltip.model.tips" :key="`t-${idx}`">{{ tip }}</li>
        </ul>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.workflow-canvas-container {
  position: relative;
  width: 100%;
  height: 100%;
  min-height: 400px;
  background: var(--surface-base);
  overflow: hidden;
}

.workflow-canvas {
  width: 100%;
  height: 100%;
  display: block;
  outline: none;
}

.canvas-error,
.canvas-loading {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 0.6rem;
  color: var(--text-muted);
  font-size: var(--font-size-caption);
  background: color-mix(in srgb, var(--surface-2) 82%, transparent);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
  /* 加载态挡交互；就绪后节点卸载，不会残留 */
  pointer-events: auto;
  z-index: 2;
}

.canvas-error {
  color: var(--danger);
}

.error-icon {
  font-size: 1.6rem;
  color: var(--danger);
}

/* ── 连接点悬停提示（Teleport 到 body，需 :global）──────────────── */
:global(.wf-port-tooltip) {
  position: fixed;
  z-index: 10050;
  width: min(280px, calc(100vw - 24px));
  max-height: min(280px, 45vh);
  overflow: auto;
  padding: 0.55rem 0.65rem 0.6rem;
  border-radius: 0.5rem;
  border: 1px solid var(--border-strong);
  background: linear-gradient(165deg, var(--surface-2), var(--surface-2));
  box-shadow:
    0 10px 28px rgba(0, 0, 0, 0.45),
    0 0 0 1px var(--surface-hover) inset;
  pointer-events: none;
  color: var(--text-primary);
}

:global(.wf-port-tooltip .port-tip-head) {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  margin-bottom: 0.4rem;
}

:global(.wf-port-tooltip .port-tip-badge) {
  flex-shrink: 0;
  padding: 0.08rem 0.32rem;
  border-radius: 0.28rem;
  font-size: var(--font-size-caption);
  font-weight: 600;
  letter-spacing: 0.02em;
  color: var(--surface-sunken);
  background: var(--tip-accent, var(--accent));
}

:global(.wf-port-tooltip .port-tip-title) {
  flex: 1;
  min-width: 0;
  font-size: var(--font-size-caption);
  font-weight: 650;
  color: var(--text-strong);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

:global(.wf-port-tooltip .port-tip-type) {
  flex-shrink: 0;
  font-size: var(--font-size-caption);
  color: var(--text-primary);
}

:global(.wf-port-tooltip .port-tip-body) {
  margin: 0 0 0.35rem;
  font-size: var(--font-size-caption);
  line-height: 1.45;
  color: var(--text-muted);
  white-space: pre-wrap;
}

:global(.wf-port-tooltip .port-tip-tips) {
  margin: 0.2rem 0 0;
  padding: 0.35rem 0 0 1rem;
  border-top: 1px solid var(--border-default);
  list-style: disc;
}

:global(.wf-port-tooltip .port-tip-tips li) {
  margin: 0.12rem 0;
  font-size: var(--font-size-caption);
  line-height: 1.4;
  color: var(--text-secondary);
}

/* port-tip 入场改用全局 cgda-pop（motion.css） */

/* ── minimap 小地图 ────────────────────────────────────────────────── */
.workflow-minimap {
  position: absolute;
  right: 0.6rem;
  bottom: 0.6rem;
  width: 160px;
  height: 100px;
  border: 1px solid var(--border-strong);
  border-radius: 0.32rem;
  background: var(--surface-1);
  pointer-events: auto;
  cursor: pointer;
  z-index: 5;
  transition:
    border-color 0.2s ease,
    box-shadow 0.2s ease,
    opacity 0.2s ease;
  opacity: 0.78;
}

.workflow-minimap:hover {
  border-color: var(--border-accent);
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.2);
  opacity: 1;
}

@media (prefers-reduced-motion: reduce) {
  .workflow-minimap {
    transition: none;
    opacity: 1;
  }
}
</style>
