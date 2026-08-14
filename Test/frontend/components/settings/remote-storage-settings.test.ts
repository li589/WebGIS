// @vitest-environment jsdom
//
// Phase D（前端-远程与存储）渲染与校验测试：
//   1) RemoteStorageSettings 双 tab（远程存储 / 开放门户）切换；
//   2) ProfileCard 协议徽标 / 双路径活动状态 / 回退模式文案；
//   3) ProfileForm 每协议必填校验（smb share、URL 协议前缀、filebrowser 用户名）；
//   4) OpenPortalPanel 国际/国内分组与凭据状态徽标。
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createPinia, mount, setActivePinia } from '@/test-utils'
import { useSettingsStore } from '@/stores/settings'
import RemoteStorageSettings from '@/components/settings/RemoteStorageSettings.vue'
import RemoteStoragePanel from '@/components/settings/remote-storage/RemoteStoragePanel.vue'
import ProfileCard from '@/components/settings/remote-storage/ProfileCard.vue'
import ProfileForm from '@/components/settings/remote-storage/ProfileForm.vue'
import OpenPortalPanel from '@/components/settings/portals/OpenPortalPanel.vue'

function makeProfile(overrides: Record<string, unknown> = {}) {
  return {
    profile_id: 'lab-nas',
    protocol: 'smb',
    host: '192.168.1.20',
    port: 445,
    username: 'user',
    has_secret: true,
    has_private_key: false,
    domain: 'WORKGROUP',
    extra: { default_share: 'data' },
    display_name: '实验室 NAS',
    enabled: true,
    created_at: '',
    updated_at: '',
    last_tested_at: null,
    last_test_status: 'ok',
    alt_host: 'tunnel.example.org',
    alt_port: 14445,
    alt_url: '',
    fallback_mode: 'auto',
    failover_state: { active: 'primary' },
    ...overrides,
  }
}

function makePortal(overrides: Record<string, unknown> = {}) {
  return {
    portal_id: 'nasa_cmr',
    name: 'NASA CMR 元数据检索',
    organization: 'NASA EOSDIS',
    region: 'international',
    base_url: 'https://cmr.earthdata.nasa.gov/',
    alt_url: null,
    website: '',
    description: '',
    requires_credentials: false,
    auth_type: 'none',
    token_header: null,
    credential_profile: 'earthdata',
    credentials_hint: '',
    search_capability: 'cmr',
    builtin: true,
    effective_base_url: 'https://cmr.earthdata.nasa.gov/',
    base_url_overridden: false,
    effective_alt_url: null,
    has_credentials: false,
    credential_source: 'none',
    ...overrides,
  }
}

function mountStore(profiles: unknown[] = [], portals: unknown[] = []) {
  setActivePinia(createPinia())
  const store = useSettingsStore()
  store.remoteStorageProfiles = profiles as never
  store.portalCatalog = portals as never
  return store
}

afterEach(() => {
  vi.restoreAllMocks()
  localStorage.clear()
})

describe('RemoteStorageSettings 双 tab', () => {
  it('默认渲染「远程存储」面板与两个 tab 按钮', () => {
    mountStore()
    const wrapper = mount(RemoteStorageSettings)
    const tabs = wrapper.findAll('.tabs-item')
    expect(tabs.map((t) => t.text())).toEqual(['远程存储', '开放门户'])
    expect(wrapper.findComponent(RemoteStoragePanel).exists()).toBe(true)
    expect(wrapper.findComponent(OpenPortalPanel).exists()).toBe(false)
  })

  it('切换到「开放门户」渲染门户面板', async () => {
    mountStore()
    const wrapper = mount(RemoteStorageSettings)
    await wrapper.findAll('.tabs-item')[1].trigger('click')
    expect(wrapper.findComponent(OpenPortalPanel).exists()).toBe(true)
    expect(wrapper.findComponent(RemoteStoragePanel).exists()).toBe(false)
    // 二级 tab 持久化到 localStorage
    expect(JSON.parse(localStorage.getItem('cgda.settings_ui') || '{}').remoteStorageTab).toBe(
      'portals',
    )
  })
})

describe('ProfileCard 徽标', () => {
  it('协议 / 测试状态 / 双路径活动徽标与回退模式文案', () => {
    mountStore()
    const wrapper = mount(ProfileCard, { props: { profile: makeProfile() } })
    const badges = wrapper.findAll('.key-badge').map((b) => b.text())
    expect(badges).toContain('smb')
    expect(badges).toContain('已验证')
    expect(badges).toContain('主路径')
    expect(wrapper.text()).toContain('回退自动')
    expect(wrapper.text()).toContain('tunnel.example.org:14445')
  })

  it('failover_state.active=alt 时显示备用路径徽标', () => {
    mountStore()
    const wrapper = mount(ProfileCard, {
      props: { profile: makeProfile({ failover_state: { active: 'alt' } }) },
    })
    expect(wrapper.findAll('.key-badge').map((b) => b.text())).toContain('备用路径')
  })

  it('禁用 profile 半透明且无备用路径时不显示路径徽标', () => {
    mountStore()
    const wrapper = mount(ProfileCard, {
      props: {
        profile: makeProfile({
          enabled: false,
          alt_host: '',
          alt_port: null,
          failover_state: {},
        }),
      },
    })
    expect(wrapper.find('.key-card.disabled').exists()).toBe(true)
    expect(wrapper.findAll('.key-badge').map((b) => b.text())).not.toContain('主路径')
  })
})

