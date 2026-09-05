import { describe, expect, it } from 'vitest'
import {
  buildAgentClientContextPayload,
  exportChatMarkdown,
  extractLayerCardsFromSteps,
  formatLocalDateKey,
  isAbortError,
  isTimeoutAbortError,
  isUserInitiatedStop,
  layerCardsFromActiveLayers,
  sumSessionTokens,
} from '@/components/agent/agent-chat-helpers'

describe('agent-chat-helpers', () => {
  it('extracts layer cards from search_layers tool_result steps', () => {
    const cards = extractLayerCardsFromSteps([
      {
        type: 'tool_result',
        summary: 'search_layers',
        detail: JSON.stringify({
          ok: true,
          query: '降水',
          layers: [
            { layer_id: 'cmfd-precip-cn', display_name: 'CMFD 降水' },
            { layer_id: 'cmfd-precip-cn', display_name: 'dup' },
            { catalog_id: 'dem-etopo', display_name: 'DEM' },
          ],
        }),
      },
    ])
    expect(cards).toEqual([
      { catalog_id: 'cmfd-precip-cn', display_name: 'CMFD 降水' },
      { catalog_id: 'dem-etopo', display_name: 'DEM' },
    ])
  })

  it('builds cards from active layers and sums tokens', () => {
    expect(
      layerCardsFromActiveLayers([
        { catalogId: 'a', name: 'A' },
        { catalog_id: 'b' },
      ]),
    ).toEqual([
      { catalog_id: 'a', display_name: 'A' },
      { catalog_id: 'b', display_name: 'b' },
    ])
    expect(
      sumSessionTokens([
        { usage: { total_tokens: 10 } },
        { usage: { total_tokens: 5 } },
        { usage: null },
      ]),
    ).toBe(15)
  })

  it('detects abort errors and exports markdown', () => {
    expect(isAbortError(new DOMException('Aborted', 'AbortError'))).toBe(true)
    expect(isAbortError(new Error('The user aborted a request.'))).toBe(true)
    expect(isAbortError(new Error('boom'))).toBe(false)

    const md = exportChatMarkdown(
      [
        { role: 'user', text: '打开降水' },
        { role: 'assistant', text: '已打开', usage: { total_tokens: 12, estimated: true } },
      ],
      { sessionId: 'abc', title: '测试会话' },
    )
    expect(md).toContain('# 测试会话')
    expect(md).toContain('session_id: `abc`')
    expect(md).toContain('## 用户')
    expect(md).toContain('打开降水')
    expect(md).toContain('tokens: 12（估）')
  })

  it('distinguishes user stop vs timeout abort', () => {
    const c = new AbortController()
    expect(isUserInitiatedStop(c.signal)).toBe(false)
    c.abort()
    expect(isUserInitiatedStop(c.signal)).toBe(true)

    expect(isTimeoutAbortError(new DOMException('请求超时', 'AbortError'))).toBe(true)
    expect(isTimeoutAbortError(new DOMException('Aborted', 'AbortError'))).toBe(false)
    expect(isTimeoutAbortError(new DOMException('timeout', 'AbortError'))).toBe(true)
    // Timeout-shaped error alone is not a user stop; only the user signal matters
    expect(isUserInitiatedStop(new AbortController().signal)).toBe(false)
  })

  it('builds client_context with timeline / viewport / basemap (local date)', () => {
    const localDate = new Date(2024, 5, 15) // June 15 local — not UTC ISO
    const payload = buildAgentClientContextPayload({
      layers: [
        { catalogId: 'cmfd-precip-cn', instanceId: 'i1', name: '降水' },
        { catalogId: 'admin-cn', isAdminBoundary: true },
      ],
      mapPoint: { lng: 116.4, lat: 39.9 },
      timeline: { hour: 8, date: localDate, playing: true },
      viewport: {
        center: { lng: 105, lat: 35 },
        zoom: 4.5,
        bbox: [70, 15, 140, 55],
      },
      basemapId: 'tianditu-vec',
    })
    expect(payload.active_catalog_ids).toEqual(['cmfd-precip-cn'])
    expect(payload.timeline).toEqual({
      hour: 8,
      date: formatLocalDateKey(localDate),
      playing: true,
    })
    expect(payload.timeline.date).toBe('2024-06-15')
    expect(payload.viewport).toEqual({
      center: [105, 35],
      zoom: 4.5,
      bbox: [70, 15, 140, 55],
    })
    expect(payload.basemap_id).toBe('tianditu-vec')
    expect(payload.map_point).toEqual({ lng: 116.4, lat: 39.9 })
  })
})
