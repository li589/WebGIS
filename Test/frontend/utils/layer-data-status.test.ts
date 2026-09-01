/**
 * 统一数据状态徽标归并逻辑回归锁（2026-08-25 UX 简化）。
 *
 * 用户报障：图层条目下方「数据异常 资产陈旧 失败 查看报告」状态串冗余，
 * 「资产」术语对地理研究者无意义。归并三源为单枚五态徽标：
 * 运行中 / 排队中 / 异常 / 完成 / 旧数据（静态层豁免旧数据）。
 */
import { describe, expect, it } from 'vitest'
import { deriveDataStatus, normalizeRunGroupMemberStatus } from '../../../Code/frontend/src/utils/layer-data-status'

describe('deriveDataStatus 三源归并', () => {
  it('job 状态优先：running → 运行中（不含组外进度百分比）', () => {
    const r = deriveDataStatus({
      jobStatus: 'running',
      jobProgress: 45.6,
      availabilityState: 'partial',
      availabilityLabel: '运行中',
      lifecycleState: 'stale',
    })
    expect(r?.state).toBe('running')
    expect(r?.label).toBe('运行中')
  })

  it('job queued/retry_pending → 排队中', () => {
    expect(deriveDataStatus({ jobStatus: 'queued' })?.label).toBe('排队中')
    expect(deriveDataStatus({ jobStatus: 'retry_pending' })?.label).toBe('排队中')
  })

  it('job failed/cancelled → 异常', () => {
    expect(deriveDataStatus({ jobStatus: 'failed' })?.state).toBe('error')
    expect(deriveDataStatus({ jobStatus: 'cancelled' })?.state).toBe('error')
  })

  it('lifecycle updating → 运行中；failed/missing → 异常', () => {
    expect(deriveDataStatus({ lifecycleState: 'updating' })?.state).toBe('running')
    expect(deriveDataStatus({ lifecycleState: 'failed' })?.state).toBe('error')
    expect(deriveDataStatus({ lifecycleState: 'missing' })?.state).toBe('error')
  })

  it('lifecycle stale 非静态层 → 旧数据（非故障提示）', () => {
    const r = deriveDataStatus({ lifecycleState: 'stale', isStaticLayer: false })
    expect(r?.state).toBe('stale')
    expect(r?.label).toBe('旧数据')
    expect(r?.title).toContain('非系统故障')
  })

  it('lifecycle stale 静态层豁免：不显示旧数据（落到后续判定）', () => {
    const r = deriveDataStatus({
      lifecycleState: 'stale',
      isStaticLayer: true,
      availabilityState: 'ready',
    })
    // 静态层数据可用 → 完成（不显示「旧数据」）
    expect(r?.state).toBe('done')
  })

  it('availability ready → 完成；partial 运行中/排队中分流', () => {
    expect(
      deriveDataStatus({ availabilityState: 'ready', availabilityLabel: '完整数据' })?.state,
    ).toBe('done')
    expect(
      deriveDataStatus({
        availabilityState: 'partial',
        availabilityLabel: '运行中',
      })?.state,
    ).toBe('running')
    expect(
      deriveDataStatus({
        availabilityState: 'partial',
        availabilityLabel: '排队中',
      })?.state,
    ).toBe('queued')
  })

  it('availability empty：数据异常→异常；数据未就绪/待运行→排队中', () => {
    expect(
      deriveDataStatus({
        availabilityState: 'empty',
        availabilityLabel: '数据异常',
      })?.state,
    ).toBe('error')
    expect(
      deriveDataStatus({
        availabilityState: 'empty',
        availabilityLabel: '待运行',
      })?.state,
    ).toBe('queued')
  })

  it('lifecycle fresh 无 availability → 完成', () => {
    expect(deriveDataStatus({ lifecycleState: 'fresh' })?.state).toBe('done')
  })

  it('无任何信号 → null（不渲染）', () => {
    expect(deriveDataStatus({})).toBeNull()
  })

  it('job succeeded 落到 availability：ready → 完成', () => {
    const r = deriveDataStatus({
      jobStatus: 'succeeded',
      availabilityState: 'ready',
      availabilityLabel: '完整数据',
    })
    expect(r?.state).toBe('done')
  })
})

describe('normalizeRunGroupMemberStatus', () => {
  it('计算组运行中：排队中/运行中统一为运行中', () => {
    expect(
      normalizeRunGroupMemberStatus({ state: 'queued', label: '排队中' }, true)?.label,
    ).toBe('运行中')
    expect(
      normalizeRunGroupMemberStatus({ state: 'running', label: '运行中 46%' }, true)?.label,
    ).toBe('运行中')
  })

  it('非计算组或终态不改动', () => {
    const done = { state: 'done' as const, label: '完成' }
    expect(normalizeRunGroupMemberStatus(done, true)).toEqual(done)
    expect(
      normalizeRunGroupMemberStatus({ state: 'queued', label: '排队中' }, false)?.label,
    ).toBe('排队中')
  })
})
