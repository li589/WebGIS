import { describe, expect, it } from 'vitest'

import {
  isTechnicalRunTitle,
  resolveJobLayerDisplayName,
  resolveRunGroupTitle,
  resolveWorkflowRunDisplayName,
  stripComputingGroupSuffix,
} from '@/utils/workflow-run-display-name'

describe('workflow-run-display-name', () => {
  const summaries = [
    { workflow_id: 'omega_avg_daily_smap_online', name: 'SMAP 平均 散射约束产品反演（在线）' },
    { workflow_id: 'omega_sf_fenkuai_smap_online', name: 'SMAP 动态 散射约束产品反演（在线）' },
  ]

  it('isTechnicalRunTitle 识别 wf-run / run-group 占位', () => {
    expect(isTechnicalRunTitle('wf-run-run-group-mtgmh5un-sm')).toBe(true)
    expect(isTechnicalRunTitle('run-group-restored-abc123')).toBe(true)
    expect(isTechnicalRunTitle('SMAP 动态 散射约束产品反演（本地）')).toBe(false)
  })

  it('resolveWorkflowRunDisplayName 优先种子 summary 名，catalog 仅兜底', () => {
    expect(
      resolveWorkflowRunDisplayName({
        workflowId: 'omega_avg_daily_smap_online',
        catalogName: 'wf-run-run-group-mtgmh5un-y29',
        summaries,
      }),
    ).toBe('SMAP 平均 散射约束产品反演（在线）')
  })

  it('resolveRunGroupTitle 禁止 wf-run 占位泄漏为组标题', () => {
    expect(
      resolveRunGroupTitle({
        workflowId: 'omega_sf_fenkuai_smap_online',
        configuredTitle: 'wf-run-run-group-mtgmh5un-y29',
        summaries,
        fallback: '工作流产物',
      }),
    ).toBe('SMAP 动态 散射约束产品反演（在线）')
  })

  it('resolveRunGroupTitle 保留已配置中文组名并去掉计算中后缀', () => {
    expect(
      resolveRunGroupTitle({
        configuredTitle: 'SMAP 动态 散射约束产品反演（本地） · 计算中',
      }),
    ).toBe('SMAP 动态 散射约束产品反演（本地）')
  })

  it('resolveJobLayerDisplayName 轮询时保留已有非技术名', () => {
    expect(
      resolveJobLayerDisplayName(
        { command_label: '运行分析 · 在线获取', layer_id: 'method-smap-omega-avg' },
        'wf-run-run-group-abc-result',
        { previousName: 'SMAP 动态 散射约束产品反演（在线）' },
      ),
    ).toBe('SMAP 动态 散射约束产品反演（在线）')
  })

  it('stripComputingGroupSuffix 去掉 · 计算中', () => {
    expect(stripComputingGroupSuffix('反演产物 · 计算中')).toBe('反演产物')
  })
})