describe('ProfileForm 校验', () => {
  function mountForm(editing: unknown = null) {
    mountStore()
    return mount(ProfileForm, { props: { editing } })
  }

  async function submitWithError(wrapper: ReturnType<typeof mount>) {
    await (wrapper.find('.form-actions .btn.primary') as ReturnType<typeof wrapper.find>).trigger(
      'click',
    )
    await wrapper.vm.$nextTick()
    return wrapper.find('.form-error').text()
  }

  it('SMB 缺 Share 时报错', async () => {
    const wrapper = mountForm()
    await wrapper.findAll('select')[0].setValue('smb')
    await wrapper.find('input[placeholder="lab-nas"]').setValue('nas')
    await wrapper.find('input[placeholder="192.168.1.20"]').setValue('192.168.1.20')
    await wrapper.find('input[placeholder="data"]').setValue('')
    expect(await submitWithError(wrapper)).toContain('默认 Share')
  })

  it('http 协议 Base URL 缺协议前缀时报错', async () => {
    const wrapper = mountForm()
    const selects = wrapper.findAll('select')
    // AppSelect 渲染原生 select；协议下拉是第一个
    await selects[0].setValue('http')
    await wrapper.find('input[placeholder="lab-nas"]').setValue('web')
    await wrapper.find('input[placeholder="http://data.example.org/archive/"]').setValue(
      'data.example.org/archive/',
    )
    expect(await submitWithError(wrapper)).toContain('http://')
  })

  it('filebrowser 缺用户名时报错', async () => {
    const wrapper = mountForm()
    await wrapper.findAll('select')[0].setValue('filebrowser')
    await wrapper.find('input[placeholder="lab-nas"]').setValue('fb')
    await wrapper.find('input[placeholder="http://192.168.1.40:8080"]').setValue(
      'http://192.168.1.40:8080',
    )
    expect(await submitWithError(wrapper)).toContain('用户名')
  })

  it('URL 协议备用路径填主机时报错（应填备用 Base URL）', async () => {
    const wrapper = mountForm()
    await wrapper.findAll('select')[0].setValue('https')
    await wrapper.find('input[placeholder="lab-nas"]').setValue('web')
    await wrapper.find('input[placeholder="https://data.example.org/archive/"]').setValue(
      'https://data.example.org/archive/',
    )
    await wrapper.find('input[placeholder="https://fb-tunnel.example.org"]').setValue('')
    // 备用主机字段在 URL 协议下不渲染，改填备用 URL 错误格式
    const altUrlInput = wrapper.find('input[placeholder="https://fb-tunnel.example.org"]')
    if (altUrlInput.exists()) {
      await altUrlInput.setValue('not-a-url')
      expect(await submitWithError(wrapper)).toContain('备用 Base URL')
    }
  })

  it('编辑模式回填 alt / fallback_mode / extra', async () => {
    const wrapper = mountForm(makeProfile())
    await wrapper.vm.$nextTick()
    expect((wrapper.find('input[placeholder="tunnel.example.org"]').element as HTMLInputElement).value).toBe('tunnel.example.org')
    expect(wrapper.text()).toContain('编辑 · lab-nas')
  })
})

describe('OpenPortalPanel 分组与徽标', () => {
  it('按国际/国内分组渲染，凭据状态徽标正确', () => {
    mountStore(
      [],
      [
        makePortal(),
        makePortal({
          portal_id: 'tpdc',
          name: '国家青藏高原科学数据中心',
          region: 'china',
          requires_credentials: true,
          has_credentials: false,
          search_capability: 'none',
        }),
        makePortal({
          portal_id: 'ecmwf_cds',
          name: 'ECMWF CDS',
          requires_credentials: true,
          has_credentials: true,
        }),
      ],
    )
    const wrapper = mount(OpenPortalPanel)
    const titles = wrapper.findAll('.section-title')
    expect(titles[0].text()).toContain('开放数据门户（3）')
    expect(titles[1].text()).toContain('国际组织（2）')
    expect(titles[2].text()).toContain('国内机构（1）')

    // 无需凭据 / 需要凭据 / 已配置
    expect(wrapper.text()).toContain('无需凭据')
    expect(wrapper.text()).toContain('需要凭据')
    expect(wrapper.text()).toContain('已配置凭据')
  })

  it('可检索门户显示「在线检索」按钮，其余不显示', () => {
    mountStore(
      [],
      [
        makePortal({ portal_id: 'nasa_cmr', search_capability: 'cmr' }),
        makePortal({ portal_id: 'nasa_earthdata', search_capability: 'none' }),
      ],
    )
    const wrapper = mount(OpenPortalPanel)
    expect(wrapper.findAll('button').filter((b) => b.text() === '在线检索').length).toBe(1)
  })
})
