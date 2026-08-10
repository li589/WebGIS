import { describe, expect, it } from 'vitest'
import {
  buildExpectedCoverageForSubmit,
  formatNativeStepValue,
  pruneInFlightTimeKeys,
  resolveJobLayerForActiveLayer,
  shouldUseExpectedTimelineAxis,
} from '@/utils/job-layer-coverage'
import type { ActiveLayer, ActiveRunLayerGroup, JobLayerItem } from '@/stores/layers/types'

function job(partial: Partial<JobLayerItem> & Pick<JobLayerItem, 'jobId'>): JobLayerItem {
  return {
    name: 't',
    commandType: 'analysis',
    status: 'running',
    progress: 10,
    createdAt: '',
    updatedAt: '',
    message: '',
    ...partial,
  }
}

describe('job-layer-coverage', () => {
  it('formatNativeStepValue accepts string and TimeStep', () => {
    expect(formatNativeStepValue('8d')).toBe('8d')
    expect(formatNativeStepValue({ value: 0.5, unit: 'hour' })).toBe('0.5h')
    expect(formatNativeStepValue(null)).toBeUndefined()
  })

  it('resolveJobLayerForActiveLayer prefers layer.jobLayer then catalog then group.runId', () => {
    const attached = job({ jobId: 'run-a', catalogId: 'cat-1' })
    const layer: ActiveLayer = {
      instanceId: 'i1',
      catalogId: 'cat-1',
      visible: true,
      opacity: 1,
      order: 0,
      isAdminBoundary: false,
      dataState: 'catalog',
      jobLayer: attached,
    }
    expect(resolveJobLayerForActiveLayer(layer, [], [])).toBe(attached)

    const orphan: ActiveLayer = {
      ...layer,
      jobLayer: undefined,
      runGroupId: 'g1',
    }
    const groupJob = job({ jobId: 'run-b', catalogId: 'other' })
    const groups: ActiveRunLayerGroup[] = [
      {
        groupId: 'g1',
        runId: 'run-b',
        title: 'g',
        status: 'computing',
        memberInstanceIds: ['i1'],
        dissolvable: false,
      },
    ]
    expect(resolveJobLayerForActiveLayer(orphan, [groupJob], groups)?.jobId).toBe('run-b')
  })

  it('shouldUseExpectedTimelineAxis for active / failed / ready times', () => {
    const expected = { start_at: '2025-01-01', end_at: '2025-01-31' }
    expect(
      shouldUseExpectedTimelineAxis({
        expected,
        job: job({ jobId: 'r', status: 'running' }),
        readyTimeCount: 0,
      }),
    ).toBe(true)
    expect(
      shouldUseExpectedTimelineAxis({
        expected,
        job: job({ jobId: 'r', status: 'succeeded' }),
        readyTimeCount: 2,
      }),
    ).toBe(true)
    expect(
      shouldUseExpectedTimelineAxis({
        expected,
        job: job({ jobId: 'r', status: 'succeeded' }),
        readyTimeCount: 0,
      }),
    ).toBe(false)
  })

  it('buildExpectedCoverageForSubmit swaps inverted range and picks omega 8d', () => {
    const cov = buildExpectedCoverageForSubmit({
      timeRange: { start_at: '2025-12-31', end_at: '2025-12-01' },
      workflowId: 'omega_sf_fenkuai_smap_single',
    })
    expect(cov.expectedTimeRange).toEqual({
      start_at: '2025-12-01',
      end_at: '2025-12-31',
    })
    expect(cov.expectedNativeStep).toBe('8d')
  })

  it('pruneInFlightTimeKeys drops keys already in ready list', () => {
    expect(
      pruneInFlightTimeKeys(
        ['20251203_20251210', '20251211_20251218'],
        ['20251203_20251210'],
      ),
    ).toEqual(['20251211_20251218'])
  })
})
