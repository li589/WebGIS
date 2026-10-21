/**
 * Agent chat helpers (P3): layer cards, markdown export, abort detection.
 */

import {
  resolveSliceForInstant,
  timeListToSlices,
  type TimeStep,
} from '../../utils/temporal-interval'

export interface AgentLayerCard {
  catalog_id: string
  display_name: string
}

export interface AgentChatExportMessage {
  role: string
  text: string
  usage?: { total_tokens: number; estimated?: boolean } | null
}

/** Parse search_layers / similar tool_result JSON from steps into clickable cards. */
export function extractLayerCardsFromSteps(
  steps: Array<{ type: string; summary?: string; detail?: string | null }> | undefined,
): AgentLayerCard[] {
  if (!steps?.length) return []
  const seen = new Set<string>()
  const out: AgentLayerCard[] = []
  for (const step of steps) {
    if (step.type !== 'tool_result' || !step.detail) continue
    try {
      const data = JSON.parse(step.detail) as Record<string, unknown>
      if (!data || typeof data !== 'object' || data.ok === false) continue
      const layers = data.layers
      if (!Array.isArray(layers)) continue
      for (const item of layers) {
        if (!item || typeof item !== 'object') continue
        const rec = item as Record<string, unknown>
        const id = String(rec.layer_id || rec.catalog_id || '').trim()
        if (!id || seen.has(id)) continue
        seen.add(id)
        const name = String(rec.display_name || rec.name || id).trim() || id
        out.push({ catalog_id: id, display_name: name })
      }
    } catch {
      /* ignore */
    }
  }
  return out
}

/** Build cards from list_active_layers-style workspace rows. */
export function layerCardsFromActiveLayers(
  layers: Array<{ catalogId?: string; catalog_id?: string; name?: string }>,
): AgentLayerCard[] {
  const seen = new Set<string>()
  const out: AgentLayerCard[] = []
  for (const layer of layers) {
    const id = String(layer.catalogId || layer.catalog_id || '').trim()
    if (!id || seen.has(id)) continue
    seen.add(id)
    out.push({
      catalog_id: id,
      display_name: String(layer.name || id).trim() || id,
    })
  }
  return out
}

