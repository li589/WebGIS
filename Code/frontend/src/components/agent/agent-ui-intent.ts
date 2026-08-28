/**
 * 执行后端返回的 UI intent（地图状态仅在客户端）。
 */
import type { AgentUiIntent } from '../../services/agent-api'
import { useLayerWorkspace } from '../../stores/layers/selectors'

export interface AgentUiIntentResult {
  ok: boolean
  message: string
}

export interface AgentUiIntentHandlers {
  fitToLayerExtent?: (instanceId: string) => boolean
}

function resolveInstanceId(
  catalogId: string | undefined,
  instanceId: string | undefined,
): { instanceId: string | null; catalogId: string | null } {
  const workspace = useLayerWorkspace()
  const layers = workspace.activeLayers.value
  if (instanceId) {
    const byId = layers.find((l) => l.instanceId === instanceId)
    if (byId) return { instanceId: byId.instanceId, catalogId: byId.catalogId }
  }
  if (catalogId) {
    const byCat = layers.find((l) => l.catalogId === catalogId)
    if (byCat) return { instanceId: byCat.instanceId, catalogId: byCat.catalogId }
  }
  return { instanceId: null, catalogId: catalogId ?? null }
}

export function executeAgentUiIntent(
  intent: AgentUiIntent,
  handlers: AgentUiIntentHandlers = {},
): AgentUiIntentResult {
  const workspace = useLayerWorkspace()
  const name = intent.name
  const args = intent.args ?? {}

  if (name === 'set_layer_visibility') {
    const catalogId = String(args.catalog_id ?? '').trim()
    const visible = Boolean(args.visible)
    if (!catalogId) return { ok: false, message: '缺少 catalog_id' }

    let resolved = resolveInstanceId(catalogId, undefined)
    if (!resolved.instanceId) {
      workspace.addLayer(catalogId)
      resolved = resolveInstanceId(catalogId, undefined)
    }
    if (!resolved.instanceId) {
      return { ok: false, message: `无法添加图层 ${catalogId}` }
    }
    const layer = workspace.activeLayers.value.find((l) => l.instanceId === resolved.instanceId)
    if (!layer) return { ok: false, message: `未找到图层 ${catalogId}` }
    if (layer.visible !== visible) {
      workspace.toggleLayerVisibility(resolved.instanceId)
    }
    workspace.selectLayer(resolved.instanceId)
    workspace.setSidebarView('active')
    return {
      ok: true,
      message: visible ? `已显示 ${catalogId}` : `已隐藏 ${catalogId}`,
    }
  }

  if (name === 'set_layer_opacity') {
    const catalogId = String(args.catalog_id ?? '').trim()
    const opacity = Number(args.opacity)
    if (!catalogId || Number.isNaN(opacity)) {
      return { ok: false, message: '缺少 catalog_id 或 opacity' }
    }
    const resolved = resolveInstanceId(catalogId, undefined)
    if (!resolved.instanceId) {
      return { ok: false, message: `图层未在活动列表中：${catalogId}` }
    }
    workspace.setLayerOpacity(resolved.instanceId, Math.max(0, Math.min(1, opacity)))
    return { ok: true, message: `已设置 ${catalogId} 透明度` }
  }

  if (name === 'fit_layer') {
    const catalogId = args.catalog_id != null ? String(args.catalog_id).trim() : undefined
    const instanceIdArg =
      args.instance_id != null ? String(args.instance_id).trim() : undefined
    const resolved = resolveInstanceId(catalogId, instanceIdArg)
    if (!resolved.instanceId) {
      return { ok: false, message: '未找到可定位的图层' }
    }
    const ok = handlers.fitToLayerExtent?.(resolved.instanceId) ?? false
    return ok
      ? { ok: true, message: '已缩放到图层' }
      : { ok: false, message: '该图层暂无可用显示范围' }
  }

  if (name === 'list_active_layers') {
    return { ok: true, message: '已使用客户端活动图层上下文' }
  }

  return { ok: false, message: `未知意图：${name}` }
}

export function executeAgentUiIntents(
  intents: AgentUiIntent[],
  handlers: AgentUiIntentHandlers = {},
): AgentUiIntentResult[] {
  return intents.map((intent) => executeAgentUiIntent(intent, handlers))
}
