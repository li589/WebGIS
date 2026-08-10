import { describe, expect, it } from 'vitest'
import {
  defaultProductLayerNames,
  namePrefixFromDefinition,
  resolveExpectedOutputTags,
  resolveOutputNamePrefix,
} from '@/utils/workflow-expected-outputs'

describe('workflow-expected-outputs', () => {
  it('uses extra.outputs when present', () => {
    expect(
      resolveExpectedOutputTags({
        workflow_id: 'wf',
        extra: { outputs: ['SM', 'VOD', 'OMEGA'] },
        nodes: [],
      }),
    ).toEqual(['SM', 'VOD', 'OMEGA'])
  })

  it('falls back to node main_layers', () => {
    expect(
      resolveExpectedOutputTags({
        workflow_id: 'wf',
        nodes: [
          {
            type: 'module/omega_avg_daily',
            properties: { main_layers: ['SM', 'OMEGA'] },
          },
        ],
      }),
    ).toEqual(['SM', 'OMEGA'])
  })

  it('defaults to result for unknown workflows', () => {
    expect(resolveExpectedOutputTags({ workflow_id: 'plain', nodes: [] })).toEqual(['result'])
    expect(resolveExpectedOutputTags(null)).toEqual(['result'])
  })

  it('builds default product names from productTagLabel', () => {
    expect(defaultProductLayerNames(['SM', 'VOD'], 'omega_sf_fenkuai')).toEqual([
      { productTag: 'SM', name: 'SM' },
      { productTag: 'VOD', name: 'VOD' },
    ])
    expect(defaultProductLayerNames(['OMEGA'])).toEqual([{ productTag: 'OMEGA', name: 'ω' }])
    expect(defaultProductLayerNames(['result'], 'my_wf')).toEqual([
      { productTag: 'result', name: '结果' },
    ])
  })

  it('extracts module name prefix', () => {
    expect(
      namePrefixFromDefinition({
        workflow_id: 'wf',
        nodes: [{ type: 'module/omega_sf_fenkuai' }],
      }),
    ).toBe('omega_sf_fenkuai')
    expect(resolveOutputNamePrefix({ workflow_id: 'alone', nodes: [] })).toBe('alone')
  })
})
