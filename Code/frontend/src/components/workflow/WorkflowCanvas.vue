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
import {
  LGraph,
  LGraphCanvas,
  LiteGraph,
  registerWorkflowNodeTypes,
  workflowDefinitionToGraphData,
  graphDataToWorkflowNodes,
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
  // 基本配置
  canvas.background_image = 'data:image/svg+xml;base64,' + btoa(
    '<svg xmlns="http://www.w3.org/2000/svg" width="40" height="40" viewBox="0 0 40 40">' +
    '<circle cx="1" cy="1" r="0.8" fill="rgba(90,180,255,0.12)"/></svg>'
  )
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

  // 节点移动后通知父组件（dirty 状态）+ 计算对齐辅助线
  const origOnNodeMoved = (canvas as unknown as {
    onNodeMoved?: (node: LGraphNodeClass) => void
  }).onNodeMoved
  ;(canvas as unknown as { onNodeMoved?: (node: LGraphNodeClass) => void }).onNodeMoved = (
    node: LGraphNodeClass,
  ) => {
    emitChange()
    // 拖动过程中实时计算对齐辅助线
    computeAlignmentGuides(node)
    if (origOnNodeMoved) origOnNodeMoved(node)
  }

  // 绘制叠加层：对齐辅助线（橙色虚线）
  // 注意：onDrawOverlay 在 LiteGraph 完成 ds 变换 restore 之后调用，
  // 此时 ctx 处于屏幕坐标系，必须将 graph 坐标转换为屏幕坐标。
  ;(canvas as unknown as { onDrawOverlay?: (ctx: CanvasRenderingContext2D) => void }).onDrawOverlay = (ctx: CanvasRenderingContext2D) => {
    if (!alignmentGuides.value.length) return
    const ds = (canvas as unknown as { ds?: { offset: [number, number]; scale: number } }).ds
    if (!ds) return
    // graph 坐标 → 屏幕坐标
    const toScreenX = (x: number) => x * ds.scale + ds.offset[0]
    const toScreenY = (y: number) => y * ds.scale + ds.offset[1]
    ctx.save()
    ctx.strokeStyle = 'rgba(255, 184, 77, 0.75)'
    ctx.lineWidth = 1
    ctx.setLineDash([4, 4])
    for (const g of alignmentGuides.value) {
      ctx.beginPath()
      if (g.orientation === 'vertical') {
        const x = toScreenX(g.pos)
        const y1 = toScreenY(g.start)
        const y2 = toScreenY(g.end)
        ctx.moveTo(x, y1)
        ctx.lineTo(x, y2)
      } else {
        const y = toScreenY(g.pos)
        const x1 = toScreenX(g.start)
        const x2 = toScreenX(g.end)
        ctx.moveTo(x1, y)
        ctx.lineTo(x2, y)
      }
      ctx.stroke()
    }
    ctx.restore()
  }

  // mouseup 后清空对齐辅助线（拖动结束）
  if (canvasRef.value) {
    _mouseupHandlerRef = () => {
      if (alignmentGuides.value.length > 0) {
        alignmentGuides.value = []
      }
    }
    canvasRef.value.addEventListener('mouseup', _mouseupHandlerRef)
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

  // 将屏幕坐标转换为 graph 坐标
  const rect = canvasEl.getBoundingClientRect()
  const x = e.clientX - rect.left
  const y = e.clientY - rect.top
  const ds = (canvas as unknown as { ds?: { offset: [number, number]; scale: number } }).ds
  if (!ds) return false
  const canvasX = (x - ds.offset[0]) / ds.scale
  const canvasY = (y - ds.offset[1]) / ds.scale

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
    // 按引擎类型着色
    const t = n.type ?? ''
    let color = '#88dfff'
    if (t.startsWith('weather/')) color = '#ffb84d'
    else if (t.startsWith('python_provider/')) color = '#78ffa0'
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

// ─── 对齐辅助线 ────────────────────────────────────────────────────────────

/**
 * 计算当前拖动节点与其他节点的对齐辅助线。
 * 触发条件：边/中心相差 < 5px（graph 坐标系）。
 * 对齐线长度策略：仅覆盖拖动节点边界 ± pad，让线条始终贴近拖动节点，
 * 避免跨越远处节点造成"跑老远"的困惑。
 * 支持的对齐方式：同侧对齐（左对左/右对右/中心对中心）
 *                + 紧贴对齐（拖动节点右边对齐其他节点左边等）。
 */
function computeAlignmentGuides(draggedNode: LGraphNodeClass) {
  if (!graphInstance.value) return
  const guides: AlignmentGuide[] = []
  const others = graphInstance.value._nodes.filter((n) => n.id !== draggedNode.id)
  const threshold = 5
  const d = draggedNode
  const dLeft = d.pos[0]
  const dTop = d.pos[1]
  const dW = d.size?.[0] ?? 200
  const dH = d.size?.[1] ?? 100
  const dRight = dLeft + dW
  const dBottom = dTop + dH
  const dCenterX = dLeft + dW / 2
  const dCenterY = dTop + dH / 2
  // 对齐线延伸量：拖动节点边界外延伸 20px，让线条更明显
  const pad = 20
  // 垂直对齐线的 y 范围 = 拖动节点上下边界 ± pad
  const vLineY1 = dTop - pad
  const vLineY2 = dBottom + pad
  // 水平对齐线的 x 范围 = 拖动节点左右边界 ± pad
  const hLineX1 = dLeft - pad
  const hLineX2 = dRight + pad

  for (const o of others) {
    const oLeft = o.pos[0]
    const oTop = o.pos[1]
    const oW = o.size?.[0] ?? 200
    const oH = o.size?.[1] ?? 100
    const oRight = oLeft + oW
    const oBottom = oTop + oH
    const oCenterX = oLeft + oW / 2
    const oCenterY = oTop + oH / 2

    // 垂直对齐线候选对：[其他节点参考边, 拖动节点对齐边]
    // 包含同侧对齐 + 紧贴对齐（边对边）
    const xPairs: Array<[number, number]> = [
      [oLeft, dLeft],       // 左边对齐
      [oRight, dRight],     // 右边对齐
      [oCenterX, dCenterX], // 中心 X 对齐
      [oLeft, dRight],      // 拖动节点右边紧贴其他节点左边
      [oRight, dLeft],      // 拖动节点左边紧贴其他节点右边
    ]
    for (const [ref, cur] of xPairs) {
      if (Math.abs(ref - cur) < threshold) {
        guides.push({
          orientation: 'vertical',
          pos: ref,
          start: vLineY1,
          end: vLineY2,
        })
      }
    }
    // 水平对齐线候选对
    const yPairs: Array<[number, number]> = [
      [oTop, dTop],
      [oBottom, dBottom],
      [oCenterY, dCenterY],
      [oTop, dBottom],
      [oBottom, dTop],
    ]
    for (const [ref, cur] of yPairs) {
      if (Math.abs(ref - cur) < threshold) {
        guides.push({
          orientation: 'horizontal',
          pos: ref,
          start: hLineX1,
          end: hLineX2,
        })
      }
    }
  }
  alignmentGuides.value = guides
  // 主动触发 canvas 重绘，确保对齐线立即显示
  canvasInstance.value?.setDirty(true, true)
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

defineExpose({
  getSerializedGraph,
  clearGraph,
  arrangeNodes,
  fitView,
  addNodeByType,
  removeNode,
  isReady,
})

// ─── 生命周期 ───────────────────────────────────────────────────────────────

onMounted(() => {
  // 等待 DOM 渲染完成
  requestAnimationFrame(() => {
    initializeCanvas()
  })
})

onBeforeUnmount(() => {
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
  if (canvasEl) {
    if (_keydownHandlerRef) {
      canvasEl.removeEventListener('keydown', _keydownHandlerRef)
      _keydownHandlerRef = null
    }
    if (_mouseupHandlerRef) {
      canvasEl.removeEventListener('mouseup', _mouseupHandlerRef)
      _mouseupHandlerRef = null
    }
  }
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
