import { describe, expect, it } from 'vitest'

import {
  isActionCommandLabel,
  isTechnicalRunTitle,
  resolveJobLayerDisplayName,
  resolveRunGroupTitle,
  resolveWorkflowRunDisplayName,
  stripComputingGroupSuffix,
} from '@/utils/workflow-run-display-name'

describe('workflow-run-display-name', () => {
  const summaries = [
    { workflow_id: 'omega_avg_daily_smap_online', name: 'SMAP 平均散射约束产品反演（在线）' },
    { workflow_id: 'omega_sf_fenkuai_smap_online', name: 'SMAP 动态散射约束产品反演（在线）' },
  ]

  it('isTechnicalRunTitle 识别 wf-run / run-group 占位', () => {
    expect(isTechnicalRunTitle('wf-run-run-group-mtgmh5un-sm')).toBe(true)
    expect(isTechnicalRunTitle('run-group-restored-abc123')).toBe(true)
    expect(isTechnicalRunTitle('SMAP 动态散射约束产品反演（本地）')).toBe(false)
  })

  it('resolveWorkflowRunDisplayName 优先种子 summary 名，catalog 仅兜底', () => {
    expect(
      resolveWorkflowRunDisplayName({
        workflowId: 'omega_avg_daily_smap_online',
        catalogName: 'wf-run-run-group-mtgmh5un-y29',
        summaries,
      }),
    ).toBe('SMAP 平均散射约束产品反演（在线）')
  })

  it('resolveRunGroupTitle 禁止 wf-run 占位泄漏为组标题', () => {
    expect(
      resolveRunGroupTitle({
        workflowId: 'omega_sf_fenkuai_smap_online',
        configuredTitle: 'wf-run-run-group-mtgmh5un-y29',
        summaries,
        fallback: '工作流产物',
      }),
    ).toBe('SMAP 动态散射约束产品反演（在线）')
  })

  it('resolveRunGroupTitle 保留已配置中文组名并去掉计算中后缀', () => {
    expect(
      resolveRunGroupTitle({
        configuredTitle: 'SMAP 动态散射约束产品反演（本地） · 计算中',
      }),
    ).toBe('SMAP 动态散射约束产品反演（本地）')
  })

  it('resolveJobLayerDisplayName 轮询时保留已有非技术名', () => {
    expect(
      resolveJobLayerDisplayName(
        { command_label: '运行分析 · 在线获取', layer_id: 'method-smap-omega-avg' },
        'wf-run-run-group-abc-result',
        { previousName: 'SMAP 动态散射约束产品反演（在线）' },
      ),
    ).toBe('SMAP 动态散射约束产品反演（在线）')
  })

  it('stripComputingGroupSuffix 去掉 · 计算中', () => {
    expect(stripComputingGroupSuffix('反演产物 · 计算中')).toBe('反演产物')
  })

  it('isActionCommandLabel 正确识别各类重跑与运行动作指令', () => {
    expect(isActionCommandLabel('按时间轴重跑 2026-07')).toBe(true)
    expect(isActionCommandLabel('按时段重跑 20250701_20250708')).toBe(true)
    expect(isActionCommandLabel('切换在线并重跑 2026-09')).toBe(true)
    expect(isActionCommandLabel('计划会话在线重跑 2026-07')).toBe(true)
    expect(isActionCommandLabel('运行 植被指数 NDVI 分析')).toBe(true)
    expect(isActionCommandLabel('运行分析 · 在线获取')).toBe(true)
    expect(isActionCommandLabel('运行画布工作流 test_flow')).toBe(true)
    expect(isActionCommandLabel('植被指数 NDVI')).toBe(false)
    expect(isActionCommandLabel('SMAP 动态散射约束产品反演（本地）')).toBe(false)
  })

  it('isTechnicalRunTitle 将动作指令判为技术/非实体名称，防止侵占主标题', () => {
    expect(isTechnicalRunTitle('按时间轴重跑 2026-07')).toBe(true)
    expect(isTechnicalRunTitle('按时段重跑 20250701_20250708')).toBe(true)
    expect(isTechnicalRunTitle('切换在线并重跑 2026-09')).toBe(true)
    expect(isTechnicalRunTitle('植被指数 NDVI')).toBe(false)
  })

  it('resolveWorkflowRunDisplayName 在时间轴重跑时保持图层业务名，动作指令不侵占主标题', () => {
    // 场景：按时间轴重跑 2026-07
    expect(
      resolveWorkflowRunDisplayName({
        commandLabel: '按时间轴重跑 2026-07',
        catalogName: '植被指数 NDVI',
      }),
    ).toBe('植被指数 NDVI')

    // 场景：按时段重跑 20250701_20250708
    expect(
      resolveWorkflowRunDisplayName({
        commandLabel: '按时段重跑 20250701_20250708',
        catalogName: '风云卫星 动态散射约束产品',
      }),
    ).toBe('风云卫星 动态散射约束产品')

    // 场景：切换在线并重跑 2026-09
    expect(
      resolveWorkflowRunDisplayName({
        commandLabel: '切换在线并重跑 2026-09',
        catalogName: '植被指数 NDVI',
      }),
    ).toBe('植被指数 NDVI')

    // 场景：运行 植被指数 NDVI 分析
    expect(
      resolveWorkflowRunDisplayName({
        commandLabel: '运行 植被指数 NDVI 分析',
        catalogName: '植被指数 NDVI',
      }),
    ).toBe('植被指数 NDVI')
  })

  it('resolveJobLayerDisplayName 在 previousName 含有动作指令脏数据时不短路保留', () => {
    expect(
      resolveJobLayerDisplayName(
        { command_label: '按时间轴重跑 2026-07', layer_id: 'vegetation-ndvi' },
        '植被指数 NDVI',
        { previousName: '按时间轴重跑 2026-07' },
      ),
    ).toBe('植被指数 NDVI')

    expect(
      resolveJobLayerDisplayName(
        { command_label: '按时段重跑 20250701_20250708', layer_id: 'method-fy-omega-doy-dynamic' },
        '风云卫星 动态散射约束产品',
        { previousName: '按时段重跑 20250701_20250708' },
      ),
    ).toBe('风云卫星 动态散射约束产品')
  })
})
