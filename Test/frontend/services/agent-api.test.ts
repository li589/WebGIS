import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/services/_http', () => ({
  requestJson: vi.fn(),
}))

import { requestJson } from '@/services/_http'
import {
  createAgentProfile,
  fetchAgentConfig,
  setActiveAgentProfile,
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
})
