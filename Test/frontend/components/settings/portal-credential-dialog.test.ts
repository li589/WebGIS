// @vitest-environment jsdom
//
// M2（FY NSMC 多账号轮换）FE：
//   1) 多账号编辑区仅 NSMC 系门户显示（credential_profile=nsmc）；
//   2) 未触碰保存不动已存账号（accounts=null）；编辑后整表覆盖（清洗空字段）；
//   3) 无效账号行（既无 token 也无用户名+密码）拦截保存；
//   4) PortalCard 展示「账号 ×N」徽标。
import { afterEach, describe, expect, it, vi } from 'vitest'
import { mount, setActivePinia, createPinia } from '@/test-utils'
import type { PortalCatalogEntry } from '@/types/api-reexports'
import PortalCredentialDialog from '@/components/settings/portals/PortalCredentialDialog.vue'
import PortalCard from '@/components/settings/portals/PortalCard.vue'
import {
  deletePortalCredential,
  fetchPortalCredentials,
  upsertPortalCredential,
} from '@/services/settings-api'

vi.mock('@/services/settings-api', () => ({
  fetchPortalCredentials: vi.fn(),
  upsertPortalCredential: vi.fn(),
  deletePortalCredential: vi.fn(),
}))

const upsertMock = vi.mocked(upsertPortalCredential)
const fetchMock = vi.mocked(fetchPortalCredentials)

function makePortal(overrides: Record<string, unknown> = {}) {
  return {
    portal_id: 'cma_nsmc',
    name: '国家卫星气象中心 NSMC 门户',
    organization: 'NSMC',
    region: 'china',
    base_url: 'https://satellite.nsmc.org.cn/',
    alt_url: null,
    website: '',
    description: '',
    requires_credentials: true,
    auth_type: 'token',
    token_header: 'token',
    credential_profile: 'nsmc',
    credentials_hint: '',
    search_capability: 'none',
    builtin: true,
    effective_base_url: 'https://satellite.nsmc.org.cn/',
    base_url_overridden: false,
    effective_alt_url: null,
    has_credentials: true,
    credential_source: 'db',
    account_count: 0,
    ...overrides,
  } as unknown as PortalCatalogEntry
}

async function openDialog(portal: PortalCatalogEntry, stored: unknown = {}) {
  fetchMock.mockResolvedValue({ portal_credentials: stored } as never)
  const wrapper = mount(PortalCredentialDialog, {
    props: { visible: false, portal },
    global: { stubs: { Teleport: true } },
  })
  await wrapper.setProps({ visible: true })
  await vi.waitFor(() => expect(fetchMock).toHaveBeenCalled())
  await Promise.resolve()
  return wrapper
}

afterEach(() => {
  vi.restoreAllMocks()
  vi.clearAllMocks()
  localStorage.clear()
})

describe('PortalCredentialDialog 多账号', () => {
  it('NSMC 系门户显示多账号区，其他门户不显示', async () => {
    setActivePinia(createPinia())
    const nsmc = await openDialog(makePortal())
    expect(nsmc.find('.pc-accounts').exists()).toBe(true)

    const earthdata = await openDialog(
      makePortal({
        portal_id: 'nasa_earthdata',
        credential_profile: 'earthdata',
      }),
    )
    expect(earthdata.find('.pc-accounts').exists()).toBe(false)
  })

  it('已存账号数回填提示；未触碰保存发 accounts=null', async () => {
    setActivePinia(createPinia())
    upsertMock.mockResolvedValue({ portal_credentials: {} } as never)
    const wrapper = await openDialog(
      makePortal(),
      {
        nsmc: {
          enabled: true,
          auth_type: 'token',
          username: '',
          has_token: true,
          has_password: false,
          account_count: 3,
          source: 'db',
        },
      },
    )
    expect(wrapper.text()).toContain('已存 3 个账号')

    await wrapper.findAll('button').find((b) => b.text() === '保存')!.trigger('click')
    await vi.waitFor(() => expect(upsertMock).toHaveBeenCalledTimes(1))
    const payload = upsertMock.mock.calls[0]![1] as Record<string, unknown>
    expect(payload['accounts']).toBeNull()
  })

  it('添加行并填写后保存：整表覆盖（清洗空字段）', async () => {
    setActivePinia(createPinia())
    upsertMock.mockResolvedValue({ portal_credentials: {} } as never)
    const wrapper = await openDialog(makePortal())

    await wrapper.find('.pc-add-acc').trigger('click')
    await wrapper.find('.pc-add-acc').trigger('click')
    const rows = wrapper.findAll('.pc-account-row')
    expect(rows).toHaveLength(2)

    const inputs = rows[0]!.findAll('input')
    await inputs[0]!.setValue('user1@lab.cn')
    await inputs[1]!.setValue('secret-1')
    const row2 = wrapper.findAll('.pc-account-row')[1]!.findAll('input')
    await row2[2]!.setValue('tok-2')

    await wrapper.findAll('button').find((b) => b.text() === '保存')!.trigger('click')
    await vi.waitFor(() => expect(upsertMock).toHaveBeenCalledTimes(1))
    const payload = upsertMock.mock.calls[0]![1] as { accounts?: unknown }
    expect(payload.accounts).toEqual([
      { username: 'user1@lab.cn', token: '', password: 'secret-1' },
      { username: '', token: 'tok-2', password: '' },
    ])
  })

  it('无效账号行（全空）拦截保存并提示', async () => {
    setActivePinia(createPinia())
    const wrapper = await openDialog(makePortal())
    await wrapper.find('.pc-add-acc').trigger('click')

    await wrapper.findAll('button').find((b) => b.text() === '保存')!.trigger('click')
    await Promise.resolve()
    expect(upsertMock).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('多账号行须至少填写')
  })

  it('删完全部行后保存：发送空表清空多账号', async () => {
    setActivePinia(createPinia())
    upsertMock.mockResolvedValue({ portal_credentials: {} } as never)
    const wrapper = await openDialog(makePortal())
    await wrapper.find('.pc-add-acc').trigger('click')
    const inputs = wrapper.findAll('.pc-account-row')[0]!.findAll('input')
    await inputs[0]!.setValue('u')
    await inputs[1]!.setValue('p')
    await wrapper.find('.pc-acc-del').trigger('click')

    await wrapper.findAll('button').find((b) => b.text() === '保存')!.trigger('click')
    await vi.waitFor(() => expect(upsertMock).toHaveBeenCalledTimes(1))
    const payload = upsertMock.mock.calls[0]![1] as { accounts?: unknown }
    expect(payload.accounts).toEqual([])
  })
})

describe('PortalCard 账号数徽标', () => {
  it('account_count>0 显示「账号 ×N」；=0 不显示', () => {
    setActivePinia(createPinia())
    const withAccounts = mount(PortalCard, {
      props: { portal: makePortal({ account_count: 3 }) },
    })
    expect(withAccounts.find('.badge-accounts').text()).toBe('账号 ×3')

    const without = mount(PortalCard, {
      props: { portal: makePortal({ account_count: 0 }) },
    })
    expect(without.find('.badge-accounts').exists()).toBe(false)
  })
})

// 引用避免 TS unused 报错（vi.mock 工厂完整性检查）
void deletePortalCredential
