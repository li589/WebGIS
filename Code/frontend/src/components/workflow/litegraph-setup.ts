/**
 * LiteGraph.js 集成助手
 *
 * 处理 LiteGraph.js 库的导入与初始化。
 * 该库使用 IIFE + CommonJS 模式，需要特殊处理才能在 ESM 环境中工作。
 */
import 'litegraph.js/css/litegraph.css'
import './litegraph-ui-overrides.css'
import * as litegraphCore from 'litegraph.js/build/litegraph.core.js'

// 类型导入（仅用于类型检查，不参与运行时）
import type {
  LiteGraph as LiteGraphStatic,
  LGraph as LGraphClass,
  LGraphCanvas as LGraphCanvasClass,
  LGraphNode as LGraphNodeClass,
  LLink as LLinkClass,
  INodeInputSlot,
  INodeOutputSlot,
  IWidget,
  SerializedLGraphNode,
  serializedLGraph,
} from 'litegraph.js'

import type {
  WorkflowDefinition,
  WorkflowDefinitionNode,
  WorkflowDefinitionLink,
} from '../../services/workflow-definition-api'

// 运行时获取：优先从命名导出获取，回退到 window/globalThis
const _globalThis = globalThis as unknown as Record<string, unknown>

export const LiteGraph: typeof LiteGraphStatic =
  (litegraphCore as unknown as { LiteGraph?: typeof LiteGraphStatic }).LiteGraph
  ?? (_globalThis.LiteGraph as typeof LiteGraphStatic)

export const LGraph: typeof LGraphClass =
  (litegraphCore as unknown as { LGraph?: typeof LGraphClass }).LGraph
  ?? (_globalThis.LGraph as typeof LGraphClass)

export const LGraphCanvas: typeof LGraphCanvasClass =
  (litegraphCore as unknown as { LGraphCanvas?: typeof LGraphCanvasClass }).LGraphCanvas
  ?? (_globalThis.LGraphCanvas as typeof LGraphCanvasClass)

export const LGraphNode: typeof LGraphNodeClass =
  (litegraphCore as unknown as { LGraphNode?: typeof LGraphNodeClass }).LGraphNode
  ?? (_globalThis.LGraphNode as typeof LGraphNodeClass)

export const LLink: typeof LLinkClass =
  (litegraphCore as unknown as { LLink?: typeof LLinkClass }).LLink
  ?? (_globalThis.LLink as typeof LLinkClass)

// 重新导出类型供其他模块使用
export type {
  LiteGraphStatic,
  LGraphClass,
  LGraphCanvasClass,
  LGraphNodeClass,
  LLinkClass,
  INodeInputSlot,
  INodeOutputSlot,
  IWidget,
  SerializedLGraphNode,
  serializedLGraph,
}

// ─── 节点类型注册 ──────────────────────────────────────────────────────────

/** 已注册过的类型集合；允许后续用更新后的模板覆盖注册 */
const _registeredTypes = new Set<string>()

/**
 * 将可调参数提升为可选输入端口，使参数也能用连线驱动（widget 仍保留作默认值）。
 */
export function mapParamTypeToPortType(paramType: string): string | null {
  switch (paramType) {
    case 'number':
    case 'integer':
    case 'float':
      return 'value:number'
    case 'boolean':
      return 'value:boolean'
    case 'string':
    case 'enum':
    case 'option':
    case 'array':
      return 'value:string'
    default:
      return null
  }
}

/** 按端口类型给出建议连接的节点类型（用于检查器/提示） */
export function suggestConnectorsForPortType(portType: string): string[] {
  switch (portType) {
    case 'value:time_range':
      return ['data/time_range']
    case 'geometry:bbox':
      return ['data/bbox', 'data/map_viewport']
    case 'value:number':
      return ['data/number', 'data/latlng']
    case 'value:string':
      return ['data/string']
    case 'value:boolean':
      return ['data/boolean']
    case 'data:source':
      return ['data/source']
    case 'data:raster':
      return ['weather/grid_fetch', 'gee/image', 'preprocess/reproject']
    case 'data:mat':
      return ['module/smap_daily', 'module/ndvi_daily', 'module/daily_bundle']
    case 'data:timeseries':
      return ['module/timeseries_bundle']
    case 'data:geojson':
      return ['weather/wind_field_render', 'gis/buffer_analysis']
    default:
      if (portType.startsWith('data:')) return ['data/source']
      return []
  }
}

