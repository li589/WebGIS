import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import {
  NOTICE_TTL_MS,
  TIMELINE_CONFIRM_DEBOUNCE_MS,
  useTimelineActionBannerStore,
} from '../../../Code/frontend/src/stores/timeline-action-banner'

describe('timeline-action-banner store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.useFakeTimers()
  })

  it('notice auto-dismisses after 10s without touching confirm', () => {
    const store = useTimelineActionBannerStore()
    store.showNotice({ message: 'fail', catalogId: 'method-fy-omega-doy-dynamic' })
    expect(store.hasNotice).toBe(true)
    expect(NOTICE_TTL_MS).toBe(10_000)

    store.showConfirm({
      message: 'confirm?',
      timeKey: '2025-12-03',
      catalogIds: ['method-fy-omega-doy-dynamic'],
      canReuse: true,
      scopeLabel: '独立·风云',
    })
    expect(store.hasConfirm).toBe(true)

    vi.advanceTimersByTime(NOTICE_TTL_MS)
    expect(store.notice).toBeNull()
    expect(store.confirm).not.toBeNull()
  })

  it('confirm debounce constant is 2s', () => {
    expect(TIMELINE_CONFIRM_DEBOUNCE_MS).toBe(2_000)
  })

  it('showConfirm replaces previous and resets alignChecked from offer', () => {
    const store = useTimelineActionBannerStore()
    store.showConfirm({
      message: 'a',
      timeKey: '2025-12-01',
      catalogIds: ['a'],
      canReuse: false,
      scopeLabel: '独立·a',
      alignOffer: {
        inputKey: 'time_window_align_on_zero_intersection',
        label: 'align',
        defaultChecked: true,
      },
    })
    expect(store.alignChecked).toBe(true)
    store.setAlignChecked(false)
    store.showConfirm({
      message: 'b',
      timeKey: '2025-12-02',
      catalogIds: ['b'],
      canReuse: true,
      scopeLabel: '统一·2源',
      alignOffer: {
        inputKey: 'time_window_align_on_zero_intersection',
        label: 'align',
        defaultChecked: false,
      },
    })
    expect(store.confirm?.timeKey).toBe('2025-12-02')
    expect(store.alignChecked).toBe(false)
  })

  it('recovery does not auto-dismiss and clears notice', () => {
    const store = useTimelineActionBannerStore()
    store.showNotice({ message: 'fail toast', catalogId: 'method-fy-omega-doy-dynamic' })
    store.showRecovery({
      catalogId: 'method-fy-omega-doy-dynamic',
      message: 'error_code=coverage_gap 零交集',
      timeKey: '2025-12-03',
      offers: ['switch_online'],
    })
    expect(store.hasRecovery).toBe(true)
    expect(store.notice).toBeNull()
    vi.advanceTimersByTime(NOTICE_TTL_MS * 2)
    expect(store.recovery).not.toBeNull()
    expect(store.recovery?.offers).toEqual(['switch_online'])
    store.dismissRecovery()
    expect(store.hasRecovery).toBe(false)
  })
})
