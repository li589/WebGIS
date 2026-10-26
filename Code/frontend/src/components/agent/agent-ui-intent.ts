/**
 * 执行后端返回的 UI intent（地图状态仅在客户端）。
 */
import type { AgentUiIntent } from '../../services/agent-api'
import { useLayerWorkspace } from '../../stores/layers/selectors'
import { safeLog } from '../../stores/log'
import { useUiStore } from '../../stores/ui'
import { isMapLinkedPalette, resolveCanonicalPaletteIdStrict } from '../map/layer-symbology'
import {
  formatLocalDateKey,
  layerDisplayName,
  readableFrameLabel,
  resolveEffectiveFrame,
} from './agent-chat-helpers'

export interface AgentUiIntentResult {
  ok: boolean
  message: string
  /** Optional structured cards for UI (list/search results) */
  cards?: Array<{ catalog_id: string; title: string }>
  /** 后端分配的命令编号，与对话里的同一条指令对应（R02 可追溯） */
  commandId?: string
}

export interface AgentUiIntentHandlers {
  fitToLayerExtent?: (instanceId: string) => boolean
  fitChina?: () => boolean
  locateCoordinate?: (lng: number, lat: number, zoom?: number) => boolean
  /** 返回 true=已切换；返回字符串=失败原因（直接展示给用户）；false=未知原因失败 */
  setBasemap?: (sourceId: string) => boolean | string
  /**
   * 图层来源中文标签（SMAP / 风云卫星…），拿不到返回空。
   *
   * 用途：报告优先4 要求日期提示写成「SMAP · 土壤水分已切到 2025-12-15」，
   * 同时让「有哪些活动图层」不出现两个无法区分的同名图层。
   */
  resolveSourceLabel?: (catalogId: string) => string | null | undefined
}

const ACTIVE_JOB = new Set(['queued', 'running', 'retry_pending', 'accepted'])

function resolveInstanceId(
  catalogId: string | undefined,
  instanceId: string | undefined,
): { instanceId: string | null; catalogId: string | null; ambiguous?: string[] } {
  const workspace = useLayerWorkspace()
  const layers = workspace.activeLayers.value
  if (instanceId) {
    const byId = layers.find((l) => l.instanceId === instanceId)
    if (byId) return { instanceId: byId.instanceId, catalogId: byId.catalogId }
  }
  if (catalogId) {
    const byCat = layers.find((l) => l.catalogId === catalogId)
    if (byCat) return { instanceId: byCat.instanceId, catalogId: byCat.catalogId }
    // 2026-10-22：助手（大模型）常把「中文显示名」甚至「图层组名」当成 catalog_id 传过来，
    // 精确匹配必然落空，用户看到的就是「隐藏/改透明度没反应」。这里按显示名兜底：
    // 唯一命中才采纳；命中多个则回报候选，绝不猜。
    const raw = catalogId.trim()
    if (raw) {
      const hits = layers.filter((l) => {
        const name = String(l.name ?? '').trim()
        if (!name || l.isAdminBoundary) return false
        return name === raw || name.includes(raw) || raw.includes(name)
      })
      if (hits.length === 1) {
        return { instanceId: hits[0].instanceId, catalogId: hits[0].catalogId }
      }
      if (hits.length > 1) {
        return {
          instanceId: null,
          catalogId: null,
          ambiguous: hits.map((l) => String(l.name ?? l.catalogId)),
        }
      }
    }
  }
  return { instanceId: null, catalogId: catalogId ?? null }
}

/** 意图文案里的图层称呼：中文名优先，绝不把 catalog_id 甩给用户。 */
function nameOf(catalogId: string | null | undefined, explicit?: unknown): string {
  const workspace = useLayerWorkspace()
  return layerDisplayName(
    catalogId,
    workspace.activeLayers.value.map((l) => ({
      catalogId: l.catalogId,
      name: l.name,
    })),
    explicit == null ? null : String(explicit),
  )
}

/**
 * 「来源 · 图层名」的写法（报告优先4 的固定模板：SMAP · 土壤水分）。
 *
 * 拿不到来源就原样返回图层名——绝不编造，也不把内部 id 顶上去；
 * 图层名本身已含来源（如「风云卫星 土壤水分」）时不重复加前缀。
 */
