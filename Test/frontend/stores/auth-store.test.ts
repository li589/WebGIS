import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import { useAuthStore } from '@/stores/auth'

const fetchPrimaryThemePublicMock = vi.fn()
const fetchThemesPublicMock = vi.fn()

vi.mock('@/services/auth-api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/services/auth-api')>()
  return {
    ...actual,
    fetchPrimaryThemePublic: (...args: unknown[]) => fetchPrimaryThemePublicMock(...args),
    fetchThemesPublic: (...args: unknown[]) => fetchThemesPublicMock(...args),
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
  }
})

vi.mock('@/services/backend-auth', () => ({
  setBackendWriteApiKey: vi.fn(),
  clearBackendWriteApiKey: vi.fn(),
}))

describe('auth store bootstrap', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    fetchPrimaryThemePublicMock.mockResolvedValue({
      id: 1,
      slug: 'sgfs',
      name_zh: '星地融合土壤数据平台',
      full_name_zh: '星地融合土壤水分监测与干旱预警数据分析与可视化系统',
      name_en: 'Satellite-Ground Fusion Soil Data Platform',
      abbr: 'SGFS',
    })
    fetchThemesPublicMock.mockResolvedValue([
      {
        id: 1,
        slug: 'sgfs',
        name_zh: '星地融合土壤数据平台',
        full_name_zh: '星地融合土壤水分监测与干旱预警数据分析与可视化系统',
        name_en: 'Satellite-Ground Fusion Soil Data Platform',
        abbr: 'SGFS',
      },
      {
        id: 2,
        slug: 'warm-soil',
        name_zh: '暖色土壤监测平台',
        full_name_zh: '暖色土壤监测与预警平台',
        name_en: 'Warm Soil Monitoring Platform',
        abbr: 'WSMP',
      },
    ])
  })

  it('auto-logins with dev prefill when unauthenticated in DEV', async () => {
    const store = useAuthStore()
    await store.bootstrap()
    expect(store.isAuthenticated).toBe(true)
    expect(store.user?.username).toBe('admin')
    expect(store.canWrite).toBe(true)
  })
})

describe('auth store login theme preview', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    fetchPrimaryThemePublicMock.mockResolvedValue({
      id: 1,
      slug: 'sgfs',
      name_zh: '星地融合土壤数据平台',
      full_name_zh: '星地融合土壤水分监测与干旱预警数据分析与可视化系统',
      name_en: 'Satellite-Ground Fusion Soil Data Platform',
      abbr: 'SGFS',
    })
    fetchThemesPublicMock.mockResolvedValue([
      {
        id: 1,
        slug: 'sgfs',
        name_zh: '星地融合土壤数据平台',
        full_name_zh: '星地融合土壤水分监测与干旱预警数据分析与可视化系统',
        name_en: 'Satellite-Ground Fusion Soil Data Platform',
        abbr: 'SGFS',
      },
      {
        id: 2,
        slug: 'warm-soil',
        name_zh: '暖色土壤监测平台',
        full_name_zh: '暖色土壤监测与预警平台',
        name_en: 'Warm Soil Monitoring Platform',
        abbr: 'WSMP',
      },
    ])
  })

  it('initLoginPreviewSlug honors route query then session storage', async () => {
    const store = useAuthStore()
    await store.loadPrimaryTheme()
    await store.loadPublicThemes()
    store.initLoginPreviewSlug('warm-soil')
    expect(store.loginPreviewSlug).toBe('warm-soil')
    expect(store.resolvedBrand.abbr).toBe('WSMP')
    expect(store.resolvedBrand.shortName).toBe('暖色土壤监测平台')
  })

  it('initLoginPreviewSlug rejects unknown slug and falls back to primary', async () => {
    const store = useAuthStore()
    await store.loadPrimaryTheme()
    await store.loadPublicThemes()
    store.initLoginPreviewSlug('unknown-theme')
    expect(store.loginPreviewSlug).toBe('sgfs')
    expect(store.resolvedBrand.abbr).toBe('SGFS')
  })
})
