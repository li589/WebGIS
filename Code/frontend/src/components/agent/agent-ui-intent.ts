/**
 * 执行后端返回的 UI intent（地图状态仅在客户端）。
 */
import type { AgentUiIntent } from '../../services/agent-api'
import { useLayerWorkspace } from '../../stores/layers/selectors'
import { useUiStore } from '../../stores/ui'
import { isMapLinkedPalette, resolveCanonicalPaletteIdStrict } from '../map/layer-symbology'
import { formatLocalDateKey } from './agent-chat-helpers'

export interface AgentUiIntentResult {
  ok: boolean
  message: string
  /** Optional structured cards for UI (list/search results) */
  cards?: Array<{ catalog_id: string; title: string }>
}

export interface AgentUiIntentHandlers {
  fitToLayerExtent?: (instanceId: string) => boolean
  fitChina?: () => boolean
  locateCoordinate?: (lng: number, lat: number, zoom?: number) => boolean
  setBasemap?: (sourceId: string) => boolean
}

const ACTIVE_JOB = new Set(['queued', 'running', 'retry_pending', 'accepted'])

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

function parseDateArg(raw: unknown): Date | null {
  if (raw == null) return null
  const s = String(raw).trim()
  if (!s) return null
  // YYYY-MM-DD
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(s)
  if (m) {
    const d = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]))
    return Number.isNaN(d.getTime()) ? null : d
  }
  const d = new Date(s)
  return Number.isNaN(d.getTime()) ? null : d
}

