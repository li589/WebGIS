/**
 * online-plan-params — descriptor 资格 + 参数投影（P2 无 catalog 白名单）
 */
import { describe, expect, it } from 'vitest'

import {
  descriptorHasOnlineWorkflowVariant,
  extractPresentOnlinePlanParams,
  projectOnlinePlanParams,
} from '../../../Code/frontend/src/utils/online-plan-params'
import { ONLINE_PLAN_COPY } from '../../../Code/frontend/src/ui-copy'

describe('online-plan-params P2 helpers', () => {
  it('descriptorHasOnlineWorkflowVariant only checks workflow_variants.online', () => {
    expect(descriptorHasOnlineWorkflowVariant(null)).toBe(false)
    expect(descriptorHasOnlineWorkflowVariant({})).toBe(false)
    expect(
      descriptorHasOnlineWorkflowVariant({
        workflow_variants: { local: { workflow_id: 'x' } },
      }),
    ).toBe(false)
    expect(
      descriptorHasOnlineWorkflowVariant({
        workflow_variants: { online: { workflow_id: 'any-online-seed' } },
      }),
    ).toBe(true)
  })

  it('extractPresentOnlinePlanParams does not invent orbit_mode defaults', () => {
    expect(extractPresentOnlinePlanParams(null)).toEqual({})
    expect(extractPresentOnlinePlanParams({ junk: 1 })).toEqual({})
    expect(extractPresentOnlinePlanParams({ orbit_mode: 'MWRIA' })).toEqual({
      orbit_mode: 'MWRIA',
    })
  })

  it('projectOnlinePlanParams still fills defaults for form merge', () => {
    expect(projectOnlinePlanParams(null).orbit_mode).toBeTruthy()
  })

  it('ONLINE_PLAN_COPY pending badge is stable', () => {
    expect(ONLINE_PLAN_COPY.pendingBadge).toBe('待计划')
    expect(ONLINE_PLAN_COPY.parkedDock(2)).toBe('待决策 2')
    expect(ONLINE_PLAN_COPY.panelTitle).toBe('在线计划')
  })
})