function withSource(
  handlers: AgentUiIntentHandlers,
  catalogId: string | null | undefined,
  title: string,
): string {
  let source: string
  try {
    source = String(handlers.resolveSourceLabel?.(String(catalogId || '')) || '').trim()
  } catch {
    return title
  }
  if (!source || source === '未标注来源' || !title) return title
  if (title.includes(source)) return title
  return `${source} · ${title}`
}

/**
 * 挑一个「用来核对日期的时间序列图层」。
 *
 * 顺序（报告第二轮 A06：回执说切到 12-15、页面却停在 01-31，就是因为
 * 回执拿「帧数最多的可见图层」算，而页面按「选中/目标图层」渲染）：
 *   ① 指令里点名的目标图层 → ② 当前选中图层 → ③ 唯一可见带帧图层 → ④ 帧数最多
 * 时间轴本身不做吸附，吸附发生在渲染层，必须拿真实 time_list 才能算准。
 */
function pickDominantTimeseries(target?: {
  catalogId?: string | null
  instanceId?: string | null
}): {
  catalogId: string
  name: string
  list: string[]
} | null {
  const workspace = useLayerWorkspace()
  const layers = workspace.activeLayers.value
  const asSeries = (layer: (typeof layers)[number]) => {
    const list = layer.importedRaster?.timeList
    if (!Array.isArray(list) || !list.length) return null
    return {
      catalogId: layer.catalogId,
      name: layerDisplayName(layer.catalogId, [{ catalogId: layer.catalogId, name: layer.name }]),
      list: list.map((t) => String(t)),
    }
  }

  const wantCatalog = String(target?.catalogId ?? '').trim()
  const wantInstance = String(target?.instanceId ?? '').trim()
  if (wantCatalog || wantInstance) {
    const hit = layers.find(
      (l) =>
        (wantInstance && l.instanceId === wantInstance) ||
        (wantCatalog && l.catalogId === wantCatalog),
    )
    if (hit) {
      const series = asSeries(hit)
      if (series) return series
    }
  }

  const selectedId = String(workspace.selectedInstanceId.value ?? '').trim()
  if (selectedId) {
    const hit = layers.find((l) => l.instanceId === selectedId)
    if (hit) {
      const series = asSeries(hit)
      if (series) return series
    }
  }

  let best: ReturnType<typeof asSeries> = null
  let visibleCount = 0
  for (const layer of layers) {
    if (layer.visible === false) continue
    if (layer.isAdminBoundary) continue
    const series = asSeries(layer)
    if (!series) continue
    visibleCount += 1
    if (!best || series.list.length > best.list.length) best = series
  }
  // 只有一个可见带帧图层时直接用；多个才退化成「帧数最多」的近似
  if (best && visibleCount >= 1) return best
  return null
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
  const result = executeAgentUiIntentCore(intent, handlers)
  const commandId = String(intent.command_id ?? '').trim()
  const enriched: AgentUiIntentResult = commandId ? { ...result, commandId } : result
  // R02：命令与其「实际执行结果」用同一个编号串起来，失败也要记
  safeLog(
    'agent-cmd',
    `${commandId || 'cmd-?'} ${intent.name} → ${enriched.ok ? '成功' : '失败'}`,
    JSON.stringify({
      target: describeIntentTarget(intent),
      message: enriched.message,
    }).slice(0, 400),
    enriched.ok ? 'info' : 'warn',
  )
  return enriched
}

/** 指令目标的可读摘要（只用于日志，不参与执行） */
function describeIntentTarget(intent: AgentUiIntent): string {
  const args = intent.args ?? {}
  const pick = (keys: string[]): string => {
    for (const k of keys) {
      const v = args[k]
      if (v != null && String(v).trim() !== '') return String(v).trim()
    }
    return ''
  }
  const hit = pick([
    'lng',
    'lon',
    'longitude',
    'latitude',
    'lat',
    'catalog_id',
    'layer_id',
    'name',
    'date',
    'time',
    'source_id',
  ])
  if (hit) return hit
  const raw = JSON.stringify(args)
  return raw && raw !== '{}' ? raw.slice(0, 80) : '-'
}

