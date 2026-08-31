// @vitest-environment jsdom
/**
 * RemoteSourceAddDialog 融合对话框回归锁（2026-08-25 数据源管理改版 P1）。
 *
 * 三形态（search/browse/plain）+ 按钮可见性（映射站点才显示
 * 「注册并添加到图层」）+ 多选检索 + 注册调用参数（site_compatible）。
 */
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { mount } from '@/test-utils'
import RemoteSourceAddDialog from '@/components/settings/data-source/RemoteSourceAddDialog.vue'

/** 等待微任务队列（项目惯例：本地定义，见 deployment-config-view.test.ts） */
async function flushPromises(): Promise<void> {
  await new Promise((resolve) => setTimeout(resolve, 0))
}

// settings store mock（saveRemoteSource 记录调用参数）
const saveRemoteSourceMock = vi.fn().mockResolvedValue(undefined)
vi.mock('@/stores/settings', () => ({
  useSettingsStore: () => ({
    saveRemoteSource: saveRemoteSourceMock,
  }),
}))

// 检索 API mock
const searchPortalMock = vi.fn()
vi.mock('@/services/settings-api', () => ({
  searchPortal: (...args: unknown[]) => searchPortalMock(...args),
  upsertRemoteDatasetGrant: vi.fn().mockResolvedValue({}),
}))

const PORTAL = {
  portal_id: 'nsidc_data',
  name: 'NSIDC',
  search_capability: 'cmr',
  requires_credentials: false,
  has_credentials: false,
} as never

function mountDialog(props: Partial<Record<string, unknown>> = {}) {
  return mount(RemoteSourceAddDialog, {
    props: {
      visible: true,
      kind: 'portal',
      refId: 'nsidc_data',
      name: 'NSIDC',
      searchable: true,
      browsable: false,
      portal: PORTAL,
      ...props,
    },
    // 对话框内容 Teleport 到 body——stub 后可被 wrapper 断言
    global: { stubs: { teleport: true } },
  })
}

beforeEach(() => {
  saveRemoteSourceMock.mockClear()
  searchPortalMock.mockReset()
})

describe('RemoteSourceAddDialog 融合对话框（P1）', () => {
  it('检索型门户：内嵌检索列表 + 多选 + 映射站点显示「注册并添加到图层」', async () => {
    searchPortalMock.mockResolvedValue({
      items: [
        { dataset_key: 'SPL3SMP_E', title: 'SMAP L3', description: '', extra: {} },
        { dataset_key: 'SPL4SMGP', title: 'SMAP L4', description: '', extra: {} },
      ],
      count: 2,
    })
    const wrapper = mountDialog()
    // nsidc_data 在 PORTAL_WORKFLOW_MAP 中 → 双按钮
    expect(wrapper.text()).toContain('注册并添加到图层')
    expect(wrapper.text()).toContain('注册')
    // 检索
    await wrapper.find('input[placeholder*="关键词"]').setValue('SMAP')
    await wrapper.find('.rsa-searchbar .btn').trigger('click')
    await flushPromises()
    expect(searchPortalMock).toHaveBeenCalledWith('nsidc_data', 'SMAP')
    expect(wrapper.findAll('.rsa-row').length).toBe(2)
    // 多选两行
    await wrapper.findAll('.rsa-row')[0].trigger('click')
    await wrapper.findAll('.rsa-row')[1].trigger('click')
    expect(wrapper.text()).toContain('注册并添加到图层（2 个）')
  })

  it('映射带默认数据集的站点：未选数据集也可一键上图（默认集）；普通注册走整源 site_compatible', async () => {
    const wrapper = mountDialog()
    // nsidc_data 映射带 defaultDatasetKeys（SPL3SMP_E）→ 按钮可用且标注默认集
    const addBtn = wrapper.findAll('button').find((b) => b.text().includes('注册并添加'))!
    expect(addBtn.attributes('disabled')).toBeUndefined()
    expect(addBtn.text()).toContain('默认数据集')
    // 点普通注册（site_compatible 整源）
    const regBtn = wrapper.findAll('button').find((b) => b.text() === '注册')!
    await regBtn.trigger('click')
    await flushPromises()
    expect(saveRemoteSourceMock).toHaveBeenCalledWith(
      'nsidc_data',
      expect.objectContaining({ access_mode: 'site_compatible' }),
    )
  })

  it('无映射站点：不显示「注册并添加到图层」按钮（仅普通注册）', () => {
    const wrapper = mountDialog({ refId: 'unknown_portal_x' })
    const actionBtns = wrapper.find('.rsa-actions').findAll('button')
    expect(actionBtns.length).toBe(1)
    expect(actionBtns[0].text()).toBe('注册')
  })

  it('仅下载型（plain）：无检索区无远端路径，仅注册', () => {
    const wrapper = mountDialog({
      searchable: false,
      browsable: false,
      portal: null,
    })
    expect(wrapper.find('.rsa-searchbar').exists()).toBe(false)
    expect(wrapper.find('.rsa-browse-row').exists()).toBe(false)
    expect(wrapper.text()).toContain('该源不支持检索/浏览')
  })

  it('浏览型存储：显示路径框 + 浏览目录按钮', () => {
    const wrapper = mountDialog({
      kind: 'storage',
      searchable: false,
      browsable: true,
      refId: 'nas-1',
      name: 'NAS',
      portal: null,
      profile: { profile_id: 'nas-1', protocol: 'ssh' } as never,
    })
    expect(wrapper.find('.rsa-browse-row').exists()).toBe(true)
    expect(wrapper.text()).toContain('浏览目录')
  })
})
