// @vitest-environment jsdom
//
// Phase E（前端-数据源）渲染与校验测试：
//   1) DataSourceSettings 双 tab（本地数据源 / 远程数据源）切换 + localStorage 持久化；
//   2) AvailableDatasetsPanel 来源筛选 / 内置条目保护（无删除按钮）/ 空态引导；
//   3) RemoteDataSourcesPanel 动态分组（存储源 / 国际门户 / 国内门户）与空态；
//   4) PathConfigSection 只读展示（修改入口收敛至部署配置中心）；
//   5) DatasetFormDialog 新增必填校验与内置条目锁定。
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createPinia, mount, setActivePinia } from '@/test-utils'
import { useSettingsStore } from '@/stores/settings'
import DataSourceSettings from '@/components/settings/DataSourceSettings.vue'
import LocalDataSourcePanel from '@/components/settings/data-source/LocalDataSourcePanel.vue'
import RemoteDataSourcesPanel from '@/components/settings/data-source/RemoteDataSourcesPanel.vue'
import AvailableDatasetsPanel from '@/components/settings/data-source/AvailableDatasetsPanel.vue'
import PathConfigSection from '@/components/settings/data-source/PathConfigSection.vue'
import DatasetFormDialog from '@/components/settings/data-source/DatasetFormDialog.vue'

function makeDataset(overrides: Record<string, unknown> = {}) {
  return {
    dataset_id: 'ds-1',
    logical_name: 'Soil_Moisture',
    path: 'I:/Geograph_DataSet/Soil_Moisture',
    file_format: 'HDF5',
    variables: ['SM'],
    time_range: '',
    resolution: '9km',
    tags: ['土壤水分'],
    description: '',
    source: 'manual',
    enabled: true,
    file_count: 12,
    last_scanned_at: null,
    created_at: '',
    updated_at: '',
    ...overrides,
  }
}

function makeProfile(overrides: Record<string, unknown> = {}) {
  return {
    profile_id: 'lab-nas',
    protocol: 'sftp',
    host: '192.168.1.10',
    port: 22,
    username: 'user',
    has_secret: true,
    has_private_key: false,
    display_name: '实验室 NAS',
    enabled: true,
    created_at: '',
    updated_at: '',
    last_tested_at: null,
    last_test_status: 'ok',
    alt_host: '',
    alt_port: null,
    alt_url: '',
    fallback_mode: 'off',
    failover_state: null,
    ...overrides,
  }
}

function makePortal(overrides: Record<string, unknown> = {}) {
  return {
    portal_id: 'tpdc',
    name: '国家青藏高原科学数据中心',
    organization: 'TPDC',
    region: 'china',
    base_url: 'https://data.tpdc.ac.cn/',
    alt_url: null,
    website: '',
    description: '',
    requires_credentials: true,
    auth_type: 'token',
    token_header: 'X-Token',
    credential_profile: '',
    credentials_hint: '',
    search_capability: 'none',
    builtin: true,
    effective_base_url: 'https://data.tpdc.ac.cn/',
    base_url_overridden: false,
    effective_alt_url: null,
    has_credentials: false,
    credential_source: 'none',
    ...overrides,
  }
}

function mountStore(opts: { datasets?: unknown[]; profiles?: unknown[]; portals?: unknown[] } = {}) {
  setActivePinia(createPinia())
  const store = useSettingsStore()
  store.dataSourceConfig = {
    storage_backend: 'minio',
    data_root: 'I:/Geograph_DataSet',
    output_root: 'I:/Geograph_DataSet/ProjectOutput',
    env_data_root: 'I:/Geograph_DataSet',
    env_output_root: null,
    pending_restart: false,
    ui_restart_enabled: false,
    download_source_root: '',
    download_real_fetch_enabled: false,
    tile_proxy_enabled: true,
    tile_proxy_cache_ttl_seconds: 600,
    static_cache_root: 'I:/static-cache',
    cache_dir: '',
  } as never
  store.availableDatasets = (opts.datasets ?? []) as never
  store.remoteStorageProfiles = (opts.profiles ?? []) as never
  store.portalCatalog = (opts.portals ?? []) as never
  return store
}

afterEach(() => {
  vi.restoreAllMocks()
  localStorage.clear()
})

describe('DataSourceSettings 双 tab', () => {
  it('默认渲染「本地数据源」面板与两个 tab 按钮', () => {
    mountStore()
    const wrapper = mount(DataSourceSettings)
    const tabs = wrapper.findAll('.tabs-item')
    expect(tabs.map((t) => t.text())).toEqual(['本地数据源', '远程数据源'])
    expect(wrapper.findComponent(LocalDataSourcePanel).exists()).toBe(true)
    expect(wrapper.findComponent(RemoteDataSourcesPanel).exists()).toBe(false)
  })

  it('切换到「远程数据源」渲染远程面板并持久化', async () => {
    mountStore()
    const wrapper = mount(DataSourceSettings)
    await wrapper.findAll('.tabs-item')[1].trigger('click')
    expect(wrapper.findComponent(RemoteDataSourcesPanel).exists()).toBe(true)
    expect(wrapper.findComponent(LocalDataSourcePanel).exists()).toBe(false)
    expect(JSON.parse(localStorage.getItem('cgda.settings_ui') || '{}').dataSourceTab).toBe('remote')
  })
})

