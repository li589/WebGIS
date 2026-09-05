/**
 * Agent chat helpers (P3): layer cards, markdown export, abort detection.
 */

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
  layers: Array<{ catalogId: string; instanceId?: string; name?: string; isAdminBoundary?: boolean }>
  mapPoint?: { lng: number; lat: number } | null
  timeline: { hour: number; date: Date; playing: boolean }
  viewport: {
    center?: { lng: number; lat: number } | null
    zoom?: number | null
    bbox?: [number, number, number, number] | number[] | null
  }
  basemapId: string
}): {
  active_catalog_ids: string[]
  active_layers: Array<{ catalog_id: string; instance_id?: string; name?: string }>
  map_point?: { lng: number; lat: number }
  timeline: { hour: number; date: string; playing: boolean }
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
    })),
    timeline: {
      hour: input.timeline.hour,
      date: formatLocalDateKey(input.timeline.date),
      playing: input.timeline.playing,
    },
    basemap_id: input.basemapId,
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
