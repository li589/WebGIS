/**
 * Manifest chunkedUpload：mock fetch 覆盖续传与并发调度（轻量）。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

describe('chunkedUpload manifest', () => {
  const fetchMock = vi.fn()
  const store = new Map<string, string>()

  beforeEach(() => {
    fetchMock.mockReset()
    store.clear()
    vi.stubGlobal('fetch', fetchMock)
    const storage = {
      getItem: (k: string) => store.get(k) ?? null,
      setItem: (k: string, v: string) => {
        store.set(k, v)
      },
      removeItem: (k: string) => {
        store.delete(k)
      },
      clear: () => store.clear(),
    }
    vi.stubGlobal('localStorage', storage)
    vi.stubGlobal('sessionStorage', storage)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('inits resumable, uploads missing chunks, completes', async () => {
    const { chunkedUpload } = await import('@/data-manager/core/api')
    const bytes = new Uint8Array(90).fill(1)
    const file = new File([bytes], 'demo.tif', { type: 'image/tiff' })
    const uploadId = 'up-manifest-1'
    const phases: string[] = []

    fetchMock.mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      const method = (init?.method || 'GET').toUpperCase()
      if (url.includes('/import/upload/resumable/init') && method === 'POST') {
        return new Response(
          JSON.stringify({
            upload_id: uploadId,
            chunk_size: 40,
            total_chunks: 3,
          }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        )
      }
      if (url.includes('/chunk/') && method === 'POST') {
        return new Response(JSON.stringify({ ok: true }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        })
      }
      if (url.includes('/status') && method === 'GET') {
        return new Response(
          JSON.stringify({
            mode: 'manifest',
            missing_chunks: [],
            total_chunks: 3,
            complete: false,
          }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        )
      }
      if (url.includes('/resumable/complete') && method === 'POST') {
        return new Response(
          JSON.stringify({ upload_id: uploadId, filename: 'demo.tif', size: 90 }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        )
      }
      return new Response(`unexpected ${method} ${url}`, { status: 500 })
    })

    const result = await chunkedUpload(file, {
      onPhase: (p) => phases.push(p),
    })
    expect(result.upload_id).toBe(uploadId)
    expect(phases.some((p) => /SHA-256|块/.test(p))).toBe(true)
    const chunkCalls = fetchMock.mock.calls.filter(([input, init]) => {
      const url = String(input)
      const method = ((init as RequestInit | undefined)?.method || 'GET').toUpperCase()
      return url.includes('/chunk/') && method === 'POST'
    })
    expect(chunkCalls.length).toBe(3)
  })
})
