/**
 * Workflow canvas — port hover tooltip (P1-5 split).
 */
import { computed, ref, type Ref, type ShallowRef } from 'vue'

import type { NodeTemplate } from '../../../services/workflow-definition-api'
import { buildPortTooltip } from '../port-tooltip'
import {
  getGraphNodes,
  getPortColor,
  suggestConnectorsForPortType,
  type LGraphCanvasClass,
  type LGraphClass,
  type LGraphNodeClass,
} from '../litegraph-setup'

export function usePortTooltip(
  graphInstance: ShallowRef<LGraphClass | null>,
  canvasRef: Ref<HTMLCanvasElement | null>,
  getNodeTemplates: () => NodeTemplate[],
) {
  const portTooltip = ref<{
    visible: boolean
    x: number
    y: number
    model: ReturnType<typeof buildPortTooltip> | null
    accent: string
  }>({ visible: false, x: 0, y: 0, model: null, accent: 'var(--accent)' })
  let _portTooltipKey = ''

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

  function hidePortTooltip() {
    if (!portTooltip.value.visible) return
    portTooltip.value = { visible: false, x: 0, y: 0, model: null, accent: 'var(--accent)' }
    _portTooltipKey = ''
  }

  function resolveSuggestTitles(portType: string): string[] {
    const templates = getNodeTemplates()
    return suggestConnectorsForPortType(portType).map(
      (t) => templates.find((n) => n.type === t)?.title ?? t,
    )
  }

  function clientToGraphCoords(
    e: MouseEvent,
    canvas: LGraphCanvasClass,
  ): { x: number; y: number } | null {
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
    const hitState: {
      best: {
        node: LGraphNodeClass
        direction: 'input' | 'output'
        slotIndex: number
        dist: number
      } | null
    } = { best: null }

    for (const node of getGraphNodes(graphInstance.value)) {
      const probe = (isInput: boolean, count: number) => {
        for (let i = 0; i < count; i++) {
          const out = new Float32Array(2)
          const pos = (
            node as unknown as {
              getConnectionPos?: (
                input: boolean,
                slot: number,
                out?: Float32Array,
              ) => Float32Array | number[]
            }
          ).getConnectionPos?.(isInput, i, out)
          if (!pos) continue
          const dist = Math.hypot(graphPos.x - pos[0], graphPos.y - pos[1])
          if (dist <= hit && (!hitState.best || dist < hitState.best.dist)) {
            hitState.best = {
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

    if (!hitState.best) {
      hidePortTooltip()
      return
    }

    const { node, direction, slotIndex } = hitState.best
    const slot = direction === 'input' ? node.inputs?.[slotIndex] : node.outputs?.[slotIndex]
    if (!slot) {
      hidePortTooltip()
      return
    }

    const slotAny = slot as unknown as Record<string, unknown>
    const portType = String(slot.type ?? '')
    const key = `${node.id}:${direction}:${slotIndex}`
    // Teleport 到 body 时用 client 坐标做 fixed 定位
    const screenX = e.clientX
    const screenY = e.clientY

    if (key !== _portTooltipKey) {
      _portTooltipKey = key
      const templates = getNodeTemplates()
      const tpl = templates.find((t) => t.type === node.type)
      const tplPort =
        direction === 'input'
          ? tpl?.inputs?.find((p) => p.name === slot.name)
          : tpl?.outputs?.find((p) => p.name === slot.name)
      const help =
        (typeof slotAny._help === 'string' ? slotAny._help : undefined) ?? tplPort?.description
      const connected =
        direction === 'input'
          ? (slot as { link?: number | null }).link != null
          : Array.isArray((slot as { links?: number[] | null }).links) &&
            ((slot as { links?: number[] | null }).links?.length ?? 0) > 0

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

  return {
    portTooltip,
    portTooltipStyle,
    hidePortTooltip,
    updatePortTooltipFromEvent,
  }
}
