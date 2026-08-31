/**
 * Workflow canvas — node CRUD / clipboard / layout ops (P1-5 split).
 */
import type { Ref, ShallowRef } from 'vue'

import type {
  NodeTemplate,
  WorkflowDefinition,
  WorkflowDefinitionLink,
  WorkflowDefinitionNode,
} from '../../../services/workflow-definition-api'
import {
  LiteGraph,
  getGraphNodes,
  graphDataToWorkflowNodes,
  syncGraphSlotsWithTemplates,
  workflowDefinitionToGraphData,
  type LGraphCanvasClass,
  type LGraphClass,
  type LGraphNodeClass,
  type serializedLGraph,
} from '../litegraph-setup'

interface ClipboardItem {
  type: string
  pos: [number, number]
  properties: Record<string, unknown>
  title?: string
}

export function useNodeOperations(
  graphInstance: ShallowRef<LGraphClass | null>,
  canvasInstance: ShallowRef<LGraphCanvasClass | null>,
  canvasRef: Ref<HTMLCanvasElement | null>,
  getNodeTemplates: () => NodeTemplate[],
  emitChange: () => void,
) {
  // 模块级剪贴板（Ctrl+C/V 用，仅当前会话有效）
  let _clipboard: ClipboardItem[] = []

  function selectAllNodes() {
    if (!graphInstance.value) return
    for (const n of getGraphNodes(graphInstance.value)) {
      n.selected = true
    }
    canvasInstance.value?.setDirty(true, true)
  }

  function copySelectedNodes() {
    if (!graphInstance.value) return
    _clipboard = getGraphNodes(graphInstance.value)
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
    const selected = getGraphNodes(graphInstance.value).filter((n) => n.selected)
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
      const nodeTemplates = getNodeTemplates()
      if (nodeTemplates.length > 0) {
        syncGraphSlotsWithTemplates(
          graph,
          nodeTemplates.map((t) => ({
            type: t.type,
            inputs: t.inputs,
            outputs: t.outputs,
            params: t.params,
          })),
        )
      }

      // 加载后重新计算节点尺寸，确保文字不重叠/不溢出
      const nodes = (
        graph as unknown as {
          _nodes?: Array<{ computeSize?: () => [number, number]; size?: [number, number] }>
        }
      )._nodes
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

  function getSerializedGraph(): {
    nodes: WorkflowDefinitionNode[]
    links: WorkflowDefinitionLink[]
  } | null {
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
    const nodes = getGraphNodes(graphInstance.value)
    if (!nodes || nodes.length === 0) return

    // 计算所有节点的边界框
    let minX = Infinity,
      minY = Infinity,
      maxX = -Infinity,
      maxY = -Infinity
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
    const scale = Math.min(scaleX, scaleY, 1.5) // 最大放大 1.5x

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
   * @param pos 可选位置 [x, y]；默认为视口中心
   * @returns 创建的节点实例
   */
  function addNodeByType(nodeType: string, pos?: [number, number]): LGraphNodeClass | null {
    if (!graphInstance.value || !LiteGraph) return null
    try {
      const node = LiteGraph.createNode<LGraphNodeClass>(nodeType)
      if (!node) {
        console.warn(`[WorkflowCanvas] Failed to create node: ${nodeType}`)
        return null
      }

      // 默认位置：视口中心附近，按节点数量偏移避免重叠
      if (pos) {
        node.pos = pos
      } else {
        // 计算视口中心（考虑 canvas 的当前缩放和平移）
        const canvas = canvasInstance.value
        if (canvas?.ds) {
          const ds = canvas.ds as unknown as { offset: [number, number]; scale: number }
          const rect = canvasRef.value?.getBoundingClientRect()
          if (rect) {
            const cx = (rect.width / 2 - ds.offset[0]) / ds.scale
            const cy = (rect.height / 2 - ds.offset[1]) / ds.scale
            // 轻微偏移避免新节点完全重叠
            const offset = getGraphNodes(graphInstance.value).length ?? 0
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

  /**
   * 将主界面时间轴窗口写入 bind_timeline 的 time_range 节点（现场改 properties + widget）。
   * @returns 实际更新的节点数
   */
  function applyBoundMainTimeline(range: { start_at: string; end_at: string }): number {
    if (!graphInstance.value) return 0
    const start = String(range.start_at || '').trim()
    const end = String(range.end_at || '').trim()
    if (!start || !end) return 0

    let changed = 0
    for (const node of getGraphNodes(graphInstance.value)) {
      const ntype = String(node.type ?? '')
      const props = { ...((node.properties ?? {}) as Record<string, unknown>) }
      const isTimeRange =
        ntype === 'data/time_range' ||
        ntype.endsWith('/time_range') ||
        props.module_name === 'time_range'
      if (!isTimeRange) continue
      if (props.bind_timeline === false || props.bind_timeline === 'false') continue
      if (String(props.start_at ?? '') === start && String(props.end_at ?? '') === end) continue

      node.properties = { ...props, start_at: start, end_at: end }
      const widgets = (node as { widgets?: Array<{ name?: string; value?: unknown }> }).widgets
      if (widgets) {
        for (const w of widgets) {
          if (w.name === 'start_at') w.value = start
          if (w.name === 'end_at') w.value = end
        }
      }
      changed += 1
    }
    if (changed > 0) {
      canvasInstance.value?.setDirty(true, true)
      emitChange()
    }
    return changed
  }

  return {
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
  }
}
