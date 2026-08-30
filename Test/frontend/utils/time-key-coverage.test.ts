import { describe, expect, it } from 'vitest'
import {
  normalizeTimeToken,
  timeListCoversTimeKey,
  isPlausiblePlanTimeKey,
} from '../../../Code/frontend/src/utils/time-key-coverage'
import {
  INPUT_KEY_TIME_WINDOW_ALIGN,
  resolveAlignPolicyMode,
  type DataInputPolicyItem,
} from '../../../Code/frontend/src/services/data-input-policies-api'

describe('time-key-coverage', () => {
  it('normalizes ISO and compact dates', () => {
    expect(normalizeTimeToken('2025-12-03')).toBe('20251203')
    expect(normalizeTimeToken('20251203')).toBe('20251203')
  })

  it('matches day and block windows', () => {
    expect(timeListCoversTimeKey(['20251203', '20251204'], '2025-12-03')).toBe(true)
    expect(
      timeListCoversTimeKey(['20251201_20251208'], '2025-12-03'),
    ).toBe(true)
    expect(timeListCoversTimeKey(['20251201_20251208'], '2025-12-20')).toBe(false)
  })

  it('isPlausiblePlanTimeKey accepts axis formats and rejects garbage', () => {
    expect(isPlausiblePlanTimeKey('2025-12-03')).toBe(true)
    expect(isPlausiblePlanTimeKey('2025-12')).toBe(true)
    expect(isPlausiblePlanTimeKey('2025')).toBe(true)
    expect(isPlausiblePlanTimeKey('2025-12-03T00:00:00')).toBe(true)
    expect(isPlausiblePlanTimeKey('2025-13-01')).toBe(false)
    expect(isPlausiblePlanTimeKey('not-a-date')).toBe(false)
    expect(isPlausiblePlanTimeKey('')).toBe(false)
  })
})

describe('resolveAlignPolicyMode', () => {
  const policies: DataInputPolicyItem[] = [
    {
      id: 'mod',
      scope: 'module',
      scope_id: 'omega_sf_fenkuai',
      input_key: INPUT_KEY_TIME_WINDOW_ALIGN,
      mode: 'allow_silent',
    },
    {
      id: 'layer',
      scope: 'layer_id',
      scope_id: 'method-fy-omega-doy-dynamic',
      input_key: INPUT_KEY_TIME_WINDOW_ALIGN,
      mode: 'allow_with_confirm',
    },
  ]

  it('prefers layer_id over module', () => {
    expect(
      resolveAlignPolicyMode(policies, {
        layerId: 'method-fy-omega-doy-dynamic',
        module: 'omega_sf_fenkuai',
      }),
    ).toBe('allow_with_confirm')
  })

  it('falls back to deny', () => {
    expect(resolveAlignPolicyMode([], { module: 'x' })).toBe('deny')
  })
})