export function executeAgentUiIntent(
  intent: AgentUiIntent,
  handlers: AgentUiIntentHandlers = {},
): AgentUiIntentResult {
  const workspace = useLayerWorkspace()
  const ui = useUiStore()
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
        cards: [],
      }
    }
    const cards = layers.map((l) => ({
      catalog_id: l.catalogId,
      title: (l.name || l.catalogId || '').trim() || l.catalogId,
    }))
    const lines = layers.map((l) => {
      const title = (l.name || l.catalogId || '').trim() || l.catalogId
      const vis = l.visible === false ? '隐藏' : '显示'
      return `- ${title}（${l.catalogId}，${vis}）`
    })
    return {
      ok: true,
      message: `当前活动图层（${layers.length}）：\n${lines.join('\n')}`,
      cards,
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
    if (lng < -180 || lng > 180 || lat < -90 || lat > 90) {
      return { ok: false, message: '经纬度超出有效范围 (lng∈[-180,180], lat∈[-90,90])' }
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

  if (name === 'set_timeline') {
    const hasHour = args.hour != null && args.hour !== ''
    const hasDate = args.date != null && String(args.date).trim() !== ''
    if (!hasHour && !hasDate) {
      return { ok: false, message: '请提供 hour（0–23）和/或 date（YYYY-MM-DD）' }
    }
    let hour = ui.currentHour
    if (hasHour) {
      hour = Number(args.hour)
      if (!Number.isInteger(hour) || hour < 0 || hour > 23) {
        return { ok: false, message: 'hour 须为 0–23 的整数' }
      }
    }
    if (hasDate) {
      const d = parseDateArg(args.date)
      if (!d) return { ok: false, message: 'date 格式无效，请用 YYYY-MM-DD' }
      ui.applyDateHour(d, hour)
    } else {
      ui.setHour(hour)
    }
    const dateLabel = formatLocalDateKey(ui.currentDate)
    return {
      ok: true,
      message: `已将时间轴设为 ${dateLabel} ${String(ui.currentHour).padStart(2, '0')}:00`,
    }
  }

  if (name === 'set_timeline_playing') {
    if (typeof args.playing !== 'boolean') {
      return { ok: false, message: '缺少 playing: boolean' }
    }
    if (args.playing) ui.play()
    else ui.pause()
    return {
      ok: true,
      message: args.playing ? '已开始时间轴播放' : '已暂停时间轴播放',
    }
  }

  if (name === 'remove_layer') {
    const catalogId = args.catalog_id != null ? String(args.catalog_id).trim() : undefined
    const instanceIdArg = args.instance_id != null ? String(args.instance_id).trim() : undefined
    const resolved = resolveInstanceId(catalogId, instanceIdArg)
    if (!resolved.instanceId) {
      return { ok: false, message: '未找到可移除的图层' }
    }
    const layer = workspace.activeLayers.value.find((l) => l.instanceId === resolved.instanceId)
    if (!layer) return { ok: false, message: '未找到可移除的图层' }
    const status = layer.jobLayer?.status
    if (status && ACTIVE_JOB.has(status)) {
      return {
        ok: false,
        message: `图层 ${resolved.catalogId} 仍有进行中的任务（${status}），请先取消后再移除`,
      }
    }
    workspace.removeLayer(resolved.instanceId)
    return { ok: true, message: `已移除图层 ${resolved.catalogId}` }
  }

  if (name === 'reorder_layer') {
    const action = String(args.action ?? '')
      .trim()
      .toLowerCase()
    if (action !== 'front' && action !== 'back') {
      return { ok: false, message: 'action 须为 front 或 back' }
    }
    const catalogId = args.catalog_id != null ? String(args.catalog_id).trim() : undefined
    const instanceIdArg = args.instance_id != null ? String(args.instance_id).trim() : undefined
    const resolved = resolveInstanceId(catalogId, instanceIdArg)
    if (!resolved.instanceId) {
      return { ok: false, message: '未找到可重排的图层' }
    }
    if (action === 'front') workspace.bringLayerToFront(resolved.instanceId)
    else workspace.sendLayerToBack(resolved.instanceId)
    return {
      ok: true,
      message:
        action === 'front' ? `已将 ${resolved.catalogId} 置顶` : `已将 ${resolved.catalogId} 置底`,
    }
  }

  if (name === 'set_layer_symbology') {
    const catalogId = args.catalog_id != null ? String(args.catalog_id).trim() : undefined
    const instanceIdArg = args.instance_id != null ? String(args.instance_id).trim() : undefined
    const resolved = resolveInstanceId(catalogId, instanceIdArg)
    if (!resolved.instanceId) {
      return { ok: false, message: '图层未在活动列表中' }
    }
    const display = workspace.activeLayersDisplay.value.find(
      (l) => l.instanceId === resolved.instanceId,
    )
    const layer = workspace.activeLayers.value.find((l) => l.instanceId === resolved.instanceId)
    const hasRenderHint = Boolean(display?.renderHint?.palette || display?.jobLayer)
    const supportsRecolor = Boolean(
      (layer as { supportsRecolor?: boolean } | undefined)?.supportsRecolor ||
      (display as { supportsRecolor?: boolean } | undefined)?.supportsRecolor ||
      layer?.importedRaster,
    )
    if (
      !isMapLinkedPalette({
        hasRenderHint,
        supportsRecolor,
        isImportedRaster: Boolean(layer?.importedRaster),
      })
    ) {
      return { ok: false, message: '该图层不支持前端调色板/拉伸（可能为烘焙 PNG）' }
    }
    const hasPalette = args.palette != null && String(args.palette).trim() !== ''
    const hasVmin = args.vmin != null && args.vmin !== ''
    const hasVmax = args.vmax != null && args.vmax !== ''
    if (!hasPalette && !hasVmin && !hasVmax) {
      return { ok: false, message: '请提供 palette 和/或 vmin/vmax' }
    }
    if (hasPalette) {
      const raw = String(args.palette).trim()
      const canon = resolveCanonicalPaletteIdStrict(raw) ?? raw
      workspace.setLayerPaletteOverride(resolved.instanceId, canon)
    }
    if (hasVmin || hasVmax) {
      const patch: { vmin?: number; vmax?: number } = {}
      if (hasVmin) {
        const v = Number(args.vmin)
        if (Number.isNaN(v)) return { ok: false, message: 'vmin 无效' }
        patch.vmin = v
      }
      if (hasVmax) {
        const v = Number(args.vmax)
        if (Number.isNaN(v)) return { ok: false, message: 'vmax 无效' }
        patch.vmax = v
      }
      workspace.setLayerRangeOverride(resolved.instanceId, patch)
    }
    return { ok: true, message: `已更新 ${resolved.catalogId} 符号化` }
  }

  return { ok: false, message: `未知意图：${name}` }
}

export function executeAgentUiIntents(
  intents: AgentUiIntent[],
  handlers: AgentUiIntentHandlers = {},
): AgentUiIntentResult[] {
  return intents.map((intent) => executeAgentUiIntent(intent, handlers))
}