describe('AvailableDatasetsPanel', () => {
  it('渲染数据集行并显示来源徽标与文件数', () => {
    mountStore({ datasets: [makeDataset()] })
    const wrapper = mount(AvailableDatasetsPanel)
    expect(wrapper.text()).toContain('Soil_Moisture')
    expect(wrapper.text()).toContain('手动')
    expect(wrapper.text()).toContain('12')
  })

  it('内置（algorithm_registry）条目不显示删除按钮', () => {
    mountStore({ datasets: [makeDataset({ source: 'algorithm_registry', dataset_id: 'ds-b' })] })
    const wrapper = mount(AvailableDatasetsPanel)
    expect(wrapper.findAll('.btn').some((b) => b.text() === '删除')).toBe(false)
  })

  it('手动条目显示删除按钮', () => {
    mountStore({ datasets: [makeDataset()] })
    const wrapper = mount(AvailableDatasetsPanel)
    expect(wrapper.findAll('.btn').some((b) => b.text() === '删除')).toBe(true)
  })

  it('空注册表显示扫描引导文案', () => {
    mountStore()
    const wrapper = mount(AvailableDatasetsPanel)
    expect(wrapper.text()).toContain('重新扫描')
    expect(wrapper.text()).toContain('暂无数据集')
  })
})

describe('RemoteDataSourcesPanel 动态分组', () => {
  it('存储源 / 国际门户 / 国内门户三组渲染，能力徽标正确', () => {
    mountStore({
      profiles: [makeProfile()],
      portals: [
        makePortal({ portal_id: 'nasa_cmr', name: 'NASA CMR', region: 'international', search_capability: 'cmr', requires_credentials: false }),
        makePortal(),
      ],
    })
    const wrapper = mount(RemoteDataSourcesPanel)
    const titles = wrapper.findAll('.group-title').map((t) => t.text())
    expect(titles.some((t) => t.startsWith('远程存储源'))).toBe(true)
    expect(titles.some((t) => t.startsWith('国际组织门户'))).toBe(true)
    expect(titles.some((t) => t.startsWith('国内机构门户'))).toBe(true)
    // sftp 存储源：可浏览 + 可检索
    expect(wrapper.text()).toContain('可检索')
    // tpdc 无检索能力 → 仅下载徽标
    expect(wrapper.text()).toContain('仅下载')
    // 缺凭据提示
    expect(wrapper.text()).toContain('缺凭据')
  })

  it('没有任何源时显示去「远程与存储」的空态引导', () => {
    mountStore()
    const wrapper = mount(RemoteDataSourcesPanel)
    expect(wrapper.find('.empty-guide').exists()).toBe(true)
    expect(wrapper.text()).toContain('远程与存储')
  })
})

describe('PathConfigSection（只读）', () => {
  it('仅展示进程生效路径，无输入框与保存按钮', () => {
    mountStore()
    const wrapper = mount(PathConfigSection)
    expect(wrapper.findAll('input').length).toBe(0)
    expect(wrapper.findAll('button').length).toBe(0)
    expect(wrapper.text()).toContain('路径配置（只读）')
    expect(wrapper.text()).toContain('部署与数据源配置中心')
    expect(wrapper.text()).toContain('进程生效数据根')
    expect(wrapper.text()).toContain('I:/Geograph_DataSet')
  })

  it('pending_restart 时显示待重启徽章', () => {
    const store = mountStore()
    store.dataSourceConfig = { ...store.dataSourceConfig, pending_restart: true } as never
    const wrapper = mount(PathConfigSection)
    expect(wrapper.find('.badge-warn').exists()).toBe(true)
  })
})

describe('DatasetFormDialog', () => {
  it('新增时必填校验（逻辑名称 / 路径）', async () => {
    mountStore()
    const wrapper = mount(DatasetFormDialog, { props: { visible: true, editing: null } })
    const saveBtn = wrapper.findAll('button').find((b) => b.text() === '保存')
    await saveBtn!.trigger('click')
    expect(wrapper.text()).toContain('请填写逻辑名称')
  })

  it('编辑内置条目时逻辑名称输入禁用', () => {
    mountStore()
    const wrapper = mount(DatasetFormDialog, {
      props: { visible: true, editing: makeDataset({ source: 'algorithm_registry' }) as never },
    })
    const nameInput = wrapper.find('input')
    expect((nameInput.element as HTMLInputElement).disabled).toBe(true)
  })
})
