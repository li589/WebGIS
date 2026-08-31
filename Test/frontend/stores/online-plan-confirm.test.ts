/**
 * OnlinePlanPanel confirm path — preference + runWorkflow online + timeRange
 *（通过 store + mock workflow，不挂载整页）
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { ref } from 'vue'

import { useOnlinePlanSessionStore } from '../../../Code/frontend/src/stores/online-plan-session'
import { toAlgorithmParamsFromPlan } from '../../../Code/frontend/src/utils/online-plan-params'

describe('online plan confirm helpers', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('toAlgorithmParamsFromPlan projects whitelist keys', () => {
    expect(toAlgorithmParamsFromPlan({ orbit_mode: 'MWRIA', junk: 1 })).toEqual({
      orbit_mode: 'MWRIA',
    })
    expect(toAlgorithmParamsFromPlan({})).toBeUndefined()
  })

  it('confirm sequence: preference online then run with timeRange (manual orchestration)', async () => {
    const plan = useOnlinePlanSessionStore()
    plan.incrementFailCount('method-fy')
    plan.incrementFailCount('method-fy')
    plan.incrementFailCount('method-fy')
    plan.ensureTab('method-fy', {
      timeKey: '2025-12-03',
      timeRange: { start_at: '2025-12-03T00:00:00Z', end_at: '2025-12-04T00:00:00Z' },
      preferredVariant: 'online',
      paramOverrides: { orbit_mode: 'Both' },
    })

    const setWorkflowVariantPreference = vi.fn()
    const interruptWorkflowForCatalog = vi.fn()
    const runWorkflowForCatalog = vi.fn(async () => 'run-new')
    const jobLayers = ref([{ jobId: 'old', catalogId: 'method-fy', status: 'failed' }])

    const tab = plan.activeTab!
    setWorkflowVariantPreference(tab.catalogId, 'online')
    interruptWorkflowForCatalog(tab.catalogId)
    // 旧 failed 不动
    expect(jobLayers.value[0].status).toBe('failed')

    await runWorkflowForCatalog(tab.catalogId, {
      workflowVariant: 'online',
      timeRange: tab.timeRange
        ? { start_at: tab.timeRange.start_at, end_at: tab.timeRange.end_at }
        : undefined,
      algorithmRequest: {
        algorithm_params: toAlgorithmParamsFromPlan(tab.paramOverrides),
      },
    })

    expect(setWorkflowVariantPreference).toHaveBeenCalledWith('method-fy', 'online')
    expect(runWorkflowForCatalog).toHaveBeenCalledWith(
      'method-fy',
      expect.objectContaining({
        workflowVariant: 'online',
        timeRange: expect.objectContaining({ start_at: '2025-12-03T00:00:00Z' }),
        algorithmRequest: { algorithm_params: { orbit_mode: 'Both' } },
      }),
    )
    expect(jobLayers.value[0].status).toBe('failed')

    plan.resolveTab('method-fy')
    expect(plan.status).toBe('resolved')
  })
})
