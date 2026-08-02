import { describe, expect, it } from 'vitest'
import {
  normalizeAnalysisFocusIds,
  resolveAnalysisTabForFocusIds,
} from './analysis-tab-focus'

describe('analysis-tab-focus', () => {
  it('maps known section ids to tabs', () => {
    expect(resolveAnalysisTabForFocusIds(['layer-style', 'global-overview'])).toBe('style')
    expect(resolveAnalysisTabForFocusIds(['report-section', 'result-section'])).toBe('meta')
    expect(resolveAnalysisTabForFocusIds(['result-section'])).toBe('visual')
    expect(resolveAnalysisTabForFocusIds(['point-weather'])).toBe('visual')
    expect(resolveAnalysisTabForFocusIds(['overlay-compare'])).toBe('visual')
    expect(resolveAnalysisTabForFocusIds(['analysis-tools'])).toBe('tools')
  })

  it('maps layer-* and hotspot-* prefixes', () => {
    expect(resolveAnalysisTabForFocusIds(['layer-abc'])).toBe('meta')
    expect(resolveAnalysisTabForFocusIds(['hotspot-1'])).toBe('visual')
  })

  it('normalizes legacy overview-section id', () => {
    expect(normalizeAnalysisFocusIds(['overview-section', 'layer-style'])).toEqual([
      'global-overview',
      'layer-style',
    ])
  })

  it('returns null for unknown ids', () => {
    expect(resolveAnalysisTabForFocusIds(['unknown'])).toBeNull()
    expect(resolveAnalysisTabForFocusIds([])).toBeNull()
  })
})
