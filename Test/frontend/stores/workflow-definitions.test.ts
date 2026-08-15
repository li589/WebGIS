/**
 * W3.4e：workflow-definitions store 测试。
 *
 * 覆盖 loadNodeTemplates/loadSummaries/loadDefinition 成功与失败、createNew/
 * updateCurrent（摘要联动）/remove（当前项清理）/duplicate、computed 分组
 * （system/user/readonly/templatesByCategory）与 clearCurrent。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import {
  fetchNodeTemplates,
  fetchWorkflowDefinitions,
  fetchWorkflowDefinition,
  createWorkflowDefinition,
  updateWorkflowDefinition,
  deleteWorkflowDefinition,
  duplicateWorkflowDefinition,
} from '@/services/workflow-definition-api'
import { useWorkflowDefinitionsStore } from '@/stores/workflow-definitions'

vi.mock('@/services/workflow-definition-api', () => ({
  fetchNodeTemplates: vi.fn(),
  fetchWorkflowDefinitions: vi.fn(),
  fetchWorkflowDefinition: vi.fn(),
  createWorkflowDefinition: vi.fn(),
  updateWorkflowDefinition: vi.fn(),
  deleteWorkflowDefinition: vi.fn(),
  duplicateWorkflowDefinition: vi.fn(),
}))

vi.mock('@/stores/log', () => ({
  useLogStore: () => ({ logOperation: vi.fn() }),
}))

const api = {
  fetchNodeTemplates,
  fetchWorkflowDefinitions,
  fetchWorkflowDefinition,
  createWorkflowDefinition,
  updateWorkflowDefinition,
  deleteWorkflowDefinition,
  duplicateWorkflowDefinition,
}

const tplA = { type: 'module/a', engine: 'gee', category: '算法' }
const tplB = { type: 'io/output', engine: 'weather' }
const tplC = { type: 'download/x' }

const summarySystem = { workflow_id: 'w-sys', name: '系统流', kind: 'system' }
const summaryUser = { workflow_id: 'w-user', name: '用户流', kind: 'user' }
const definition = {
  workflow_id: 'w-user',
  name: '用户流',
  description: '描述',
  nodes: [{ id: 1 }, { id: 2 }],
  links: [],
  _meta: { readonly: false, updated_at: '2026-08-16T00:00:00Z' },
}

beforeEach(() => {
  vi.clearAllMocks()
  setActivePinia(createPinia())
  api.fetchNodeTemplates.mockResolvedValue([tplA, tplB, tplC] as never)
  api.fetchWorkflowDefinitions.mockResolvedValue([summarySystem, summaryUser] as never)
  api.fetchWorkflowDefinition.mockResolvedValue(definition as never)
  api.createWorkflowDefinition.mockResolvedValue(definition as never)
  api.updateWorkflowDefinition.mockResolvedValue({ ...definition, name: '改名' } as never)
  api.duplicateWorkflowDefinition.mockResolvedValue(definition as never)
})

describe('加载动作', () => {
  it('loadNodeTemplates 成功填充模板', async () => {
    const store = useWorkflowDefinitionsStore()
    await store.loadNodeTemplates()
    expect(store.nodeTemplates).toHaveLength(3)
    expect(store.error).toBeNull()
  })

  it('loadNodeTemplates 失败记录 error', async () => {
    api.fetchNodeTemplates.mockRejectedValue(new Error('模板服务不可用'))
    const store = useWorkflowDefinitionsStore()
    await store.loadNodeTemplates()
    expect(store.error).toBe('模板服务不可用')
  })

  it('loadSummaries 成功与失败均复位 loading', async () => {
    const store = useWorkflowDefinitionsStore()
    await store.loadSummaries()
    expect(store.summaries).toHaveLength(2)
    expect(store.loading).toBe(false)

    api.fetchWorkflowDefinitions.mockRejectedValueOnce(new Error('列表失败'))
    await store.loadSummaries()
    expect(store.error).toBe('列表失败')
    expect(store.loading).toBe(false)
  })

  it('loadDefinition 成功设置当前定义并返回；失败返回 null', async () => {
    const store = useWorkflowDefinitionsStore()
    const loaded = await store.loadDefinition('w-user')
    expect(loaded).toBe(store.currentDefinition)
    expect(store.isReadonly).toBe(false)

    api.fetchWorkflowDefinition.mockRejectedValueOnce(new Error('404'))
    const failed = await store.loadDefinition('missing')
    expect(failed).toBeNull()
    expect(store.error).toBe('404')
  })
})

describe('CRUD 动作', () => {
  it('createNew 创建后刷新列表', async () => {
    const store = useWorkflowDefinitionsStore()
    await store.createNew({ workflow_id: 'w-new', name: '新流' })
    expect(api.createWorkflowDefinition).toHaveBeenCalledWith({
      workflow_id: 'w-new',
      name: '新流',
    })
    expect(api.fetchWorkflowDefinitions).toHaveBeenCalled()
  })

  it('updateCurrent 无当前定义返回 null；成功时同步摘要', async () => {
    const store = useWorkflowDefinitionsStore()
    expect(await store.updateCurrent({ name: 'x' })).toBeNull()

    await store.loadDefinition('w-user')
    const updated = await store.updateCurrent({ name: '改名' })
    expect(updated.name).toBe('改名')
    expect(store.currentDefinition.name).toBe('改名')
  })

  it('updateCurrent 列表中不存在该 id 时不更新摘要但返回更新值', async () => {
    api.fetchWorkflowDefinitions.mockResolvedValue([summarySystem] as never)
    const store = useWorkflowDefinitionsStore()
    await store.loadSummaries()
    await store.loadDefinition('w-user')
    const updated = await store.updateCurrent({ name: '改名' })
    expect(updated).not.toBeNull()
    expect(store.summaries).toHaveLength(1)
  })

  it('remove 删除当前定义时清空 currentDefinition 并刷新', async () => {
    const store = useWorkflowDefinitionsStore()
    await store.loadDefinition('w-user')
    await store.remove('w-user')
    expect(store.currentDefinition).toBeNull()
    expect(api.deleteWorkflowDefinition).toHaveBeenCalledWith('w-user')
  })

  it('remove 删除非当前定义不影响 currentDefinition', async () => {
    const store = useWorkflowDefinitionsStore()
    await store.loadDefinition('w-user')
    await store.remove('w-other')
    expect(store.currentDefinition).not.toBeNull()
  })

  it('duplicate 复制并刷新列表', async () => {
    const store = useWorkflowDefinitionsStore()
    const created = await store.duplicate('w-user', 'w-copy', '副本')
    expect(created).not.toBeNull()
    expect(api.duplicateWorkflowDefinition).toHaveBeenCalledWith('w-user', 'w-copy', '副本')
    expect(api.fetchWorkflowDefinitions).toHaveBeenCalled()
  })

  it('clearCurrent 清空当前定义', async () => {
    const store = useWorkflowDefinitionsStore()
    await store.loadDefinition('w-user')
    store.clearCurrent()
    expect(store.currentDefinition).toBeNull()
  })
})

describe('computed 分组', () => {
  it('systemWorkflows / userWorkflows 按 kind 过滤', async () => {
    const store = useWorkflowDefinitionsStore()
    await store.loadSummaries()
    expect(store.systemWorkflows).toHaveLength(1)
    expect(store.userWorkflows).toHaveLength(1)
  })

  it('isReadonly 取自 _meta.readonly', async () => {
    api.fetchWorkflowDefinition.mockResolvedValue({
      ...definition,
      _meta: { readonly: true, updated_at: '' },
    } as never)
    const store = useWorkflowDefinitionsStore()
    await store.loadDefinition('w-user')
    expect(store.isReadonly).toBe(true)
  })

  it('templatesByCategory 按 category → engine → other 分组', async () => {
    const store = useWorkflowDefinitionsStore()
    await store.loadNodeTemplates()
    const groups = store.templatesByCategory
    expect(Object.keys(groups).sort()).toEqual(['other', 'weather', '算法'])
    expect(groups['算法']).toHaveLength(1)
    expect(groups.weather).toHaveLength(1)
    expect(groups.other).toHaveLength(1)
  })
})