/**
 * 注册所有自定义节点类型。
 *
 * 每个节点类型对应后端 NodeTemplate 中的一种 type。
 * 可重复调用：未注册的类型会新增，已注册类型会覆盖（便于模板热更新）。
 */
export function registerWorkflowNodeTypes(
  templates: Array<{
    type: string
    title: string
    engine?: string
    inputs: Array<{ name: string; type: string; description?: string; required?: boolean }>
    outputs: Array<{ name: string; type: string; description?: string }>
    params?: Array<{ key: string; type: string; default?: unknown; options?: string[]; description?: string }>
  }>,
): void {
  if (!LiteGraph) {
    console.warn('[litegraph-setup] LiteGraph not available, skipping node registration')
    return
  }

  for (const template of templates) {
    const tpl = template
    const engineColor = getEngineColor(tpl.type, tpl.engine)

    // 合并：显式 inputs + 由 params 提升的可选参数端口（同名不重复）
    const existingNames = new Set(tpl.inputs.map((i) => i.name))
    const promotedParamInputs = (tpl.params ?? [])
      .map((param) => {
        const portType = mapParamTypeToPortType(param.type)
        if (!portType || existingNames.has(param.key)) return null
        existingNames.add(param.key)
        return {
          name: param.key,
          type: portType,
          required: false,
          description: param.description ?? '可调参数：连线可覆盖，未连接时用节点内控件默认值',
        }
      })
      .filter((item): item is { name: string; type: string; required: boolean; description: string } => item !== null)

    const allInputs = [...tpl.inputs, ...promotedParamInputs]

    class WorkflowNode extends (LGraphNode as unknown as typeof LGraphNodeClass) {
      static title = tpl.title
      static type = tpl.type

      constructor(title?: string) {
        super(title ?? tpl.title)
        this.type = tpl.type

        this.color = engineColor.nodeBg
        this.bgcolor = engineColor.nodeHeader
        this.boxcolor = engineColor.accent

        this.resizable = true
        ;(this.flags as Record<string, unknown>).allow_interaction = true

        for (const input of allInputs) {
          this.addInput(input.name, input.type)
          const slot = this.inputs[this.inputs.length - 1]
          if (slot) {
            const slotAny = slot as Record<string, unknown>
            slotAny.color = getPortColor(input.type)
            // 详细说明挂在 _help，供悬停提示框读取；不要写进 label（会挤占节点宽度）
            if (input.description) slotAny._help = input.description
            if (input.required === false) slotAny._optional = true
          }
        }

        for (const output of tpl.outputs) {
          this.addOutput(output.name, output.type)
          const slot = this.outputs[this.outputs.length - 1]
          if (slot) {
            const slotAny = slot as Record<string, unknown>
            slotAny.color = getPortColor(output.type)
            if (output.description) slotAny._help = output.description
          }
        }

        if (tpl.params) {
          for (const param of tpl.params) {
            const widgetType = mapParamTypeToWidget(param.type, param.options)
            let defaultValue: unknown = param.default ?? getDefaultForType(param.type)
            if (param.type === 'array' && Array.isArray(defaultValue)) {
              defaultValue = (defaultValue as unknown[]).join(',')
            }
            const options: Record<string, unknown> = {}
            if (param.options && param.options.length > 0) {
              options.values = param.options
            }
            this.addWidget(
              widgetType as 'number' | 'slider' | 'combo' | 'text' | 'toggle',
              param.key,
              defaultValue,
              param.key,
              options,
            )
          }
        }

        const slotCount = Math.max(allInputs.length, tpl.outputs.length)
        const widgetCount = tpl.params?.length ?? 0
        const minHeight = 36 + slotCount * 20 + widgetCount * 18
        this.size = [220, Math.max(72, minHeight)]
      }

      onConnectInput(
        inputIndex: number,
        outputType: string,
        _outputSlot: unknown,
        _outputNode: unknown,
        _outputSlotIndex: number,
      ): boolean {
        const inputSlot = this.inputs[inputIndex]
        if (!inputSlot) return false
        return checkConnectionValid(inputSlot.type as string, outputType)
      }
    }

    LiteGraph.registerNodeType(template.type, WorkflowNode as unknown as { new (): LGraphNodeClass })
    _registeredTypes.add(template.type)
  }
}

