import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import { useAuthStore } from '@/stores/auth'
import { setBackendWriteApiKey } from '@/services/backend-auth'

vi.mock('@/services/auth-api', () => ({
  fetchAuthConfig: vi.fn(async () => ({
    auth_required: true,
    session_cookie_name: 'cgda_session',
    roles: ['admin', 'standard', 'demo'],
    dev_prefill: { username: 'admin', password: 'cgda-dev-admin' },
    dev_write_api_key: 'cgda-dev-write-key',
  })),
  fetchAuthMe: vi.fn(async () => {
    throw new Error('401')
  }),
  loginRequest: vi.fn(async () => ({
    id: 1,
    username: 'admin',
    role: 'admin' as const,
    enabled: true,
  })),
  logoutRequest: vi.fn(async () => undefined),
  listUsers: vi.fn(async () => []),
  createUser: vi.fn(),
  updateUser: vi.fn(),
  deleteUser: vi.fn(),
}))

vi.mock('@/services/backend-auth', () => ({
  setBackendWriteApiKey: vi.fn(),
  clearBackendWriteApiKey: vi.fn(),
}))

describe('auth store bootstrap', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('auto-logins with dev prefill when unauthenticated in DEV', async () => {
    const store = useAuthStore()
    await store.bootstrap()
    expect(store.isAuthenticated).toBe(true)
    expect(store.user?.username).toBe('admin')
    expect(store.canWrite).toBe(true)
    expect(setBackendWriteApiKey).not.toHaveBeenCalled()
  })
})
