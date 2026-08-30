/**
 * source-route-policy — 本地优先 / 在线回退决策单测。
 */
import { describe, expect, it } from 'vitest'

import type { LayerDataCoverageResponse } from '../../../Code/frontend/src/services/layer-coverage-api'
import {
  decideSourceRoute,
  descriptorEligibleForSourceRoute,
  inferDefaultVariant,
  shouldConfirmSwitchOnlineOnCoverageGap,
  shouldSilentSwitchOnlineOnCoverageGap,
} from '../../../Code/frontend/src/utils/source-route-policy'

function coverage(partial: {
  localDates?: string[]
  online?: { available: boolean; start?: string; end?: string }
}): LayerDataCoverageResponse {
  return {
    layer_id: 'ndvi',
    channels: {
      local: {
        available: Boolean(partial.localDates?.length),
        dates: partial.localDates ?? [],
      },
      online: {
        available: partial.online?.available ?? false,
        coverage_start: partial.online?.start ?? null,
        coverage_end: partial.online?.end ?? null,
        native_step: '1M',
      },
    },
  }
}

describe('descriptorEligibleForSourceRoute', () => {
  it('requires both local and online workflow_id', () => {
    expect(descriptorEligibleForSourceRoute(null)).toBe(false)
    expect(
      descriptorEligibleForSourceRoute({
        workflow_variants: { online: { workflow_id: 'ndvi_online_read' } },
      }),
    ).toBe(false)
    expect(
      descriptorEligibleForSourceRoute({
        workflow_variants: {
          online: { workflow_id: 'ndvi_online_read' },
          local: { workflow_id: 'ndvi_local_read' },
        },
      }),
    ).toBe(true)
  })
})

describe('decideSourceRoute', () => {
  it('skips when deny or ineligible', () => {
    expect(
      decideSourceRoute({
        mode: 'deny',
        eligible: true,
        coverage: coverage({ localDates: ['20230101'] }),
        timeKey: '2023-01-01',
      }).action,
    ).toBe('skip')
    expect(
      decideSourceRoute({
        mode: 'allow_silent',
        eligible: false,
        coverage: null,
      }).action,
    ).toBe('skip')
  })

  it('uses local when dates hit', () => {
    const d = decideSourceRoute({
      mode: 'allow_silent',
      eligible: true,
      coverage: coverage({ localDates: ['20230101', '20230201'] }),
      timeKey: '2023-01-01',
    })
    expect(d).toEqual({ action: 'use', variant: 'local', reason: 'local_dates_hit' })
  })

  it('silent online when local dates miss', () => {
    const d = decideSourceRoute({
      mode: 'allow_silent',
      eligible: true,
      coverage: coverage({
        localDates: ['20220101'],
        online: { available: true, start: '2000-01', end: '2025-06' },
      }),
      timeKey: '2024-07-01',
    })
    expect(d.action).toBe('use')
    if (d.action === 'use') expect(d.variant).toBe('online')
  })

  it('confirm_online when mode is allow_with_confirm', () => {
    const d = decideSourceRoute({
      mode: 'allow_with_confirm',
      eligible: true,
      coverage: coverage({
        localDates: ['20220101'],
        online: { available: true, start: '2000-01', end: '2025-06' },
      }),
      timeKey: '2024-07-01',
    })
    expect(d.action).toBe('confirm_online')
  })

  it('optimistic local when dates empty and default local', () => {
    const d = decideSourceRoute({
      mode: 'allow_silent',
      eligible: true,
      coverage: coverage({ localDates: [] }),
      timeKey: '2024-07-01',
      defaultVariant: 'local',
    })
    expect(d).toEqual({ action: 'use', variant: 'local', reason: 'local_optimistic' })
  })

  it('default online + empty dates routes online when window ok', () => {
    const d = decideSourceRoute({
      mode: 'allow_silent',
      eligible: true,
      coverage: coverage({
        localDates: [],
        online: { available: true, start: '2000-01', end: '2025-06' },
      }),
      timeKey: '2024-07-01',
      defaultVariant: 'online',
    })
    expect(d.action).toBe('use')
    if (d.action === 'use') {
      expect(d.variant).toBe('online')
      expect(d.reason).toContain('default_online')
    }
  })

  it('inferDefaultVariant matches workflow_id', () => {
    expect(
      inferDefaultVariant({
        workflow_id: 'omega_sf_fenkuai_smap_online',
        workflow_variants: {
          online: { workflow_id: 'omega_sf_fenkuai_smap_online' },
          local: { workflow_id: 'omega_sf_fenkuai_smap_single' },
        },
      }),
    ).toBe('online')
    expect(
      inferDefaultVariant({
        workflow_id: 'ndvi_local_read',
        workflow_variants: {
          online: { workflow_id: 'ndvi_online_read' },
          local: { workflow_id: 'ndvi_local_read' },
        },
      }),
    ).toBe('local')
  })
})

describe('coverage_gap helpers', () => {
  it('maps modes', () => {
    expect(shouldSilentSwitchOnlineOnCoverageGap('allow_silent')).toBe(true)
    expect(shouldSilentSwitchOnlineOnCoverageGap('deny')).toBe(false)
    expect(shouldConfirmSwitchOnlineOnCoverageGap('allow_with_confirm')).toBe(true)
  })
})