/** 引擎颜色配置 */
interface EngineColor {
  nodeBg: string      // 节点背景色
  nodeHeader: string  // 节点标题栏色
  accent: string      // 强调色（选中边框等）
}

/**
 * 解析节点所属引擎。优先用模板 engine 字段；否则按 type 前缀推断。
 * 注意：Python 模块类型是 `module/*`，不是 `python_provider/*`。
 */
export function resolveNodeEngine(nodeType: string, templateEngine?: string | null): string {
  const fromTpl = (templateEngine ?? '').trim()
  if (fromTpl) return fromTpl
  if (nodeType.startsWith('weather/')) return 'weather'
  if (nodeType.startsWith('gee/')) return 'gee'
  if (nodeType.startsWith('module/') || nodeType.startsWith('python_provider/')) return 'python_provider'
  return 'common'
}

/** 按引擎返回节点配色 */
function getEngineColor(nodeType: string, templateEngine?: string | null): EngineColor {
  const engine = resolveNodeEngine(nodeType, templateEngine)
  if (engine === 'weather') {
    return { nodeBg: '#1a2230', nodeHeader: '#2a4a5a', accent: '#ffb84d' }
  }
  if (engine === 'python_provider') {
    return { nodeBg: '#1a2a1e', nodeHeader: '#2a4a38', accent: '#78ffa0' }
  }
  if (engine === 'gee') {
    return { nodeBg: '#1a2030', nodeHeader: '#3a2e5a', accent: '#5ad5ff' }
  }
  return { nodeBg: '#1a2740', nodeHeader: '#1a2540', accent: '#88dfff' }
}

function mapParamTypeToWidget(paramType: string, options?: string[]): string {
  // 有可选项时优先 combo（后端多为 string+options，而非 enum）
  if (options && options.length > 0) {
    return 'combo'
  }
  switch (paramType) {
    case 'number':
    case 'integer':
    case 'float':
      return 'number'
    case 'boolean':
      return 'toggle'
    case 'enum':
    case 'option':
      return 'combo'
    case 'array':
      // array 类型用文本输入，逗号分隔；运行时由后端解析
      return 'text'
    default:
      return 'text'
  }
}

/**
 * 端口连接类型校验：判断 outputType 是否可连接到 inputType。
 *
 * 规则:
 *   - 相同类型：允许
 *   - data (通用) <-> data:* (具体子类型)：允许（向后兼容）
 *   - 通配 *：允许
 *   - 其余不同类型：禁止（含 value/geometry 互串、data 串到 value）
 */
export function checkConnectionValid(inputType: string, outputType: string): boolean {
  if (!inputType || !outputType) return true
  if (inputType === '*' || outputType === '*') return true
  if (inputType === outputType) return true
  // 仅允许通用 data 与 data:* 子类型互连，禁止 data 接到 value/geometry
  if (inputType === 'data' && outputType.startsWith('data:')) return true
  if (outputType === 'data' && inputType.startsWith('data:')) return true
  return false
}

/**
 * 按端口类型返回颜色（用于 slot 渲染）。
 */
