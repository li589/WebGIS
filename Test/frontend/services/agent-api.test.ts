import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/services/_http', () => ({
  requestJson: vi.fn(),
  resolveApiUrl: (path: string) => path,
}))

vi.mock('@/services/session-expired', () => ({
  handleSessionExpired: vi.fn(),
  isAuthBootstrapPath: () => false,
}))

vi.mock('@/services/backend-auth', () => ({
  withWriteAuthHeaders: (headers: HeadersInit) => headers,
}))

import { requestJson } from '@/services/_http'
import {
  createAgentProfile,
  fetchAgentConfig,
  refreshAgentModels,
  setActiveAgentProfile,
  streamAgentChat,
  useGlobalAgentProfile,
} from '@/services/agent-api'

const mockRequest = vi.mocked(requestJson)

describe('agent-api profiles isolation', () => {
  beforeEach(() => {
    mockRequest.mockReset()
  })

  it('fetchAgentConfig returns isolation fields', async () => {
    mockRequest.mockResolvedValueOnce({
      active_profile_id: 'demo',
      active_scope: 'global',
      can_manage_global: true,
      can_manage_personal: true,
      profiles: [
        {
          id: 'demo',
          name: '演示',
          provider_kind: 'demo',
          protocol: 'demo',
          base_url: '',
          model: 'demo-rules',
          context_window_input: 4000,
          context_window_output: 2000,
          scope: 'global',
          enabled: true,
          has_api_key: false,
        },
      ],
      presets: [],
    })
    const bundle = await fetchAgentConfig()
    expect(bundle.can_manage_global).toBe(true)
    expect(bundle.active_scope).toBe('global')
    expect(bundle.profiles[0]?.scope).toBe('global')
  })

  it('createAgentProfile posts scope', async () => {
    mockRequest.mockResolvedValueOnce({
      id: 'abc',
      name: 'Ollama',
      provider_kind: 'ollama',
      protocol: 'openai',
      base_url: 'http://127.0.0.1:11434/v1',
      model: 'qwen2.5',
      context_window_input: 8192,
      context_window_output: 4096,
      scope: 'personal',
      enabled: false,
      has_api_key: false,
    })
    await createAgentProfile({ preset_id: 'ollama', scope: 'personal' })
    expect(mockRequest).toHaveBeenCalledWith('/agent/config/profiles', {
      method: 'POST',
      body: JSON.stringify({ preset_id: 'ollama', scope: 'personal' }),
    })
  })

  it('setActiveAgentProfile includes scope', async () => {
    mockRequest.mockResolvedValueOnce({
      active_profile_id: 'x',
      active_scope: 'personal',
      can_manage_global: false,
      can_manage_personal: true,
      profiles: [],
      presets: [],
    })
    await setActiveAgentProfile('x', 'personal')
    expect(mockRequest).toHaveBeenCalledWith('/agent/config/active', {
      method: 'POST',
      body: JSON.stringify({ profile_id: 'x', scope: 'personal' }),
    })
  })

  it('useGlobalAgentProfile posts endpoint', async () => {
    mockRequest.mockResolvedValueOnce({
      active_profile_id: 'demo',
      active_scope: 'global',
      can_manage_global: false,
      can_manage_personal: true,
      profiles: [],
      presets: [],
    })
    await useGlobalAgentProfile()
    expect(mockRequest).toHaveBeenCalledWith('/agent/config/use-global', {
      method: 'POST',
      body: '{}',
    })
  })

  it('refreshAgentModels posts draft base_url and api_key', async () => {
    mockRequest.mockResolvedValueOnce({
      profile_id: 'p1',
      models: ['m1', 'm2'],
      manual: false,
    })
    await refreshAgentModels('p1', 'global', {
      base_url: ' http://127.0.0.1:11434/v1 ',
      api_key: ' sk-x ',
    })
    expect(mockRequest).toHaveBeenCalledWith('/agent/models/refresh', {
      method: 'POST',
      body: JSON.stringify({
        profile_id: 'p1',
        scope: 'global',
        base_url: 'http://127.0.0.1:11434/v1',
        api_key: 'sk-x',
      }),
    })
  })
})

describe('streamAgentChat SSE', () => {
  beforeEach(() => {
    vi.unstubAllGlobals()
  })

  it('parses token/step/done events', async () => {
    const sse = [
      'event: step\ndata: {"type":"thought","summary":"演示"}\n\n',
      'event: token\ndata: {"text":"你好"}\n\n',
      'event: token\ndata: {"text":"世界"}\n\n',
      'event: done\ndata: {"session_id":"s1","reply":"你好世界","ui_intents":[],"provider":"demo","steps":[]}\n\n',
    ].join('')
    const stream = new ReadableStream({
      start(controller) {
        controller.enqueue(new TextEncoder().encode(sse))
        controller.close()
      },
    })
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        body: stream,
        status: 200,
      }),
    )

    const tokens: string[] = []
    const steps: string[] = []
    const res = await streamAgentChat(
      { message: 'hi' },
      {
        onToken: (t) => tokens.push(t),
        onStep: (s) => steps.push(s.summary),
      },
    )
    expect(tokens.join('')).toBe('你好世界')
    expect(steps).toEqual(['演示'])
    expect(res.reply).toBe('你好世界')
    expect(res.session_id).toBe('s1')
  })

  it('throws on error event', async () => {
    const sse = 'event: error\ndata: {"detail":"上游失败","status_code":502}\n\n'
    const stream = new ReadableStream({
      start(controller) {
        controller.enqueue(new TextEncoder().encode(sse))
        controller.close()
      },
    })
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        body: stream,
        status: 200,
      }),
    )
    await expect(streamAgentChat({ message: 'x' })).rejects.toThrow('上游失败')
  })
})