function formatLocalDateKey(d: Date): string {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

export function isAbortError(err: unknown): boolean {
  if (!err) return false
  if (err instanceof DOMException && err.name === 'AbortError') return true
  if (err instanceof Error) {
    if (err.name === 'AbortError') return true
    const msg = err.message.toLowerCase()
    return msg.includes('aborted') || msg.includes('abort')
  }
  return false
}

/** True when abort reason looks like request timeout (not user stop). */
export function isTimeoutAbortError(err: unknown): boolean {
  if (!isAbortError(err)) return false
  const msg = err instanceof Error ? err.message : String(err ?? '')
  return /超时|timeout/i.test(msg)
}

/**
 * User-initiated stop: only the send() AbortSignal counts.
 * Stream-internal timeout aborts must not be treated as「已停止」.
 */
export function isUserInitiatedStop(userSignal: AbortSignal): boolean {
  return userSignal.aborted
}

export function sumSessionTokens(
  messages: Array<{ usage?: { total_tokens?: number } | null }>,
): number {
  let total = 0
  for (const m of messages) {
    const n = m.usage?.total_tokens
    if (typeof n === 'number' && Number.isFinite(n)) total += n
  }
  return total
}

export function exportChatMarkdown(
  messages: AgentChatExportMessage[],
  opts?: { sessionId?: string | null; title?: string },
): string {
  const title = opts?.title || 'CGDA 地图助手会话'
  const lines: string[] = [`# ${title}`, '']
  if (opts?.sessionId) {
    lines.push(`- session_id: \`${opts.sessionId}\``)
    lines.push('')
  }
  for (const msg of messages) {
    if (msg.role === 'system' && !msg.text.trim()) continue
    const roleLabel = msg.role === 'user' ? '用户' : msg.role === 'assistant' ? '助手' : '系统'
    lines.push(`## ${roleLabel}`)
    lines.push('')
    lines.push(msg.text.trim() || '（空）')
    if (msg.usage?.total_tokens != null) {
      lines.push('')
      lines.push(`*tokens: ${msg.usage.total_tokens}${msg.usage.estimated ? '（估）' : ''}*`)
    }
    lines.push('')
  }
  return lines.join('\n').trimEnd() + '\n'
}

/** Pure builder for agent client_context (testable). */
export function buildAgentClientContextPayload(input: {
  layers: Array<{
    catalogId: string
    instanceId?: string
    name?: string
    isAdminBoundary?: boolean
    /** 运行时栅格 overlay id（imported-*），供 Agent 点查采样 */
    overlayLayerId?: string | null
  }>
  mapPoint?: { lng: number; lat: number } | null
  timeline: { hour: number; date: Date; playing: boolean }
  viewport: {
    center?: { lng: number; lat: number } | null
    zoom?: number | null
    bbox?: [number, number, number, number] | number[] | null
  }
  basemapId: string
  /** 主导图层的可用时间范围，供后端判断「切到某天有没有数据」 */
  dataRange?: { start: string; end: string; frames: number } | null
}): {
  active_catalog_ids: string[]
  active_layers: Array<{
    catalog_id: string
    instance_id?: string
    name?: string
    overlay_layer_id?: string | null
  }>
  map_point?: { lng: number; lat: number }
  timeline: {
    hour: number
    date: string
    playing: boolean
    data_range?: { start: string; end: string; frames: number }
  }
  viewport?: {
    center: [number, number]
    zoom: number
    bbox?: number[]
  }
  basemap_id: string
} {
  const layers = input.layers.filter((l) => !l.isAdminBoundary)
  const ctx: ReturnType<typeof buildAgentClientContextPayload> = {
    active_catalog_ids: layers.map((l) => l.catalogId).filter(Boolean),
    active_layers: layers.map((l) => ({
      catalog_id: l.catalogId,
      instance_id: l.instanceId,
      name: l.name || l.catalogId,
      overlay_layer_id: l.overlayLayerId || null,
    })),
    timeline: {
      hour: input.timeline.hour,
      date: formatLocalDateKey(input.timeline.date),
      playing: input.timeline.playing,
    },
    basemap_id: input.basemapId,
  }
  const range = input.dataRange
  if (range && range.start && range.end) {
    ctx.timeline.data_range = {
      start: range.start,
      end: range.end,
      frames: range.frames,
    }
  }
  if (input.mapPoint) {
    ctx.map_point = { lng: input.mapPoint.lng, lat: input.mapPoint.lat }
  }
  const c = input.viewport.center
  const z = input.viewport.zoom
  if (c && typeof z === 'number' && Number.isFinite(z)) {
    ctx.viewport = {
      center: [c.lng, c.lat],
      zoom: z,
    }
    if (input.viewport.bbox && input.viewport.bbox.length >= 4) {
      ctx.viewport.bbox = [...input.viewport.bbox].slice(0, 4)
    }
  }
  return ctx
}

export { formatLocalDateKey }

/** 内部 id 形态（imported-xxx / 纯数字长串 / 日期帧），不该出现在对话正文里。 */
export function looksLikeInternalId(text: string | null | undefined): boolean {
  const t = String(text ?? '').trim()
  if (!t) return false
  if (/^\d{6,}$/.test(t)) return true
  if (/^(imported|wf-run|wf|run|layer|overlay)-/i.test(t)) return true
  if (/^(\d{8})(_\d{8})?$/.test(t)) return true
  return false
}

/** 按 catalogId 取用户看到的图层名；取不到就给「该图层」，**绝不回 id**。 */
export function layerDisplayName(
  catalogId: string | null | undefined,
  layers: Array<{ catalogId?: string; catalog_id?: string; name?: string; displayName?: string }>,
  explicitName?: string | null,
): string {
  const explicit = String(explicitName ?? '').trim()
  if (explicit && !looksLikeInternalId(explicit)) return explicit
  const id = String(catalogId ?? '').trim()
  if (!id) return explicit || '该图层'
  for (const layer of layers) {
    const lid = String(layer.catalogId || layer.catalog_id || '').trim()
    if (lid !== id) continue
    const name = String(layer.name || layer.displayName || '').trim()
    if (name && name !== lid && !looksLikeInternalId(name)) return name
  }
  return '该图层'
}

/** 把 time_list 的原始键写成日期：20251203 → 2025-12-03；窗口键写成区间。 */
export function readableFrameLabel(key: string | null | undefined): string {
  const raw = String(key ?? '').trim()
  const m = raw.match(/^(\d{4})(\d{2})(\d{2})(?:_(\d{4})(\d{2})(\d{2}))?$/)
  if (!m) return raw
  const start = `${m[1]}-${m[2]}-${m[3]}`
  if (!m[4]) return start
  return `${start} 至 ${m[4]}-${m[5]}-${m[6]}`
}

export interface EffectiveFrame {
  /** time_list 原始键（如 20251203 或 20251203_20251212） */
  key: string
  /** 可读日期 / 区间 */
  label: string
  /** 目标时刻是否正好落在该帧的原生区间内（false = 被吸附到邻近帧） */
  nativeMatch: boolean
}

/**
 * 给定「请求的日期+钟点」，算出该图层**实际会显示哪一帧**。
 *
 * 时间轴本身不做吸附，吸附发生在渲染层（resolveSliceForInstant 挑切片）。
 * 所以 ui.currentDate 只代表"用户要的那天"，不代表"屏幕上真的在放那天的数据"。
 * 这个函数把渲染层的选择结果提前算出来，用于如实回显。
 */
export function resolveEffectiveFrame(
  timeList: string[] | null | undefined,
  date: Date,
  hour: number,
  step: TimeStep = { value: 1, unit: 'day' },
): EffectiveFrame | null {
  const list = (timeList ?? []).map((t) => String(t ?? '').trim()).filter(Boolean)
  if (!list.length) return null
  const at = new Date(date.getTime())
  at.setHours(Number.isFinite(hour) ? hour : 0, 0, 0, 0)
  const resolved = resolveSliceForInstant({ nativeStep: step, slices: timeListToSlices(list) }, at)
  if (!resolved.slice) return null
  const key = String(resolved.slice.label ?? resolved.slice.t0 ?? '').trim()
  return {
    key,
    label: readableFrameLabel(key),
    nativeMatch: resolved.nativeMatch,
  }
}

/** 主导图层的可用时间范围摘要，供后端做日期校验（首末帧 + 帧数）。 */
export function summarizeTimeRange(
  timeList: string[] | null | undefined,
): { start: string; end: string; frames: number } | null {
  const list = (timeList ?? []).map((t) => String(t ?? '').trim()).filter(Boolean)
  if (!list.length) return null
  const first = list[0]!
  const last = list[list.length - 1]!
  const start = first.split('_')[0] ?? ''
  const endParts = last.split('_')
  const end = endParts[endParts.length - 1] ?? ''
  if (!/^\d{8}$/.test(start) || !/^\d{8}$/.test(end)) return null
  return { start, end, frames: list.length }
}
