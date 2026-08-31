/**
 * useOnlinePlanParamSync — 流水线在线表单 ↔ 计划会话 draft 同源
 */
import { beforeEach, describe, expect, it } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import { useOnlinePlanParamSync } from '../../../Code/frontend/src/composables/useOnlinePlanParamSync'
import { useOnlinePlanSessionStore } from '../../../Code/frontend/src/stores/online-plan-session'

describe('useOnlinePlanParamSync', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('pushFormParamToPlan merges whitelist keys into active tab', () => {
    const plan = useOnlinePlanSessionStore()
    plan.incrementFailCount('fy-layer')
    plan.ensureTab('fy-layer', {
      preferredVariant: 'online',
      paramOverrides: { orbit_mode: 'MWRID' },
    })

    const { pushFormParamToPlan, pullPlanParamsForForm } = useOnlinePlanParamSync()
    pushFormParamToPlan('orbit_mode', 'MWRIA')
    expect(pullPlanParamsForForm('fy-layer')).toEqual(
      expect.objectContaining({ orbit_mode: 'MWRIA' }),
    )
    // 非白名单键忽略
    pushFormParamToPlan('junk_key', 'x')
    expect(pullPlanParamsForForm('fy-layer')).not.toHaveProperty('junk_key')
  })

  it('pullPlanParamsForForm returns null when no tab', () => {
    const { pullPlanParamsForForm } = useOnlinePlanParamSync()
    expect(pullPlanParamsForForm('missing')).toBeNull()
  })
})
