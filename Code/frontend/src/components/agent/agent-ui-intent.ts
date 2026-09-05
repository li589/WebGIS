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
  fitChina?: () => boolean
  locateCoordinate?: (lng: number, lat: number, zoom?: number) => boolean
  setBasemap?: (sourceId: string) => boolean
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
      const block = workspace.getCatalogAddBlockReason?.(catalogId) ?? null
      if (block) {
        return { ok: false, message: block }
      }
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
    const instanceIdArg = args.instance_id != null ? String(args.instance_id).trim() : undefined
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
    const layers = workspace.activeLayers.value.filter((l) => !l.isAdminBoundary)
    if (!layers.length) {
      return {
        ok: true,
        message: '当前没有活动图层。可先在左侧图层库添加图层。',
      }
    }
    const lines = layers.map((l) => {
      const title = (l.name || l.catalogId || '').trim() || l.catalogId
      const vis = l.visible === false ? '隐藏' : '显示'
      return `- ${title}（${l.catalogId}，${vis}）`
    })
    return {
      ok: true,
      message: `当前活动图层（${layers.length}）：\n${lines.join('\n')}`,
    }
  }

  if (name === 'fit_china' || name === 'zoom_to_china') {
    const ok = handlers.fitChina?.() ?? false
    return ok
      ? { ok: true, message: '已缩放到中国全境范围' }
      : { ok: false, message: '无法缩放到中国范围（地图未就绪）' }
  }

  if (name === 'locate_coordinate' || name === 'fly_to_location' || name === 'fly_to') {
    const rawLng = args.lng ?? args.longitude ?? args.lon
    const rawLat = args.lat ?? args.latitude
    const lng = Number(rawLng)
    const lat = Number(rawLat)
    const zoom = args.zoom != null ? Number(args.zoom) : undefined

    if (Number.isNaN(lng) || Number.isNaN(lat)) {
      return { ok: false, message: '缺少有效的经纬度坐标 (lng, lat)' }
    }

    const ok = handlers.locateCoordinate?.(lng, lat, zoom) ?? false
    return ok
      ? { ok: true, message: `已定位到经纬度 (${lng.toFixed(4)}, ${lat.toFixed(4)})` }
      : { ok: false, message: '无法定位到指定坐标（地图未就绪）' }
  }

  if (name === 'switch_basemap' || name === 'set_basemap') {
    const sourceId = String(args.basemap_id ?? args.source_id ?? args.id ?? args.style ?? '').trim()
    if (!sourceId) {
      return { ok: false, message: '缺少底图标识 (basemap_id / source_id)' }
    }
    const ok = handlers.setBasemap?.(sourceId) ?? false
    return ok
      ? { ok: true, message: `已切换底图为：${sourceId}` }
      : { ok: false, message: `切换底图失败：${sourceId}` }
  }

  return { ok: false, message: `未知意图：${name}` }
}

export function executeAgentUiIntents(
  intents: AgentUiIntent[],
  handlers: AgentUiIntentHandlers = {},
): AgentUiIntentResult[] {
  return intents.map((intent) => executeAgentUiIntent(intent, handlers))
}
