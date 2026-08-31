/**
 * online-plan-session — failCount / multi-tab / park / resolve
 */
import { beforeEach, describe, expect, it } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import {
  ONLINE_PLAN_ESCALATE_AFTER,
  useOnlinePlanSessionStore,
} from '../../../Code/frontend/src/stores/online-plan-session'

describe('online-plan-session store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('increments failCount and escalates threshold is 3', () => {
    const store = useOnlinePlanSessionStore()
    expect(ONLINE_PLAN_ESCALATE_AFTER).toBe(3)
    expect(store.incrementFailCount('layer-a')).toBe(1)
    expect(store.incrementFailCount('layer-a')).toBe(2)
    expect(store.incrementFailCount('layer-a')).toBe(3)
    expect(store.getFailCount('layer-a')).toBe(3)
  })

  it('ensureTab opens session and supports multi-catalog chips', () => {
    const store = useOnlinePlanSessionStore()
    store.incrementFailCount('a')
    store.incrementFailCount('a')
    store.incrementFailCount('a')
    store.ensureTab('a', { displayName: 'A', lastFailMessage: 'gap' })
    store.incrementFailCount('b')
    store.incrementFailCount('b')
    store.incrementFailCount('b')
    store.ensureTab('b', { displayName: 'B' })

    expect(store.tabs).toHaveLength(2)
    expect(store.activeCatalogId).toBe('b')
    expect(store.status).toBe('open')

    store.setActiveCatalog('a')
    expect(store.activeTab?.catalogId).toBe('a')
    expect(store.activeTab?.displayName).toBe('A')
  })

  it('park keeps draft; reopen restores open without clearing tabs', () => {
    const store = useOnlinePlanSessionStore()
    store.incrementFailCount('x')
    store.ensureTab('x', {
      lastFailMessage: 'coverage_gap',
      timeKey: '2025-12-03',
      preferredVariant: 'online',
    })
    store.parkSession()
    expect(store.status).toBe('parked')
    expect(store.tabs[0].timeKey).toBe('2025-12-03')
    store.openSession()
    expect(store.status).toBe('open')
    expect(store.tabs).toHaveLength(1)
  })

  it('resolveTab clears failCount; last tab resolves session', () => {
    const store = useOnlinePlanSessionStore()
    store.incrementFailCount('only')
    store.ensureTab('only')
    store.resolveTab('only')
    expect(store.getFailCount('only')).toBe(0)
    expect(store.status).toBe('resolved')
    expect(store.tabs).toHaveLength(0)
  })

  it('isCatalogPendingPlan is true while tab open/parked; false after resolve', () => {
    const store = useOnlinePlanSessionStore()
    store.ensureTab('layer-x')
    expect(store.isCatalogPendingPlan('layer-x')).toBe(true)
    store.parkSession()
    expect(store.isCatalogPendingPlan('layer-x')).toBe(true)
    store.resolveTab('layer-x')
    expect(store.isCatalogPendingPlan('layer-x')).toBe(false)
  })

  it('applyTimeRangeToAllTabs writes same timeKey to every tab', () => {
    const store = useOnlinePlanSessionStore()
    store.ensureTab('a', { timeKey: '2025-01-01' })
    store.ensureTab('b', { timeKey: '2025-01-02' })
    const n = store.applyTimeRangeToAllTabs({
      timeKey: '2025-12-03',
      timeRange: {
        start_at: '2025-12-03T00:00:00Z',
        end_at: '2025-12-04T00:00:00Z',
        granularity: 'day',
      },
    })
    expect(n).toBe(2)
    expect(store.tabs.every((t) => t.timeKey === '2025-12-03')).toBe(true)
    expect(store.tabs[0].timeRange?.start_at).toBe('2025-12-03T00:00:00Z')
  })
})
