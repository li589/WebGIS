/**
 * 流水线时间参数记忆（pipeline-time-memory）单元测试。
 *
 * 覆盖：写入/读取、空入参忽略、容量上限淘汰最旧、损坏 JSON 容错。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'

const store = new Map<string, string>()

vi.mock('@/services/user-local-isolation', () => ({
  readScopedItem: (key: string) => store.get(key) ?? null,
  writeScopedItem: (key: string, value: string) => void store.set(key, value),
  removeScopedItem: (key: string) => void store.delete(key),
}))

import {
  getPipelineLastTimeRange,
  setPipelineLastTimeRange,
} from '@/services/pipeline-time-memory'

beforeEach(() => {
  store.clear()
})

describe('pipeline-time-memory', () => {
  it('写入后可按 workflowId 读回', () => {
    setPipelineLastTimeRange('omega_avg_smap_online', '20250601', '20250630')
    const remembered = getPipelineLastTimeRange('omega_avg_smap_online')
    expect(remembered?.start_date).toBe('20250601')
    expect(remembered?.end_date).toBe('20250630')
    expect(remembered?.savedAt).toBeTruthy()
  })

  it('无记忆时返回 undefined；空入参不写入', () => {
    expect(getPipelineLastTimeRange('no-such')).toBeUndefined()
    setPipelineLastTimeRange('', '20250601', '20250630')
    setPipelineLastTimeRange('wf', '', '20250630')
    expect(getPipelineLastTimeRange('wf')).toBeUndefined()
  })

  it('同 workflowId 覆盖旧值', () => {
    setPipelineLastTimeRange('wf-a', '20250101', '20250131')
    setPipelineLastTimeRange('wf-a', '20250201', '20250228')
    expect(getPipelineLastTimeRange('wf-a')?.start_date).toBe('20250201')
  })

  it('超过容量上限时淘汰最旧条目', () => {
    for (let i = 0; i < 105; i++) {
      setPipelineLastTimeRange(`wf-${String(i).padStart(3, '0')}`, '20250101', '20250102')
    }
    expect(getPipelineLastTimeRange('wf-000')).toBeUndefined()
    expect(getPipelineLastTimeRange('wf-104')).toBeDefined()
  })

  it('损坏的存储内容容错（返回空，不抛异常）', () => {
    store.set('geo:pipeline-last-time-range:v1', '{broken json')
    expect(getPipelineLastTimeRange('wf-a')).toBeUndefined()
    setPipelineLastTimeRange('wf-a', '20250101', '20250131')
    expect(getPipelineLastTimeRange('wf-a')?.start_date).toBe('20250101')
  })
})
