// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { loadUnifiedIntegrationConfigSafe } from '@/services/api-config'
import { clearLocalWriteApiKey, setLocalWriteApiKey } from '@/services/settings-local'

vi.mock('@/services/runtime-api', () => ({
  resolveApiUrl: (path: string) => path,
}))

const fetchMock = vi.fn()

beforeEach(() => {
  fetchMock.mockReset()
  vi.stubGlobal('fetch', fetchMock)
  clearLocalWriteApiKey()
})

describe('requestConfigJson auth headers', () => {
  it('attaches X-Api-Key on runtime api-config GET when key is set', async () => {
    setLocalWriteApiKey('integration-key')
    fetchMock.mockImplementation(async (url: string) => ({
      ok: true,
      status: 200,
      json: async () => {
        if (url === '/runtime/api-config') return {}
        if (url === '/gee/config') return { accounts: [] }
        if (url === '/gee/config/status') return {}
        if (url === '/gee/config/environment') return {}
        return {}
      },
    }))

    await loadUnifiedIntegrationConfigSafe()

    const runtimeCall = fetchMock.mock.calls.find(([url]) => url === '/runtime/api-config')
    expect(runtimeCall).toBeTruthy()
    const [, init] = runtimeCall as [string, RequestInit]
    expect((init.headers as Record<string, string>)['X-Api-Key']).toBe('integration-key')
  })
})
