/**
 * W3.4c/W3.6：workflow-timekey-seek 工具测试。
 *
 * 覆盖：timelineTargetFromWorkflowTimeKey 的 range/单键/带连字符/月份/非法输入分支，
 * 与 matchSliceLabelInTimeList 的精确/前缀/未命中分支。
 */
import { describe, expect, it } from 'vitest'

import {
  matchSliceLabelInTimeList,
  timelineTargetFromWorkflowTimeKey,
} from '@/utils/workflow-timekey-seek'

describe('timelineTargetFromWorkflowTimeKey', () => {
  it('8 位区间键透传 sliceLabel 且为日粒度', () => {
    const target = timelineTargetFromWorkflowTimeKey('20240501_20240508')
    expect(target).not.toBeNull()
    expect(target!.sliceLabel).toBe('20240501_20240508')
    expect(target!.granularity).toBe('day')
    expect(target!.hour).toBe(0)
    expect(target!.date.getFullYear()).toBe(2024)
    expect(target!.date.getMonth()).toBe(4)
    expect(target!.date.getDate()).toBe(1)
  })

  it('单日键 sliceLabel 为 8 位日期', () => {
    const target = timelineTargetFromWorkflowTimeKey('20240501')
    expect(target!.sliceLabel).toBe('20240501')
    expect(target!.granularity).toBe('day')
  })

  it('带连字符日期压缩为 8 位，dateEnd 拼接区间', () => {
    const target = timelineTargetFromWorkflowTimeKey('2024-05-01', '2024-05-08')
    expect(target!.sliceLabel).toBe('20240501_20240508')
  })

  it('dateEnd 与起始同日时不拼接区间', () => {
    const target = timelineTargetFromWorkflowTimeKey('2024-05-01', '2024-05-01')
    expect(target!.sliceLabel).toBe('20240501')
  })

  it('月份键生成对应目标', () => {
    const target = timelineTargetFromWorkflowTimeKey('2024-05')
    expect(target).not.toBeNull()
  })

  it('空串与非日期串返回 null', () => {
    expect(timelineTargetFromWorkflowTimeKey('')).toBeNull()
    expect(timelineTargetFromWorkflowTimeKey('garbage')).toBeNull()
    expect(timelineTargetFromWorkflowTimeKey('   ')).toBeNull()
  })
})

describe('matchSliceLabelInTimeList', () => {
  const timeList = ['20240425_20240502', '20240501_20240508']

  it('精确命中返回原标签', () => {
    expect(matchSliceLabelInTimeList(timeList, '20240501_20240508')).toBe('20240501_20240508')
  })

  it('按 8 位前缀命中区间标签', () => {
    expect(matchSliceLabelInTimeList(timeList, '20240425')).toBe('20240425_20240502')
  })

  it('未命中返回 null', () => {
    expect(matchSliceLabelInTimeList(timeList, '20250101')).toBeNull()
  })

  it('空列表或空标签返回 null', () => {
    expect(matchSliceLabelInTimeList([], '20240501')).toBeNull()
    expect(matchSliceLabelInTimeList(undefined, '20240501')).toBeNull()
    expect(matchSliceLabelInTimeList(timeList, '')).toBeNull()
  })
})
