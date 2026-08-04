import { describe, expect, it } from 'vitest'

import { ANALYSIS_COPY } from '@/ui-copy/analysis'
import {
  resolveAnalysisStageKind,
  resolveAnalysisStageLabel,
  resolveAnalysisSubtitle,
  resolveStaticLayerHint,
  resolveWorkflowStageCopy,
} from '@/components/info-panel/analysis-panel-summary'

describe('analysis-panel-summary', () => {
  it('maps empty selection to empty stage label', () => {
    const kind = resolveAnalysisStageKind({
      hasRealSelection: false,
      isWeather: false,
      isImported: false,
      isImportedRaster: false,
      isAdminBoundary: false,
      canRunWorkflow: false,
    })
    expect(kind).toBe('empty')
    expect(resolveAnalysisStageLabel(kind)).toBe(ANALYSIS_COPY.stageEmpty)
    expect(resolveAnalysisSubtitle(kind)).toBe(ANALYSIS_COPY.subtitleEmpty)
  })

  it('prefers weather over workflow capability', () => {
    const kind = resolveAnalysisStageKind({
      hasRealSelection: true,
      isWeather: true,
      isImported: false,
      isImportedRaster: false,
      isAdminBoundary: false,
      canRunWorkflow: false,
    })
    expect(kind).toBe('weather')
    expect(resolveAnalysisStageLabel(kind)).toBe(ANALYSIS_COPY.stageWeather)
  })

  it('labels imported vector / raster and boundary', () => {
    expect(
      resolveAnalysisStageLabel(
        resolveAnalysisStageKind({
          hasRealSelection: true,
          isWeather: false,
          isImported: true,
          isImportedRaster: false,
          isAdminBoundary: false,
          canRunWorkflow: false,
        }),
      ),
    ).toBe(ANALYSIS_COPY.stageImportedVector)
    expect(
      resolveAnalysisStageLabel(
        resolveAnalysisStageKind({
          hasRealSelection: true,
          isWeather: false,
          isImported: false,
          isImportedRaster: true,
          isAdminBoundary: false,
          canRunWorkflow: false,
        }),
      ),
    ).toBe(ANALYSIS_COPY.stageImportedRaster)
    expect(
      resolveAnalysisStageLabel(
        resolveAnalysisStageKind({
          hasRealSelection: true,
          isWeather: false,
          isImported: false,
          isImportedRaster: false,
          isAdminBoundary: true,
          canRunWorkflow: false,
        }),
      ),
    ).toBe(ANALYSIS_COPY.stageBoundary)
    expect(resolveAnalysisSubtitle('imported_vector')).toBe(ANALYSIS_COPY.subtitleImportedVector)
    expect(resolveStaticLayerHint('imported_raster')).toBe(ANALYSIS_COPY.staticImportedRaster)
  })

  it('labels runnable workflow layers', () => {
    const kind = resolveAnalysisStageKind({
      hasRealSelection: true,
      isWeather: false,
      isImported: false,
      isImportedRaster: false,
      isAdminBoundary: false,
      canRunWorkflow: true,
    })
    expect(kind).toBe('workflow')
    expect(resolveAnalysisStageLabel(kind)).toBe(ANALYSIS_COPY.stageWorkflow)
  })

  it('resolves workflow idle copy without placeholder noise', () => {
    expect(resolveWorkflowStageCopy({ stage: 'idle', progress: 0 })).toBe(
      ANALYSIS_COPY.stageIdleNotRun,
    )
    expect(resolveWorkflowStageCopy({ stage: 'succeeded', progress: 100 })).toBe(
      ANALYSIS_COPY.stageDone,
    )
    expect(
      resolveWorkflowStageCopy({
        stage: 'idle',
        progress: 0,
        isWeather: true,
        tilePending: 3,
        tileCached: 0,
      }),
    ).toBe(ANALYSIS_COPY.stageLoading)
    expect(
      resolveWorkflowStageCopy({
        stage: 'succeeded',
        progress: 0,
        isWeather: true,
        tilePending: 0,
        tileCached: 12,
      }),
    ).toBe(ANALYSIS_COPY.stageCached)
  })
})
