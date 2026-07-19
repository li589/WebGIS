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
import { computed, onMounted, onBeforeUnmount, ref, shallowRef, watch } from 'vue'
import {
  LGraph,
  LGraphCanvas,
  LiteGraph,
  registerWorkflowNodeTypes,
  workflowDefinitionToGraphData,
  graphDataToWorkflowNodes,
  syncGraphSlotsWithTemplates,
  getPortColor,
  suggestConnectorsForPortType,
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
import { buildPortTooltip, type PortTooltipModel } from './port-tooltip'

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

// 对齐辅助线状态（拖动节点时显示）
interface AlignmentGuide {
  orientation: 'vertical' | 'horizontal'
  pos: number
  start: number
  end: number
}
const alignmentGuides = ref<AlignmentGuide[]>([])
/** 吸附网格边长（graph 坐标） */
const SNAP_GRID_SIZE = 20
/** 边缘对齐吸附阈值（graph 坐标） */
const ALIGN_SNAP_THRESHOLD = 8
/** 拖动过程中是否正在吸附（避免重复 emit） */
let _dragSnapActive = false

/** 连接点悬停提示 */
const portTooltip = ref<{
  visible: boolean
  x: number
  y: number
  model: PortTooltipModel | null
  accent: string
}>({ visible: false, x: 0, y: 0, model: null, accent: '#5ad5ff' })
let _portTooltipKey = ''
/** 独立 mousemove 监听（LiteGraph 可能 bind 了 processMouseMove，覆写方法不可靠） */
let _portMousemoveHandlerRef: ((e: MouseEvent) => void) | null = null

const portTooltipStyle = computed(() => {
  // fixed 定位到视口，避开父级 overflow:hidden / 层叠裁剪
  const pad = 12
  const tipW = 300
  const tipH = 260
  const x = Math.max(pad, Math.min(portTooltip.value.x + 14, window.innerWidth - tipW - pad))
  const y = Math.max(pad, Math.min(portTooltip.value.y + 14, window.innerHeight - tipH - pad))
  return {
    left: `${x}px`,
    top: `${y}px`,
    '--tip-accent': portTooltip.value.accent,
  }
})

// minimap 定时刷新句柄
let _minimapTimer: ReturnType<typeof setInterval> | null = null

// 模块级剪贴板（Ctrl+C/V 用，仅当前会话有效）
interface ClipboardItem {
  type: string
  pos: [number, number]
  properties: Record<string, unknown>
  title?: string
}
let _clipboard: ClipboardItem[] = []

// keydown 监听句柄（组件销毁时需移除）
let _keydownHandlerRef: ((e: KeyboardEvent) => void) | null = null

// mouseup 监听句柄（用于清空对齐辅助线）
let _mouseupHandlerRef: (() => void) | null = null

// minimap mousedown 监听句柄（用于点击/拖动同步主视口）
let _minimapMousedownHandlerRef: ((e: MouseEvent) => void) | null = null
let _minimapMouseupHandlerRef: (() => void) | null = null
let _minimapMousemoveHandlerRef: ((e: MouseEvent) => void) | null = null

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

    // 启动 minimap 定时刷新（5 FPS，节流避免阻塞主画布）
    _minimapTimer = setInterval(drawMinimap, 200)

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

  // 主题色适配深色 UI
  if (LiteGraph) {
    // 节点默认颜色
    LiteGraph.NODE_DEFAULT_COLOR = '#1a2740'
    LiteGraph.NODE_DEFAULT_BGCOLOR = '#0f1828'
    LiteGraph.NODE_DEFAULT_BOXCOLOR = '#5ad5ff'
    LiteGraph.NODE_DEFAULT_SHAPE = 'round'
    LiteGraph.NODE_TITLE_COLOR = '#d8e6f5'
    LiteGraph.NODE_TEXT_COLOR = '#c4d6e8'
    LiteGraph.NODE_SELECTED_TITLE_COLOR = '#ffb84d'
    LiteGraph.NODE_BOX_OUTLINE_COLOR = '#5ad5ff'
    // 连线颜色 — 不同数据类型不同颜色
    LiteGraph.LINK_COLOR = '#5ad5ff'           // 默认（青色）
    LiteGraph.CONNECTING_LINK_COLOR = '#ffb84d' // 正在连接（橙色）
    LiteGraph.EVENT_LINK_COLOR = '#78ffa0'      // 事件类型（绿色）
    // 标题栏高度
    LiteGraph.NODE_TITLE_HEIGHT = 22
    LiteGraph.NODE_SLOT_HEIGHT = 20
    LiteGraph.NODE_WIDGET_HEIGHT = 20
    // 连线宽度
    LiteGraph.LINK_WIDTH = 2.2
    // 鼠标悬停连接线时的高亮颜色（降级方案：依赖 LiteGraph 内置 hover 绘制）
    LiteGraph.LINK_HOVER_COLOR = '#ffd38a'
  }

  // 选区回调
  const origOnNodeSelected = canvas.onNodeSelected?.bind(canvas)
  canvas.onNodeSelected = (node: LGraphNodeClass) => {
    emit('nodeSelect', node)
    if (origOnNodeSelected) origOnNodeSelected(node)
  }

  const origOnNodeDeselected = canvas.onNodeDeselected?.bind(canvas)
  canvas.onNodeDeselected = () => {
    emit('nodeSelect', null)
    if (origOnNodeDeselected) origOnNodeDeselected()
  }

  // 图变更后通知父组件
  const origOnConnectionChange = (canvas as unknown as {
    onConnectionChange?: (...args: unknown[]) => void
  }).onConnectionChange
  ;(canvas as unknown as { onConnectionChange?: (...args: unknown[]) => void }).onConnectionChange = (
    ...args: unknown[]
  ) => {
    emitChange()
    if (origOnConnectionChange) origOnConnectionChange(...args)
  }

  // 拖动过程中实时吸附 + 辅助线（LiteGraph 的 onNodeMoved 仅在 mouseup 触发，不跟手）
  const canvasAny = canvas as unknown as {
    processMouseMove?: (e: MouseEvent) => unknown
    node_dragged?: LGraphNodeClass | null
    selected_nodes?: Record<string, LGraphNodeClass>
    onNodeMoved?: (node: LGraphNodeClass) => void
    onDrawOverlay?: (ctx: CanvasRenderingContext2D) => void
    onDrawBackground?: (ctx: CanvasRenderingContext2D, visibleArea?: Float32Array | number[]) => void
    convertOffsetToCanvas?: (pos: number[], out?: number[]) => number[]
    ds?: { offset: [number, number]; scale: number; visible_area?: Float32Array | number[] }
  }
  const origProcessMouseMove = canvasAny.processMouseMove?.bind(canvas)
  if (origProcessMouseMove) {
    canvasAny.processMouseMove = (e: MouseEvent) => {
      const result = origProcessMouseMove(e)
      const dragged = canvasAny.node_dragged
      if (dragged && !props.readonly) {
        _dragSnapActive = true
        applySnapWhileDragging(dragged, canvasAny.selected_nodes ?? { [dragged.id]: dragged })
        computeAlignmentGuides(dragged)
        canvas.setDirty(true, true)
        hidePortTooltip()
      }
      return result
    }
  }

  // 连接点悬停：挂在容器 capture 上（LiteGraph 的 processMouseMove 已被 bind，覆写方法无效）
  const tipHost = canvasContainerRef.value ?? canvasRef.value
  if (tipHost) {
    _portMousemoveHandlerRef = (e: MouseEvent) => {
      if (!canvasInstance.value) return
      const target = e.target as HTMLElement | null
      if (target?.closest?.('.workflow-minimap')) {
        hidePortTooltip()
        return
      }
      const dragged = (canvasInstance.value as unknown as { node_dragged?: LGraphNodeClass | null }).node_dragged
      if (dragged) {
        hidePortTooltip()
        return
      }
      updatePortTooltipFromEvent(e, canvasInstance.value)
    }
    tipHost.addEventListener('mousemove', _portMousemoveHandlerRef, { passive: true, capture: true })
    tipHost.addEventListener('mouseleave', hidePortTooltip)
  }

  const origOnNodeMoved = canvasAny.onNodeMoved
  canvasAny.onNodeMoved = (node: LGraphNodeClass) => {
    // 松手时再做一次硬吸附，保证落点落在网格/对齐线上；辅助线仅拖动中显示
    applySnapWhileDragging(node, canvasAny.selected_nodes ?? { [node.id]: node }, true)
    alignmentGuides.value = []
    emitChange()
    _dragSnapActive = false
    if (origOnNodeMoved) origOnNodeMoved(node)
  }

  // 网格背景：在 graph 坐标系中绘制，缩放后位置始终正确
  canvasAny.onDrawBackground = (ctx: CanvasRenderingContext2D) => {
    const area = canvasAny.ds?.visible_area
    if (!area) return
    const left = Number(area[0])
    const top = Number(area[1])
    const width = Number(area[2])
    const height = Number(area[3])
    const scale = canvasAny.ds?.scale ?? 1
    // 缩放很小时降采样网格密度，避免线条过密
    const step = scale < 0.5 ? SNAP_GRID_SIZE * 2 : SNAP_GRID_SIZE
    const startX = Math.floor(left / step) * step
    const startY = Math.floor(top / step) * step
    ctx.save()
    ctx.strokeStyle = 'rgba(90, 180, 255, 0.08)'
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
    ctx.strokeStyle = 'rgba(90, 180, 255, 0.16)'
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
    ctx.strokeStyle = 'rgba(160, 200, 230, 0.32)'
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
      _dragSnapActive = false
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
    canvas.bindKey = undefined  // 不覆盖 LiteGraph 默认绑定
    const canvasEl = canvasRef.value
    if (canvasEl) {
      const keydownHandler = (e: KeyboardEvent) => {
        // 输入框/文本域/下拉框中不拦截快捷键
        const target = e.target as HTMLElement | null
        if (target && (
          target.tagName === 'INPUT' ||
          target.tagName === 'TEXTAREA' ||
          target.tagName === 'SELECT' ||
          target.isContentEditable
        )) {
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
          clearAlignmentGuides(canvas)
          hidePortTooltip()
          if (graphInstance.value) {
            for (const n of graphInstance.value._nodes) {
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
 * 启用画布交互（标准 ComfyUI 风格）：
 *   - 左键空白区域拖动 → 框选多节点
 *   - 右键空白区域拖动 → 平移视角
 *   - 右键节点 → 显示上下文菜单（LiteGraph 原生 processContextMenu，含 Remove 等）
 *   - 中键拖动 → 平移视角（LiteGraph 原生）
 *   - 左键节点 → 选中/拖动节点（LiteGraph 原生）
 *   - 多选后拖动任一节点 → 整体移动（LiteGraph 原生）
 *
 * 实现方式：monkey-patch LGraphCanvas._mousedown_callback
 *   1. 左键空白：将 e.ctrlKey 强制设为 true，让 LiteGraph 原生框选逻辑生效（L5998-L6006）
 *   2. 右键空白：origCallback 执行后强制设置 dragging_canvas=true，
 *      LiteGraph 原生 mousemove（L6497-L6502）会处理平移，
 *      mouseup（L6964-L6968）会自动清理 dragging_canvas
 */
function clearAlignmentGuides(canvas?: LGraphCanvasClass | null) {
  if (!alignmentGuides.value.length) return
  alignmentGuides.value = []
  const c = canvas ?? canvasInstance.value
  c?.setDirty(true, true)
}

function enableCanvasInteractions(canvas: LGraphCanvasClass) {
  const canvasAny = canvas as unknown as {
    _mousedown_callback?: (e: MouseEvent) => void
    dragging_canvas?: boolean
  }
  const origCallback = canvasAny._mousedown_callback
  if (!origCallback || !canvasRef.value) return

  const wrappedCallback = (e: MouseEvent) => {
    const isLeftClick = e.button === 0
    const isRightClick = e.button === 2
    const onEmpty = isPointOnEmptyArea(e, canvas)

    // 点击空白：立即清除对齐辅助线（左键/右键空白都清）
    if (onEmpty) {
      clearAlignmentGuides(canvas)
      hidePortTooltip()
    }

    // 左键空白 → 框选：让 LiteGraph 进入 dragging_rectangle 模式
    if (isLeftClick && shouldTriggerBoxSelection(e, canvas)) {
      try {
        Object.defineProperty(e, 'ctrlKey', { get: () => true, configurable: true })
      } catch {
        // 修改失败时退化为原生行为（用户仍可手动按 Ctrl 框选）
      }
    }

    const result = origCallback(e)

    // 右键空白 → 平移视角：origCallback 中 LiteGraph 的右键分支在 node=null 时什么都不做
    // （L6362-L6384：node 为 null 时跳过 processContextMenu），所以这里强制启动平移
    // mousemove 中 dragging_canvas=true 会更新 offset（L6497-L6502）
    // mouseup 中 which==3 会自动清理 dragging_canvas=false（L6964-L6968）
    if (isRightClick && shouldTriggerPanOnRightClick(e, canvas)) {
      canvasAny.dragging_canvas = true
    }

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
      if (me.button != null && me.button !== 0 && me.button !== 2) return
      // 点在 minimap 上不处理
      const target = e.target as HTMLElement | null
      if (target?.closest?.('.workflow-minimap')) return
      if (isPointOnEmptyArea(me, canvas)) {
        clearAlignmentGuides(canvas)
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
 * 判断当前 mousedown 事件是否应触发右键平移模式。
 * 条件：
 *   1. 右键（button === 2）
 *   2. 非只读模式（只读也允许平移视角，不禁用）
 *   3. 点击位置不在任何节点上（点中节点时让 LiteGraph 显示右键菜单）
 *   4. canvas 状态正常
 */
function shouldTriggerPanOnRightClick(e: MouseEvent, canvas: LGraphCanvasClass): boolean {
  if (e.button !== 2) return false
  if (!graphInstance.value) return false
  return isPointOnEmptyArea(e, canvas)
}

/**
 * 判断鼠标点击位置是否在空白区域（不在任何节点上）。
 * 共用工具函数，供框选和右键平移判断使用。
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

// ─── minimap 绘制与交互 ────────────────────────────────────────────────────

/**
 * 绘制 minimap（右下角小地图预览）。
 * 节流到 5 FPS（setInterval 200ms），独立于主画布渲染循环。
 * 内容：所有节点的矩形（按引擎色着色）+ 当前视口框（橙色矩形）。
 */
function drawMinimap() {
  const mm = minimapRef.value
  const graph = graphInstance.value
  const canvas = canvasInstance.value
  if (!mm || !graph || !canvas) return
  const ctx = mm.getContext('2d')
  if (!ctx) return

  const W = mm.width
  const H = mm.height
  ctx.clearRect(0, 0, W, H)
  ctx.fillStyle = 'rgba(8, 15, 28, 0.6)'
  ctx.fillRect(0, 0, W, H)

  const nodes = graph._nodes
  if (nodes.length === 0) return

  // 计算所有节点的边界框
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity
  for (const n of nodes) {
    const w = n.size?.[0] ?? 200
    const h = n.size?.[1] ?? 100
    minX = Math.min(minX, n.pos[0])
    minY = Math.min(minY, n.pos[1])
    maxX = Math.max(maxX, n.pos[0] + w)
    maxY = Math.max(maxY, n.pos[1] + h)
  }
  // 加 padding 避免节点贴边
  const pad = 40
  minX -= pad; minY -= pad; maxX += pad; maxY += pad
  const contentW = maxX - minX
  const contentH = maxY - minY
  if (contentW <= 0 || contentH <= 0) return

  // 计算缩放比例（保持长宽比，fit 到 minimap）
  const scale = Math.min(W / contentW, H / contentH)
  const offsetX = (W - contentW * scale) / 2
  const offsetY = (H - contentH * scale) / 2

  // graph 坐标 → minimap 坐标
  const toMx = (x: number) => (x - minX) * scale + offsetX
  const toMy = (y: number) => (y - minY) * scale + offsetY

  // 绘制每个节点的矩形
  for (const n of nodes) {
    const w = n.size?.[0] ?? 200
    const h = n.size?.[1] ?? 100
    const x = toMx(n.pos[0])
    const y = toMy(n.pos[1])
    const nw = Math.max(2, w * scale)
    const nh = Math.max(2, h * scale)
    // 按引擎类型着色（module/* 属于 python_provider）
    const t = n.type ?? ''
    let color = '#88dfff'
    if (t.startsWith('weather/')) color = '#ffb84d'
    else if (t.startsWith('module/') || t.startsWith('python_provider/')) color = '#78ffa0'
    else if (t.startsWith('gee/')) color = '#5ad5ff'
    ctx.fillStyle = color
    ctx.globalAlpha = n.selected ? 1.0 : 0.7
    ctx.fillRect(x, y, nw, nh)
  }
  ctx.globalAlpha = 1.0

  // 绘制当前视口框（橙色矩形）
  const ds = (canvas as unknown as { ds?: { offset: [number, number]; scale: number } }).ds
  const mainCanvas = canvasRef.value
  if (ds && mainCanvas) {
    // 视口在 graph 坐标系中的范围
    const viewLeft = -ds.offset[0] / ds.scale
    const viewTop = -ds.offset[1] / ds.scale
    const viewW = mainCanvas.width / ds.scale
    const viewH = mainCanvas.height / ds.scale
    const vx = toMx(viewLeft)
    const vy = toMy(viewTop)
    const vw = viewW * scale
    const vh = viewH * scale
    ctx.strokeStyle = 'rgba(255, 184, 77, 0.9)'
    ctx.lineWidth = 1
    ctx.setLineDash([3, 3])
    ctx.strokeRect(vx, vy, vw, vh)
    ctx.setLineDash([])
  }
}

/**
 * 绑定 minimap 点击/拖动事件：将点击位置同步到主画布视口中心。
 */
function bindMinimapInteractions() {
  const mm = minimapRef.value
  if (!mm) return

  _minimapMousedownHandlerRef = (e: MouseEvent) => {
    syncMinimapToViewport(e)
    // 进入拖动模式
    _minimapMousemoveHandlerRef = (ev: MouseEvent) => syncMinimapToViewport(ev)
    mm.addEventListener('mousemove', _minimapMousemoveHandlerRef)
    _minimapMouseupHandlerRef = () => {
      if (_minimapMousemoveHandlerRef) {
        mm.removeEventListener('mousemove', _minimapMousemoveHandlerRef)
        _minimapMousemoveHandlerRef = null
      }
      if (_minimapMouseupHandlerRef) {
        mm.removeEventListener('mouseup', _minimapMouseupHandlerRef)
        _minimapMouseupHandlerRef = null
      }
    }
    mm.addEventListener('mouseup', _minimapMouseupHandlerRef)
  }
  mm.addEventListener('mousedown', _minimapMousedownHandlerRef)
}

/**
 * 将 minimap 上的点击/拖动位置转换为 graph 坐标，并同步主画布视口中心。
 */
function syncMinimapToViewport(e: MouseEvent) {
  const mm = minimapRef.value
  const graph = graphInstance.value
  const canvas = canvasInstance.value
  if (!mm || !graph || !canvas) return

  const rect = mm.getBoundingClientRect()
  const px = e.clientX - rect.left
  const py = e.clientY - rect.top

  // 反推 graph 坐标（与 drawMinimap 中的计算对应）
  const nodes = graph._nodes
  if (nodes.length === 0) return
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity
  for (const n of nodes) {
    const w = n.size?.[0] ?? 200
    const h = n.size?.[1] ?? 100
    minX = Math.min(minX, n.pos[0])
    minY = Math.min(minY, n.pos[1])
    maxX = Math.max(maxX, n.pos[0] + w)
    maxY = Math.max(maxY, n.pos[1] + h)
  }
  const pad = 40
  minX -= pad; minY -= pad; maxX += pad; maxY += pad
  const contentW = maxX - minX
  const contentH = maxY - minY
  if (contentW <= 0 || contentH <= 0) return

  const scale = Math.min(mm.width / contentW, mm.height / contentH)
  const offsetX = (mm.width - contentW * scale) / 2
  const offsetY = (mm.height - contentH * scale) / 2
  // minimap 坐标 → graph 坐标
  const gx = (px - offsetX) / scale + minX
  const gy = (py - offsetY) / scale + minY

  // 将主画布视口中心对齐到 (gx, gy)
  const ds = (canvas as unknown as { ds?: { offset: [number, number]; scale: number } }).ds
  const mainCanvas = canvasRef.value
  if (!ds || !mainCanvas) return
  ds.offset[0] = -gx * ds.scale + mainCanvas.width / 2
  ds.offset[1] = -gy * ds.scale + mainCanvas.height / 2
  canvas.setDirty(true, true)
}

// ─── 连接点悬停提示 ────────────────────────────────────────────────────────

function hidePortTooltip() {
  if (!portTooltip.value.visible) return
  portTooltip.value = { visible: false, x: 0, y: 0, model: null, accent: '#5ad5ff' }
  _portTooltipKey = ''
}

function resolveSuggestTitles(portType: string): string[] {
  return suggestConnectorsForPortType(portType)
    .map((t) => props.nodeTemplates.find((n) => n.type === t)?.title ?? t)
}

function clientToGraphCoords(e: MouseEvent, canvas: LGraphCanvasClass): { x: number; y: number } | null {
  // 优先走 LiteGraph 官方坐标换算，避免与缩放/偏移不一致
  const canvasAny = canvas as unknown as {
    adjustMouseEvent?: (ev: MouseEvent) => void
    ds?: { offset: [number, number]; scale: number }
  }
  if (typeof canvasAny.adjustMouseEvent === 'function') {
    canvasAny.adjustMouseEvent(e)
    const ev = e as MouseEvent & { canvasX?: number; canvasY?: number }
    if (typeof ev.canvasX === 'number' && typeof ev.canvasY === 'number') {
      return { x: ev.canvasX, y: ev.canvasY }
    }
  }
  const canvasEl = canvasRef.value
  const ds = canvasAny.ds
  if (!canvasEl || !ds || !ds.scale) return null
  const rect = canvasEl.getBoundingClientRect()
  const sx = e.clientX - rect.left
  const sy = e.clientY - rect.top
  return {
    x: sx / ds.scale - ds.offset[0],
    y: sy / ds.scale - ds.offset[1],
  }
}

function updatePortTooltipFromEvent(e: MouseEvent, canvas: LGraphCanvasClass) {
  if (!graphInstance.value) {
    hidePortTooltip()
    return
  }

  const graphPos = clientToGraphCoords(e, canvas)
  if (!graphPos) {
    hidePortTooltip()
    return
  }

  const ds = (canvas as unknown as { ds?: { scale: number } }).ds
  const scale = Math.max(ds?.scale ?? 1, 0.35)
  // 连接点常在节点外缘，不能先 getNodeOnPos；扫描全部节点的 slot
  const hit = 22 / scale
  let best: {
    node: LGraphNodeClass
    direction: 'input' | 'output'
    slotIndex: number
    dist: number
  } | null = null

  for (const node of graphInstance.value._nodes ?? []) {
    const probe = (isInput: boolean, count: number) => {
      for (let i = 0; i < count; i++) {
        const out = new Float32Array(2)
        const pos = (node as unknown as {
          getConnectionPos?: (input: boolean, slot: number, out?: Float32Array) => Float32Array | number[]
        }).getConnectionPos?.(isInput, i, out)
        if (!pos) continue
        const dist = Math.hypot(graphPos.x - pos[0], graphPos.y - pos[1])
        if (dist <= hit && (!best || dist < best.dist)) {
          best = {
            node,
            direction: isInput ? 'input' : 'output',
            slotIndex: i,
            dist,
          }
        }
      }
    }
    probe(true, node.inputs?.length ?? 0)
    probe(false, node.outputs?.length ?? 0)
  }

  if (!best) {
    hidePortTooltip()
    return
  }

  const { node, direction, slotIndex } = best
  const slot = direction === 'input' ? node.inputs?.[slotIndex] : node.outputs?.[slotIndex]
  if (!slot) {
    hidePortTooltip()
    return
  }

  const slotAny = slot as Record<string, unknown>
  const portType = String(slot.type ?? '')
  const key = `${node.id}:${direction}:${slotIndex}`
  // Teleport 到 body 时用 client 坐标做 fixed 定位
  const screenX = e.clientX
  const screenY = e.clientY

  if (key !== _portTooltipKey) {
    _portTooltipKey = key
    const tpl = props.nodeTemplates.find((t) => t.type === node.type)
    const tplPort = direction === 'input'
      ? tpl?.inputs?.find((p) => p.name === slot.name)
      : tpl?.outputs?.find((p) => p.name === slot.name)
    const help = (typeof slotAny._help === 'string' ? slotAny._help : undefined)
      ?? tplPort?.description
    const connected = direction === 'input'
      ? (slot as { link?: number | null }).link != null
      : Array.isArray((slot as { links?: number[] | null }).links)
        && ((slot as { links?: number[] | null }).links?.length ?? 0) > 0

    const model = buildPortTooltip({
      direction,
      name: slot.name ?? `slot-${slotIndex}`,
      type: portType,
      description: help,
      required: slotAny._optional === true ? false : tplPort?.required,
      connected,
      nodeTitle: node.title,
      suggestTitles: resolveSuggestTitles(portType),
    })
    portTooltip.value = {
      visible: true,
      x: screenX,
      y: screenY,
      model,
      accent: getPortColor(portType),
    }
  } else {
    portTooltip.value = {
      ...portTooltip.value,
      visible: true,
      x: screenX,
      y: screenY,
    }
  }
}

// ─── 吸附网格 + 对齐辅助线 ────────────────────────────────────────────────

function snapToGrid(value: number, grid = SNAP_GRID_SIZE): number {
  return Math.round(value / grid) * grid
}

function nodeBounds(node: LGraphNodeClass) {
  const w = node.size?.[0] ?? 200
  const h = node.size?.[1] ?? 100
  return {
    left: node.pos[0],
    top: node.pos[1],
    right: node.pos[0] + w,
    bottom: node.pos[1] + h,
    centerX: node.pos[0] + w / 2,
    centerY: node.pos[1] + h / 2,
    w,
    h,
  }
}

/**
 * 拖动时：优先边缘磁吸到其他节点，否则吸附到网格。
 * hard=true 时用于松手落点，强制网格对齐。
 */
function applySnapWhileDragging(
  draggedNode: LGraphNodeClass,
  selectedNodes: Record<string, LGraphNodeClass>,
  hard = false,
) {
  if (!graphInstance.value) return
  const selected = Object.values(selectedNodes)
  const movers = selected.length > 0 ? selected : [draggedNode]
  const primary = draggedNode
  const pb = nodeBounds(primary)
  const others = graphInstance.value._nodes.filter((n) => !movers.some((m) => m.id === n.id))

  let bestDx: number | null = null
  let bestDy: number | null = null
  let bestAbsDx = ALIGN_SNAP_THRESHOLD
  let bestAbsDy = ALIGN_SNAP_THRESHOLD

  for (const o of others) {
    const ob = nodeBounds(o)
    const xCandidates = [
      ob.left - pb.left,
      ob.right - pb.right,
      ob.centerX - pb.centerX,
      ob.left - pb.right,
      ob.right - pb.left,
    ]
    const yCandidates = [
      ob.top - pb.top,
      ob.bottom - pb.bottom,
      ob.centerY - pb.centerY,
      ob.top - pb.bottom,
      ob.bottom - pb.top,
    ]
    for (const dx of xCandidates) {
      const adx = Math.abs(dx)
      if (adx < bestAbsDx) {
        bestAbsDx = adx
        bestDx = dx
      }
    }
    for (const dy of yCandidates) {
      const ady = Math.abs(dy)
      if (ady < bestAbsDy) {
        bestAbsDy = ady
        bestDy = dy
      }
    }
  }

  // 边缘磁吸优先；否则吸附到网格（hard 仅表示松手再确认一次）
  void hard
  const dx = bestDx !== null
    ? bestDx
    : snapToGrid(primary.pos[0]) - primary.pos[0]
  const dy = bestDy !== null
    ? bestDy
    : snapToGrid(primary.pos[1]) - primary.pos[1]

  if (Math.abs(dx) < 0.01 && Math.abs(dy) < 0.01) return
  for (const n of movers) {
    n.pos[0] += dx
    n.pos[1] += dy
  }
}

/**
 * 计算当前拖动节点与其他节点的对齐辅助线。
 * 对齐线覆盖：拖动节点与参考节点之间的跨度（更易看清对齐目标）。
 */
function computeAlignmentGuides(draggedNode: LGraphNodeClass) {
  if (!graphInstance.value) return
  const guides: AlignmentGuide[] = []
  const others = graphInstance.value._nodes.filter((n) => n.id !== draggedNode.id)
  const threshold = ALIGN_SNAP_THRESHOLD
  const db = nodeBounds(draggedNode)
  const pad = 24

  for (const o of others) {
    const ob = nodeBounds(o)
    const xPairs: Array<[number, number]> = [
      [ob.left, db.left],
      [ob.right, db.right],
      [ob.centerX, db.centerX],
      [ob.left, db.right],
      [ob.right, db.left],
    ]
    for (const [ref, cur] of xPairs) {
      if (Math.abs(ref - cur) <= threshold) {
        guides.push({
          orientation: 'vertical',
          pos: ref,
          start: Math.min(db.top, ob.top) - pad,
          end: Math.max(db.bottom, ob.bottom) + pad,
        })
      }
    }
    const yPairs: Array<[number, number]> = [
      [ob.top, db.top],
      [ob.bottom, db.bottom],
      [ob.centerY, db.centerY],
      [ob.top, db.bottom],
      [ob.bottom, db.top],
    ]
    for (const [ref, cur] of yPairs) {
      if (Math.abs(ref - cur) <= threshold) {
        guides.push({
          orientation: 'horizontal',
          pos: ref,
          start: Math.min(db.left, ob.left) - pad,
          end: Math.max(db.right, ob.right) + pad,
        })
      }
    }
  }
  alignmentGuides.value = guides
}

// ─── 节点编辑快捷键辅助函数 ────────────────────────────────────────────────

function selectAllNodes() {
  if (!graphInstance.value) return
  for (const n of graphInstance.value._nodes) {
    n.selected = true
  }
  canvasInstance.value?.setDirty(true, true)
}

function copySelectedNodes() {
  if (!graphInstance.value) return
  _clipboard = graphInstance.value._nodes
    .filter((n) => n.selected)
    .map((n) => ({
      type: n.type ?? '',
      pos: [n.pos[0], n.pos[1]] as [number, number],
      properties: { ...(n.properties ?? {}) } as Record<string, unknown>,
      title: n.title,
    }))
}

function pasteNodes() {
  if (!graphInstance.value || !LiteGraph) return
  for (const item of _clipboard) {
    try {
      const node = LiteGraph.createNode<LGraphNodeClass>(item.type)
      if (!node) continue
      node.pos = [item.pos[0] + 30, item.pos[1] + 30]
      if (item.title) node.title = item.title
      if (item.properties) node.properties = { ...item.properties }
      graphInstance.value.add(node)
    } catch (err) {
      console.error('[WorkflowCanvas] Failed to paste node:', err)
    }
  }
  emitChange()
}

function duplicateSelectedNodes() {
  if (!graphInstance.value) return
  const selected = graphInstance.value._nodes.filter((n) => n.selected)
  for (const n of selected) {
    try {
      if (!LiteGraph) continue
      const node = LiteGraph.createNode<LGraphNodeClass>(n.type ?? '')
      if (!node) continue
      node.pos = [n.pos[0] + 30, n.pos[1] + 30]
      node.title = n.title
      node.properties = { ...(n.properties ?? {}) }
      graphInstance.value.add(node)
    } catch (err) {
      console.error('[WorkflowCanvas] Failed to duplicate node:', err)
    }
  }
  emitChange()
}

function loadDefinitionIntoGraph(def: WorkflowDefinition, graph: LGraphClass) {
  try {
    const graphData = workflowDefinitionToGraphData(def)
    graph.configure(graphData as unknown as object)

    // 安全网：手动恢复节点 inputs/outputs 对 graph.links 的引用
    // 即使 workflowDefinitionToGraphData 已正确填充 link/links 字段，
    // LGraphNode.configure() 的 cloneObject 在某些边界情况下可能未完整恢复引用，
    // 这里遍历 graph.links 显式回填，确保画布渲染连线。
    const graphAny = graph as unknown as {
      links: Array<{
        id: number
        origin_id: number
        origin_slot: number
        target_id: number
        target_slot: number
      } | null> | null
      getNodeById: (id: number) => {
        id: number
        inputs?: Array<{ link: number | null }>
        outputs?: Array<{ links: number[] | null }>
      } | null
    }
    if (graphAny.links) {
      for (const link of graphAny.links) {
        if (!link) continue
        const originNode = graphAny.getNodeById(link.origin_id)
        const targetNode = graphAny.getNodeById(link.target_id)
        if (originNode?.outputs?.[link.origin_slot]) {
          const slot = originNode.outputs[link.origin_slot]
          if (!slot.links) slot.links = []
          if (!slot.links.includes(link.id)) slot.links.push(link.id)
        }
        if (targetNode?.inputs?.[link.target_slot]) {
          targetNode.inputs[link.target_slot].link = link.id
        }
      }
    }

    // 按最新模板补齐 time_range / bbox 等缺失端口（旧图打开后也能连）
    if (props.nodeTemplates.length > 0) {
      syncGraphSlotsWithTemplates(
        graph,
        props.nodeTemplates.map((t) => ({
          type: t.type,
          inputs: t.inputs,
          outputs: t.outputs,
          params: t.params,
        })),
      )
    }

    // 加载后重新计算节点尺寸，确保文字不重叠/不溢出
    const nodes = (graph as unknown as { _nodes?: Array<{ computeSize?: () => [number, number]; size?: [number, number] }> })._nodes
    if (nodes) {
      for (const node of nodes) {
        if (typeof node.computeSize === 'function') {
          const computed = node.computeSize()
          if (computed && computed[0] > 0 && computed[1] > 0) {
            node.size = [Math.max(computed[0], 180), Math.max(computed[1], 60)]
          }
        }
      }
    }

    // 强制重绘
    if (canvasInstance.value) {
      canvasInstance.value.setDirty(true, true)
    }

    // 加载后自动适配视图
    requestAnimationFrame(() => fitView())
  } catch (err) {
    console.error('[WorkflowCanvas] Failed to load definition into graph:', err)
  }
}

// ─── 序列化输出 ─────────────────────────────────────────────────────────────

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

// ─── 公开方法（通过 defineExpose） ──────────────────────────────────────────

function getSerializedGraph(): { nodes: WorkflowDefinitionNode[]; links: WorkflowDefinitionLink[] } | null {
  if (!graphInstance.value) return null
  try {
    const graphData = graphInstance.value.serialize<serializedLGraph>()
    return graphDataToWorkflowNodes(graphData)
  } catch (err) {
    console.error('[WorkflowCanvas] Failed to serialize graph:', err)
    return null
  }
}

function clearGraph() {
  if (!graphInstance.value) return
  graphInstance.value.clear()
  emitChange()
}

function arrangeNodes() {
  if (!graphInstance.value) return
  graphInstance.value.arrange()
  emitChange()
}

function fitView() {
  if (!canvasInstance.value || !graphInstance.value) return
  const canvas = canvasInstance.value
  const nodes = graphInstance.value._nodes
  if (!nodes || nodes.length === 0) return

  // 计算所有节点的边界框
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity
  for (const node of nodes) {
    const w = node.size?.[0] ?? 200
    const h = node.size?.[1] ?? 100
    minX = Math.min(minX, node.pos[0])
    minY = Math.min(minY, node.pos[1])
    maxX = Math.max(maxX, node.pos[0] + w)
    maxY = Math.max(maxY, node.pos[1] + h)
  }

  const rect = canvasRef.value?.getBoundingClientRect()
  if (!rect || !canvas.ds) return

  const padding = 60
  const contentW = maxX - minX + padding * 2
  const contentH = maxY - minY + padding * 2
  const scaleX = rect.width / contentW
  const scaleY = rect.height / contentH
  const scale = Math.min(scaleX, scaleY, 1.5) // 最大缩放 1.5x

  const ds = canvas.ds as unknown as { offset: [number, number]; scale: number }
  ds.scale = scale
  // 居中
  ds.offset[0] = -minX * scale + (rect.width - (maxX - minX) * scale) / 2
  ds.offset[1] = -minY * scale + (rect.height - (maxY - minY) * scale) / 2

  canvas.setDirty(true, true)
}

/**
 * 添加一个新节点到画布上。
 * @param nodeType 节点类型（如 "weather/forecast_fetch"）
 * @param pos 可选位置 [x, y]，默认为视口中心
 * @returns 创建的节点实例
 */
function addNodeByType(
  nodeType: string,
  pos?: [number, number],
): LGraphNodeClass | null {
  if (!graphInstance.value || !LiteGraph) return null
  try {
    const node = LiteGraph.createNode<LGraphNodeClass>(nodeType)
    if (!node) {
      console.warn(`[WorkflowCanvas] Failed to create node: ${nodeType}`)
      return null
    }

    // 默认位置：视口中心附近，并叠加少量偏移避免重叠
    if (pos) {
      node.pos = pos
    } else {
      // 计算视口中心（基于 canvas 的当前缩放和平移）
      const canvas = canvasInstance.value
      if (canvas?.ds) {
        const ds = canvas.ds as unknown as { offset: [number, number]; scale: number }
        const rect = canvasRef.value?.getBoundingClientRect()
        if (rect) {
          const cx = (rect.width / 2 - ds.offset[0]) / ds.scale
          const cy = (rect.height / 2 - ds.offset[1]) / ds.scale
          // 叠加偏移避免新节点完全重叠
          const offset = graphInstance.value._nodes?.length ?? 0
          node.pos = [cx + (offset % 5) * 30, cy + (offset % 5) * 30]
        } else {
          node.pos = [200, 200]
        }
      } else {
        node.pos = [200, 200]
      }
    }

    graphInstance.value.add(node)
    emitChange()
    return node
  } catch (err) {
    console.error('[WorkflowCanvas] Failed to add node:', err)
    return null
  }
}

/**
 * 删除指定节点。
 */
function removeNode(nodeId: number) {
  if (!graphInstance.value) return
  const node = graphInstance.value.getNodeById(nodeId)
  if (node) {
    graphInstance.value.remove(node)
    emitChange()
  }
}

/** 关闭编辑器时清理挂到 body / canvas 容器的 LiteGraph 浮动 UI，避免输入框泄漏到主界面 */
function disposeLiteGraphFloatingUi() {
  const canvas = canvasInstance.value as unknown as {
    search_box?: { close?: () => void } | null
    prompt_box?: { close?: () => void } | null
    closePanels?: () => void
  } | null

  try { canvas?.search_box?.close?.() } catch { /* ignore */ }
  try { canvas?.prompt_box?.close?.() } catch { /* ignore */ }
  try { canvas?.closePanels?.() } catch { /* ignore */ }
  try {
    ;(LiteGraph as unknown as { closeAllContextMenus?: (w?: Window) => void })
      .closeAllContextMenus?.(window)
  } catch { /* ignore */ }

  // prompt / createDialog 挂在 canvas.parentNode；搜索框/菜单挂在 document.body
  canvasContainerRef.value
    ?.querySelectorAll('.graphdialog, .litegraph.dialog, .litegraph.litesearchbox, .litegraph.litecontextmenu')
    .forEach((el) => {
      try { el.parentNode?.removeChild(el) } catch { /* ignore */ }
    })

  document.querySelectorAll(
    '.graphdialog, .litegraph.graphdialog, .litegraph.litesearchbox, .litegraph.litecontextmenu, .litegraph.dialog, #node-panel, #option-panel',
  ).forEach((el) => {
    try { el.parentNode?.removeChild(el) } catch { /* ignore */ }
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
  if (resizeObserver) {
    resizeObserver.disconnect()
    resizeObserver = null
  }
  // 清理 minimap 定时器
  if (_minimapTimer) {
    clearInterval(_minimapTimer)
    _minimapTimer = null
  }
  // 清理 minimap 事件监听
  const mm = minimapRef.value
  if (mm) {
    if (_minimapMousedownHandlerRef) {
      mm.removeEventListener('mousedown', _minimapMousedownHandlerRef)
      _minimapMousedownHandlerRef = null
    }
    if (_minimapMousemoveHandlerRef) {
      mm.removeEventListener('mousemove', _minimapMousemoveHandlerRef)
      _minimapMousemoveHandlerRef = null
    }
    if (_minimapMouseupHandlerRef) {
      mm.removeEventListener('mouseup', _minimapMouseupHandlerRef)
      _minimapMouseupHandlerRef = null
    }
  }
  // 清理主画布事件监听
  const canvasEl = canvasRef.value
  const tipHost = canvasContainerRef.value ?? canvasEl
  if (tipHost) {
    if (_portMousemoveHandlerRef) {
      tipHost.removeEventListener('mousemove', _portMousemoveHandlerRef, true)
      _portMousemoveHandlerRef = null
    }
    tipHost.removeEventListener('mouseleave', hidePortTooltip)
  }
  const container = canvasContainerRef.value as (HTMLDivElement & {
    __clearGuidesHandler?: (e: Event) => void
  }) | null
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
    canvasEl.removeEventListener('mouseleave', hidePortTooltip)
  }
  hidePortTooltip()
  // 清空对齐辅助线状态
  alignmentGuides.value = []
  // 清空剪贴板
  _clipboard = []
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
      <span class="error-icon" aria-hidden="true">⚠</span>
      <span class="error-text">画布初始化失败：{{ errorMsg }}</span>
    </div>
    <div v-else-if="!isReady" class="canvas-loading">
      <span class="loading-spinner"></span>
      <span>正在加载画布...</span>
    </div>

    <canvas
      ref="minimapRef"
      class="workflow-minimap"
      width="160"
      height="100"
      aria-hidden="true"
    />
  </div>

  <!-- Teleport 到 body，避免被 editor-canvas-area 的 overflow:hidden 裁剪 -->
  <Teleport to="body">
    <Transition name="port-tip">
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
  background: #0a0f1c;
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
  color: #8aa8bf;
  font-size: 0.74rem;
  background: rgba(8, 15, 28, 0.92);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
}

.canvas-error {
  color: #ff9b9b;
}

.error-icon {
  font-size: 1.6rem;
  color: #ff6b6b;
}

.loading-spinner {
  width: 1.6rem;
  height: 1.6rem;
  border: 2px solid rgba(90, 213, 255, 0.2);
  border-top-color: #5ad5ff;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
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
  border: 1px solid color-mix(in srgb, var(--tip-accent, #5ad5ff) 45%, transparent);
  background: linear-gradient(165deg, rgba(14, 24, 40, 0.96), rgba(8, 14, 26, 0.94));
  box-shadow: 0 10px 28px rgba(0, 0, 0, 0.45), 0 0 0 1px rgba(255, 255, 255, 0.03) inset;
  pointer-events: none;
  color: #d5e4f3;
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
  font-size: 0.52rem;
  font-weight: 600;
  letter-spacing: 0.02em;
  color: #0b1220;
  background: var(--tip-accent, #5ad5ff);
}

:global(.wf-port-tooltip .port-tip-title) {
  flex: 1;
  min-width: 0;
  font-size: 0.72rem;
  font-weight: 650;
  color: #eef6ff;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

:global(.wf-port-tooltip .port-tip-type) {
  flex-shrink: 0;
  font-size: 0.52rem;
  color: color-mix(in srgb, var(--tip-accent, #5ad5ff) 85%, #fff);
}

:global(.wf-port-tooltip .port-tip-body) {
  margin: 0 0 0.35rem;
  font-size: 0.6rem;
  line-height: 1.45;
  color: #b7c9db;
  white-space: pre-wrap;
}

:global(.wf-port-tooltip .port-tip-tips) {
  margin: 0.2rem 0 0;
  padding: 0.35rem 0 0 1rem;
  border-top: 1px solid rgba(136, 192, 255, 0.12);
  list-style: disc;
}

:global(.wf-port-tooltip .port-tip-tips li) {
  margin: 0.12rem 0;
  font-size: 0.55rem;
  line-height: 1.4;
  color: #9eb4c9;
}

:global(.port-tip-enter-active),
:global(.port-tip-leave-active) {
  transition: opacity 0.12s ease, transform 0.12s ease;
}
:global(.port-tip-enter-from),
:global(.port-tip-leave-to) {
  opacity: 0;
  transform: translateY(4px);
}

/* ── minimap 小地图 ────────────────────────────────────────────────── */
.workflow-minimap {
  position: absolute;
  right: 0.6rem;
  bottom: 0.6rem;
  width: 160px;
  height: 100px;
  border: 1px solid rgba(136, 192, 255, 0.2);
  border-radius: 0.32rem;
  background: rgba(8, 15, 28, 0.85);
  pointer-events: auto;
  cursor: pointer;
  z-index: 5;
}
</style>
