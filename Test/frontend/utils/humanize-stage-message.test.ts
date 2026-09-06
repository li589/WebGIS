/**
 * 状态面板消息人话化（humanize-stage-message）测试。
 */
import { describe, expect, it } from 'vitest'
import { humanizeStageMessage } from '@/utils/humanize-stage-message'

describe('humanizeStageMessage', () => {
  it('Stage D 进度人话化', () => {
    expect(
      humanizeStageMessage('Stage D: 361/365 (processed=0, resumed=25, skipped=336)'),
    ).toBe('反演阶段 D（反演回代）：已完成 361/365 天（新计算 0，复用缓存 25，跳过 336）')
  })

  it('规划与产物消息', () => {
    expect(
      humanizeStageMessage('Build FY daily job plan from I:\\Geograph_DataSet\\Satellite'),
    ).toBe('生成风云逐日作业计划')
    expect(humanizeStageMessage('[fy_plan] Artifact ready: fy_daily_tif')).toBe(
      '已生成产物：逐日亮温（TIF）',
    )
  })

  it('下载与跳过消息', () => {
    expect(humanizeStageMessage('Downloaded 0 file(s), skipped 2: FY3D_AAA, FY3D_BBB')).toBe(
      '已下载 0 个文件，跳过 2 个（已存在）：FY3D_AAA, FY3D_BBB',
    )
    expect(humanizeStageMessage('Skipped 20260101 (mat exists)')).toBe(
      '2026-01-01 已有结果，跳过',
    )
  })

  it('未命中的消息原样返回', () => {
    const raw = 'Some unknown internal message'
    expect(humanizeStageMessage(raw)).toBe(raw)
    expect(humanizeStageMessage('')).toBe('')
  })
})
