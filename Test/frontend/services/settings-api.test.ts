// @vitest-environment jsdom
/**
 * F2（前端 settings 服务层重构）回归测试。
 * 固化共享 `settingsFetch` 适配器行为：
 *  - 写鉴权头注入（GET 无密钥 / 敏感 GET 有密钥 / 写方法有密钥 / 写方法无密钥）—— P0
 *  - 错误归一化（非 2xx → `Settings API failed: <status> <path> — <detail>`）—— P0
 *  - 请求体包裹（open-data-presets / remote-layer-uris 必填包裹字段）—— P1
 *  - 响应信封强类型透传（deleteApiKey / fetchRuntimeConfig）—— P1/P2
 *
 * 密钥走真实 `settings-local`（jsdom 提供 sessionStorage），`fetch` 与 `resolveApiUrl`
 * 由本文件桩化，保证断言确定性。
 */

import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  deleteApiKey,
  fetchGeneralConfig,
  fetchRuntimeConfig,
  updateApiKey,
  updateOpenDataPresets,
  updateRemoteLayerUris,
} from '@/services/settings-api'
import { clearLocalWriteApiKey, setLocalWriteApiKey } from '@/services/settings-local'

vi.mock('@/services/runtime-api', () => ({
  resolveApiUrl: (path: string) => path,
}))

function okResponse(body: unknown, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
    text: async () => (typeof body === 'string' ? body : JSON.stringify(body)),
  }
}

function errResponse(status: number, detail: string) {
  return {
    ok: false,
    status,
    json: async () => ({ detail }),
    text: async () => detail,
  }
}

const fetchMock = vi.fn()

beforeEach(() => {
  fetchMock.mockReset()
  vi.stubGlobal('fetch', fetchMock)
  clearLocalWriteApiKey()
})

describe('settingsFetch header injection (F2/P0)', () => {
  it('GET omits X-Api-Key when no write key is set', async () => {
    fetchMock.mockResolvedValue(okResponse({}))
    await fetchGeneralConfig()
    const [, init] = fetchMock.mock.calls[0] as [string, any]
    expect(init.headers['X-Api-Key']).toBeUndefined()
  })

  it('sensitive GET adds X-Api-Key when a write key is present', async () => {
    setLocalWriteApiKey('secret-key')
    fetchMock.mockResolvedValue(okResponse({}))
    await fetchGeneralConfig()
    const [, init] = fetchMock.mock.calls[0] as [string, any]
    expect(init.headers['X-Api-Key']).toBe('secret-key')
  })

  it('PUT write adds X-Api-Key and sets Content-Type when key present', async () => {
    setLocalWriteApiKey('secret-key')
    fetchMock.mockResolvedValue(okResponse({ key_name: 'k', enabled: true }))
    await updateApiKey('k', { enabled: true } as any)
    const [url, init] = fetchMock.mock.calls[0] as [string, any]
    expect(url).toBe('/config/api-keys/k')
    expect(init.method).toBe('PUT')
    expect(init.headers['X-Api-Key']).toBe('secret-key')
    expect(init.headers['Content-Type']).toBe('application/json')
  })

  it('PUT write omits X-Api-Key when no key is set', async () => {
    clearLocalWriteApiKey()
    fetchMock.mockResolvedValue(okResponse({ key_name: 'k', enabled: true }))
    await updateApiKey('k', { enabled: true } as any)
    const [, init] = fetchMock.mock.calls[0] as [string, any]
    expect(init.headers['X-Api-Key']).toBeUndefined()
  })
})

describe('settingsFetch error normalization (F2/P0)', () => {
  it('throws a normalized error with status, path and detail on non-ok', async () => {
    fetchMock.mockResolvedValue(errResponse(500, 'boom'))
    await expect(fetchGeneralConfig()).rejects.toThrow(
      /Settings API failed: 500 \/config\/general — boom/,
    )
  })

  it('surfaces detail from the error body for a 422', async () => {
    fetchMock.mockResolvedValue(errResponse(422, 'field required'))
    await expect(updateApiKey('k', { enabled: true } as any)).rejects.toThrow(/422/)
  })
})

describe('settingsFetch wrapped request bodies (F2/P1)', () => {
  it('updateOpenDataPresets sends the { open_data_presets } envelope', async () => {
    fetchMock.mockResolvedValue(okResponse({ ok: true }))
    await updateOpenDataPresets({ foo: 'bar' })
    const [, init] = fetchMock.mock.calls[0] as [string, any]
    expect(init.method).toBe('PUT')
    expect(JSON.parse(init.body)).toEqual({ open_data_presets: { foo: 'bar' } })
  })

  it('updateRemoteLayerUris sends the { remote_layer_data_uris } envelope', async () => {
    fetchMock.mockResolvedValue(okResponse({ ok: true }))
    const uris = [{ id: 'a', uris: ['x'] }]
    await updateRemoteLayerUris(uris as any)
    const [, init] = fetchMock.mock.calls[0] as [string, any]
    expect(JSON.parse(init.body)).toEqual({ remote_layer_data_uris: uris })
  })
})

describe('settingsFetch typed responses (F2/P1-P2)', () => {
  it('deleteApiKey returns the ApiKeyDeletedResponse envelope', async () => {
    fetchMock.mockResolvedValue(okResponse({ deleted: true, key_name: 'k' }))
    const res = await deleteApiKey('k')
    expect(res).toEqual({ deleted: true, key_name: 'k' })
  })

  it('fetchRuntimeConfig returns the RuntimeConfigSnapshotResponse', async () => {
    const snapshot = { scopes: { backend: { items: [] } }, version: '1' }
    fetchMock.mockResolvedValue(okResponse(snapshot))
    const res = await fetchRuntimeConfig()
    expect(res).toEqual(snapshot)
  })
})
