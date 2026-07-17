/**
 * LiteGraph.js 集成助手
 *
 * 处理 LiteGraph.js 库的导入与初始化。
 * 该库使用 IIFE + CommonJS 模式，需要特殊处理才能在 ESM 环境中工作。
 */
import 'litegraph.js/css/litegraph.css'
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

let _nodeTypesRegistered = false

/**
 * 注册所有自定义节点类型。
 *
 * 每个节点类型对应后端 NodeTemplate 中的一种 type。
 * 节点类型的注册是幂等的，重复注册会被 LiteGraph 忽略。
 */
export function registerWorkflowNodeTypes(
  templates: Array<{
    type: string
    title: string
    inputs: Array<{ name: string; type: string }>
    outputs: Array<{ name: string; type: string }>
    params?: Array<{ key: string; type: string; default?: unknown; options?: string[] }>
  }>,
): void {
  if (_nodeTypesRegistered) return
  if (!LiteGraph) {
    console.warn('[litegraph-setup] LiteGraph not available, skipping node registration')
    return
  }

  for (const template of templates) {
    // 跳过已注册的类型
    if (LiteGraph.registered_node_types[template.type]) continue

    const tpl = template
    // 按引擎类别确定节点颜色
    const engineColor = getEngineColor(tpl.type)

    class WorkflowNode extends (LGraphNode as unknown as typeof LGraphNodeClass) {
      static title = tpl.title
      static type = tpl.type

      constructor(title?: string) {
        super(title ?? tpl.title)
        this.type = tpl.type

        // 按引擎类别设置节点颜色
        this.color = engineColor.nodeBg
        this.bgcolor = engineColor.nodeHeader
        this.boxcolor = engineColor.accent

        // 显式启用交互属性：允许拖动、允许右下角缩放
        this.resizable = true
        // allow_interaction 不在 flags 类型定义中但运行时 LiteGraph 会读取，用 as 断言
        ;(this.flags as Record<string, unknown>).allow_interaction = true

        // 添加输入端口（带类型颜色）
        for (const input of tpl.inputs) {
          this.addInput(input.name, input.type)
          const slot = this.inputs[this.inputs.length - 1]
          if (slot) (slot as Record<string, unknown>).color = getPortColor(input.type)
        }

        // 添加输出端口（带类型颜色）
        for (const output of tpl.outputs) {
          this.addOutput(output.name, output.type)
          const slot = this.outputs[this.outputs.length - 1]
          if (slot) (slot as Record<string, unknown>).color = getPortColor(output.type)
        }

        // 添加参数 widgets
        if (tpl.params) {
          for (const param of tpl.params) {
            const widgetType = mapParamTypeToWidget(param.type)
            // 根据 param.type 决定默认值，避免 number widget 得到空字符串
            let defaultValue: unknown = param.default ?? getDefaultForType(param.type)
            // array 类型：数组转逗号分隔字符串（widget 为 text）
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

        // 设置合理尺寸：标题栏 + 输入/输出插槽 + 参数 widget
        const slotCount = Math.max(tpl.inputs.length, tpl.outputs.length)
        const widgetCount = tpl.params?.length ?? 0
        const minHeight = 40 + slotCount * 22 + widgetCount * 20
        this.size = [220, Math.max(80, minHeight)]
      }

      /** 端口连接类型校验：拒绝类型不兼容的连接 */
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
  }

  _nodeTypesRegistered = true
}

/** 引擎颜色配置 */
interface EngineColor {
  nodeBg: string      // 节点背景色
  nodeHeader: string  // 节点标题栏色
  accent: string      // 强调色（选中边框等）
}

/** 按节点类型前缀返回引擎配色 */
function getEngineColor(nodeType: string): EngineColor {
  if (nodeType.startsWith('weather/')) {
    return { nodeBg: '#1a2230', nodeHeader: '#2a4a5a', accent: '#ffb84d' }
  }
  if (nodeType.startsWith('python_provider/')) {
    return { nodeBg: '#1a2a1e', nodeHeader: '#2a4a38', accent: '#78ffa0' }
  }
  if (nodeType.startsWith('gee/')) {
    return { nodeBg: '#1a2030', nodeHeader: '#3a2e5a', accent: '#5ad5ff' }
  }
  // general / common
  return { nodeBg: '#1a2740', nodeHeader: '#1a2540', accent: '#88dfff' }
}

function mapParamTypeToWidget(paramType: string): string {
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
 *   - data:* 之间不同子类型：禁止
 *   - value:* / geometry:* 不同子类型：禁止
 *   - 其他不同类型：禁止
 */
export function checkConnectionValid(inputType: string, outputType: string): boolean {
  if (inputType === outputType) return true
  // data 通用类型与 data:* 子类型互连（向后兼容）
  if (inputType === 'data' || outputType === 'data') return true
  // 同前缀但不同子类型：禁止
  if (inputType.startsWith('data:') && outputType.startsWith('data:')) return false
  if (inputType.startsWith('value:') && outputType.startsWith('value:')) return false
  if (inputType.startsWith('geometry:') && outputType.startsWith('geometry:')) return false
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
  if (type === 'value:number' || type === 'value:string') return '#ffd5a8' // 浅黄
  if (type === 'value:time_range') return '#ff8fb1' // 粉色
  if (type === 'geometry:bbox') return '#ff6b6b' // 红色
  return '#6e8ba0' // 默认灰
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