export function getPortColor(type: string): string {
  if (type === 'data' || type === 'data:source') return '#5ad5ff' // 青色
  if (type === 'data:mat') return '#ffb84d' // 橙色
  if (type === 'data:raster') return '#5ad5ff' // 蓝色
  if (type === 'data:geojson') return '#78ffa0' // 绿色
  if (type === 'data:timeseries') return '#c084fc' // 紫色
  if (type === 'value:number') return '#ffd5a8' // 浅黄
  if (type === 'value:string') return '#ffe08a' // 金黄
  if (type === 'value:boolean') return '#9ae6b4' // 浅绿
  if (type === 'value:time_range') return '#ff8fb1' // 粉色
  if (type === 'geometry:bbox') return '#ff6b6b' // 红色
  return '#6e8ba0' // 默认灰
}

/** 端口类型中文说明（检查器/面板用） */
export function getPortTypeLabel(type: string): string {
  switch (type) {
    case 'value:time_range': return '时间范围'
    case 'geometry:bbox': return '空间范围 (bbox)'
    case 'value:number': return '数值'
    case 'value:string': return '文本'
    case 'value:boolean': return '开关'
    case 'data:source': return '数据源路径'
    case 'data:raster': return '栅格'
    case 'data:mat': return 'MAT 数据'
    case 'data:timeseries': return '时间序列'
    case 'data:geojson': return '矢量 GeoJSON'
    case 'data': return '通用数据'
    default: return type
  }
}

/**
 * 根据参数类型返回合适的默认值（当 param.default 为 undefined 时使用）。
 * 避免 number widget 得到空字符串导致类型混乱。
 */
function getDefaultForType(paramType: string): unknown {
  switch (paramType) {
    case 'number':
    case 'integer':
    case 'float':
      return 0
    case 'boolean':
      return false
    default:
      return ''
  }
}

/**
 * 按最新模板给已有节点补齐缺失的输入/输出端口（旧工作流打开后也能看到 time_range/bbox 等）。
 * 不删除已有端口，避免破坏已保存连线。
 */
export function syncGraphSlotsWithTemplates(
  graph: LGraphClass,
  templates: Array<{
    type: string
    inputs: Array<{ name: string; type: string; description?: string; required?: boolean }>
    outputs: Array<{ name: string; type: string; description?: string }>
    params?: Array<{ key: string; type: string; description?: string }>
  }>,
): void {
  const byType = new Map(templates.map((t) => [t.type, t]))
  for (const node of graph._nodes ?? []) {
    const tpl = byType.get(node.type ?? '')
    if (!tpl) continue

    const existingIn = new Set((node.inputs ?? []).map((s) => s.name))
    const existingOut = new Set((node.outputs ?? []).map((s) => s.name))

    const promoted = (tpl.params ?? [])
      .map((param) => {
        const portType = mapParamTypeToPortType(param.type)
        if (!portType || existingIn.has(param.key) || tpl.inputs.some((i) => i.name === param.key)) {
          return null
        }
        return {
          name: param.key,
          type: portType,
          required: false,
          description: param.description ?? '可调参数',
        }
      })
      .filter((x): x is { name: string; type: string; required: boolean; description: string } => x !== null)

    for (const input of [...tpl.inputs, ...promoted]) {
      if (existingIn.has(input.name)) continue
      node.addInput(input.name, input.type)
      const slot = node.inputs[node.inputs.length - 1]
      if (slot) {
        const slotAny = slot as Record<string, unknown>
        slotAny.color = getPortColor(input.type)
        if (input.description) slotAny._help = input.description
        if (input.required === false) slotAny._optional = true
      }
      existingIn.add(input.name)
    }

    for (const output of tpl.outputs) {
      if (existingOut.has(output.name)) continue
      node.addOutput(output.name, output.type)
      const slot = node.outputs[node.outputs.length - 1]
      if (slot) {
        const slotAny = slot as Record<string, unknown>
        slotAny.color = getPortColor(output.type)
        if (output.description) slotAny._help = output.description
      }
      existingOut.add(output.name)
    }

    const slotCount = Math.max(node.inputs?.length ?? 0, node.outputs?.length ?? 0)
    const widgetCount = node.widgets?.length ?? 0
    const minHeight = 40 + slotCount * 22 + widgetCount * 20
    const curW = node.size?.[0] ?? 240
    const curH = node.size?.[1] ?? 80
    node.size = [Math.max(curW, 240), Math.max(curH, minHeight)]
  }
}