function executeAgentUiIntentCore(
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
    if (resolved.ambiguous?.length) {
      return {
        ok: false,
        message: `「${catalogId}」匹配到多个图层（${resolved.ambiguous.join('、')}），请说得更具体一点`,
      }
    }
    if (!resolved.instanceId) {
      // 2026-10-22 修正：隐藏一个当前不在地图上的图层时，绝不能「顺手把它加上」——
      // 用户看到的是「已隐藏」，实际地图上反而多出一层。只有「显示」才允许自动添加。
      if (!visible) {
        return {
          ok: false,
          message: `当前地图上没有「${nameOf(catalogId, args.display_name)}」，无需隐藏`,
        }
      }
      const block = workspace.getCatalogAddBlockReason?.(catalogId) ?? null
      if (block) {
        return { ok: false, message: block }
      }
      workspace.addLayer(catalogId)
      resolved = resolveInstanceId(catalogId, undefined)
    }
    if (!resolved.instanceId) {
      return { ok: false, message: `无法添加「${nameOf(catalogId, args.display_name)}」` }
    }
    const layer = workspace.activeLayers.value.find((l) => l.instanceId === resolved.instanceId)
    if (!layer) return { ok: false, message: `未找到「${nameOf(catalogId, args.display_name)}」` }
    if (layer.visible !== visible) {
      workspace.toggleLayerVisibility(resolved.instanceId)
    }
    workspace.selectLayer(resolved.instanceId)
    workspace.setSidebarView('active')
    const label = nameOf(catalogId, args.display_name || layer.name)
    return {
      ok: true,
      message: visible ? `已显示「${label}」` : `已隐藏「${label}」`,
    }
  }

  if (name === 'set_layer_opacity') {
    const catalogId = String(args.catalog_id ?? '').trim()
    const opacity = Number(args.opacity)
    if (!catalogId || Number.isNaN(opacity)) {
      return { ok: false, message: '缺少 catalog_id 或 opacity' }
    }
    const resolved = resolveInstanceId(catalogId, undefined)
    if (resolved.ambiguous?.length) {
      return {
        ok: false,
        message: `「${catalogId}」匹配到多个图层（${resolved.ambiguous.join('、')}），请说得更具体一点`,
      }
    }
    if (!resolved.instanceId) {
      return { ok: false, message: `「${nameOf(catalogId, args.display_name)}」还没在图层列表里` }
    }
    const clamped = Math.max(0, Math.min(1, opacity))
    workspace.setLayerOpacity(resolved.instanceId, clamped)
    return {
      ok: true,
      message: `已把「${nameOf(catalogId, args.display_name)}」的透明度调为 ${Math.round(
        clamped * 100,
      )}%`,
    }
  }

  if (name === 'fit_layer') {
    const catalogId = args.catalog_id != null ? String(args.catalog_id).trim() : undefined
    const instanceIdArg = args.instance_id != null ? String(args.instance_id).trim() : undefined
    const resolved = resolveInstanceId(catalogId, instanceIdArg)
    if (!resolved.instanceId) {
      return { ok: false, message: '未找到可定位的图层' }
    }
    const ok = handlers.fitToLayerExtent?.(resolved.instanceId) ?? false
    const fitLabel = nameOf(resolved.catalogId, args.display_name)
    return ok
      ? { ok: true, message: `已缩放到「${fitLabel}」` }
      : { ok: false, message: `「${fitLabel}」暂无可用显示范围` }
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
    // 正文只列中文名 + 显示状态；catalog_id 只留在 cards 里供点击复用
    // 来源前缀用于区分同名图层（两个「土壤水分」分属 SMAP 与风云卫星）。
    const lines = layers.map((l) => {
      const title = layerDisplayName(l.catalogId, [{ catalogId: l.catalogId, name: l.name }])
      const vis = l.visible === false ? '已隐藏' : '显示中'
      return `- ${withSource(handlers, l.catalogId, title)}（${vis}）`
    })
    return {
      ok: true,
      message: `当前有 ${layers.length} 个活动图层：\n${lines.join('\n')}`,
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
    const result = handlers.setBasemap?.(sourceId)
    // 底图 source id 是内部标识，正文不点名，后端回复会给出中文底图名。
    // 2026-10-22：切换失败要说明原因（缺密钥 / 无此底图），不再一律回「切换失败」。
    if (result === true) return { ok: true, message: '底图已切换' }
    if (typeof result === 'string') return { ok: false, message: result }
    return { ok: false, message: '底图切换失败' }
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
    let targetDate = new Date(ui.currentDate)
    if (hasDate) {
      const d = parseDateArg(args.date)
      if (!d) return { ok: false, message: 'date 格式无效，请用 YYYY-MM-DD' }
      targetDate = d
      ui.applyDateHour(d, hour)
    } else {
      ui.setHour(hour)
    }

    // 时间轴只负责「选中某个时刻」，真正的帧是渲染层按切片挑的。
    // 这里提前算出会落到哪一帧，如实回报，避免「切到 12-15」实际放的是 12-03。
    // 目标是哪个图层：指令点名 → 当前选中 → 唯一可见（报告第二轮 A06）。
    const dominant = pickDominantTimeseries({
      catalogId: String(args.catalog_id ?? args.layer_id ?? '').trim() || null,
      instanceId: String(args.instance_id ?? '').trim() || null,
    })
    if (!dominant) {
      return {
        ok: true,
        message: `时间轴已设为 ${formatLocalDateKey(targetDate)}（当前没有带时间序列的可见图层，无法核对该日是否有数据）`,
      }
    }
    const eff = resolveEffectiveFrame(dominant.list, targetDate, hour)
    if (!eff) {
      return {
        ok: false,
        message: `${formatLocalDateKey(targetDate)} 没有可用数据：${dominant.name} 还没有任何时间帧`,
      }
    }
    const requested = formatLocalDateKey(targetDate)
    const span = `${readableFrameLabel(dominant.list[0])} 至 ${readableFrameLabel(
      dominant.list[dominant.list.length - 1],
    )}`
    // 报告优先4：成功提示用固定模板「来源 · 图层名已切到 YYYY-MM-DD」，
    // 有来源就写成 `SMAP · 土壤水分已切到 2025-12-15`，没来源退回「土壤水分」。
    const dominantLabel = withSource(handlers, dominant.catalogId, dominant.name)
    const shownName = dominantLabel === dominant.name ? `「${dominant.name}」` : dominantLabel
    if (eff.nativeMatch) {
      // 报告第二轮 P2：时间块 ≠ 逐日帧，回执必须说清是「落在块内」还是「真切到了那一天」。
      const isBlock = String(eff.key ?? '').includes('_')
      if (isBlock) {
        return {
          ok: true,
          message: `${shownName}已切到 ${requested}，该日落在时间块 ${eff.label} 内（无独立逐日帧）`,
        }
      }
      // 报告优先4：动作成功也要给「图层 + 具体日期」的确定说法，
      // 不能只丢一个笼统的覆盖区间（否则用户不知道到底切到哪天）。
      const frameHint = eff.label && eff.label !== requested ? `（实际命中帧 ${eff.label}）` : ''
      return {
        ok: true,
        message: `${shownName}已切到 ${requested}${frameHint}`,
      }
    }
    return {
      ok: true,
      message: `${shownName}已设为 ${requested}，但该日没有数据，实际显示的是 ${eff.label}\n（可用范围是 ${span}，已自动对齐到最近可用帧）`,
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
    const removeLabel = nameOf(resolved.catalogId, args.display_name || layer.name)
    const status = layer.jobLayer?.status
    if (status && ACTIVE_JOB.has(status)) {
      return {
        ok: false,
        message: `「${removeLabel}」还有进行中的任务（${status}），请先取消再移除`,
      }
    }
    // 只从面板移除，不删后端产物（与侧栏 × 行为一致）
    workspace.removeLayer(resolved.instanceId, { deleteBackendFile: false })
    return { ok: true, message: `已从图层面板移除「${removeLabel}」（数据文件保留）` }
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
    const reorderLabel = nameOf(resolved.catalogId, args.display_name)
    return {
      ok: true,
      message:
        action === 'front'
          ? `已把「${reorderLabel}」移到最上层`
          : `已把「${reorderLabel}」移到最下层`,
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
    return {
      ok: true,
      message: `已更新「${nameOf(resolved.catalogId, args.display_name || layer?.name)}」的配色与拉伸`,
    }
  }

  return { ok: false, message: `未知意图：${name}` }
}

export function executeAgentUiIntents(
  intents: AgentUiIntent[],
  handlers: AgentUiIntentHandlers = {},
): AgentUiIntentResult[] {
  return intents.map((intent) => executeAgentUiIntent(intent, handlers))
}