// ─── 序列化/反序列化助手 ────────────────────────────────────────────────────

/**
 * 将后端 WorkflowDefinition 转换为 LiteGraph 可识别的 serializedLGraph 格式。
 *
 * 关键：必须根据 def.links 计算每个节点 input.link / output.links 字段，
 * 否则 LGraphNode.configure() 通过 cloneObject 覆盖后，节点 slot 不会引用
 * graph.links 中的 LLink 对象，导致画布不渲染连线。
 */
export function workflowDefinitionToGraphData(def: WorkflowDefinition): serializedLGraph {
  // links 格式: [link_id, from_node, from_slot, to_node, to_slot, type]
  // 先构建 slot -> link_id 的映射
  const inputLinkMap = new Map<string, number>()     // "nodeId:slotIdx" -> link_id
  const outputLinksMap = new Map<string, number[]>()  // "nodeId:slotIdx" -> [link_id, ...]
  for (const l of def.links) {
    const linkId = l[0]
    const fromNode = l[1]
    const fromSlot = l[2]
    const toNode = l[3]
    const toSlot = l[4]
    inputLinkMap.set(`${toNode}:${toSlot}`, linkId)
    const outKey = `${fromNode}:${fromSlot}`
    const arr = outputLinksMap.get(outKey) ?? []
    arr.push(linkId)
    outputLinksMap.set(outKey, arr)
  }

  const nodes: SerializedLGraphNode[] = def.nodes.map((n) => ({
    id: n.id,
    type: n.type,
    pos: n.pos,
    // 不设置 size — 让节点构造函数根据 inputs/outputs/widgets 数量自适应计算
    flags: {},
    mode: 0,
    inputs: (n.inputs ?? []).map((p, idx) => ({
      name: p.name,
      type: p.type,
      link: inputLinkMap.get(`${n.id}:${idx}`) ?? null,
    })),
    outputs: (n.outputs ?? []).map((p, idx) => ({
      name: p.name,
      type: p.type,
      links: outputLinksMap.get(`${n.id}:${idx}`) ?? null,
    })),
    title: n.title,
    properties: n.properties ?? {},
  }))

  // LiteGraph 链接格式：[link_id, from_node, from_slot, to_node, to_slot, type]
  const links: Array<[number, number, number, number, number, string]> = def.links.map(
    (l) => [l[0], l[1], l[2], l[3], l[4], l[5]],
  )

  const maxNodeId = def.nodes.reduce((max, n) => Math.max(max, n.id), 0)
  const maxLinkId = def.links.reduce((max, l) => Math.max(max, l[0]), 0)

  return {
    last_node_id: maxNodeId,
    last_link_id: maxLinkId,
    nodes,
    links,
    groups: [],
    config: {},
    version: LiteGraph?.VERSION ?? 0.4,
  }
}

/**
 * 将 LiteGraph 序列化数据转换回后端 WorkflowDefinition 格式。
 */
export function graphDataToWorkflowNodes(
  graphData: serializedLGraph,
): { nodes: WorkflowDefinitionNode[]; links: WorkflowDefinitionLink[] } {
  const nodes: WorkflowDefinitionNode[] = graphData.nodes.map((n) => ({
    id: n.id,
    type: n.type ?? '',
    title: n.title ?? n.type ?? '',
    pos: n.pos ?? [0, 0],
    properties: n.properties ?? {},
    inputs: (n.inputs ?? []).map((p) => ({
      name: p.name,
      type: typeof p.type === 'string' ? p.type : String(p.type),
    })),
    outputs: (n.outputs ?? []).map((p) => ({
      name: p.name,
      type: typeof p.type === 'string' ? p.type : String(p.type),
    })),
  }))

  const links: WorkflowDefinitionLink[] = graphData.links.map((l) => ({
    0: l[0],
    1: l[1],
    2: l[2],
    3: l[3],
    4: l[4],
    5: l[5],
  })) as WorkflowDefinitionLink[]

  return { nodes, links }
}
