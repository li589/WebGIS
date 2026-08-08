import { describe, expect, it } from 'vitest'
import { resolveEmptyOverlayWorkflowError } from '@/stores/layers/materialize-empty'
import { WORKFLOW_COPY } from '@/ui-copy/workflow'

describe('resolveEmptyOverlayWorkflowError (BUG-4)', () => {
  it('sets empty message when runId present and raw imports empty', () => {
    expect(
      resolveEmptyOverlayWorkflowError({
        runId: 'run-1',
        rawImportCount: 0,
        existingWorkflowError: null,
        emptyMessage: WORKFLOW_COPY.noMapLayers,
      }),
    ).toBe(WORKFLOW_COPY.noMapLayers)
  })

  it('does not overwrite existing materialize error', () => {
    expect(
      resolveEmptyOverlayWorkflowError({
        runId: 'run-1',
        rawImportCount: 0,
        existingWorkflowError: '工作流结果图层加载失败：boom',
        emptyMessage: WORKFLOW_COPY.noMapLayers,
      }),
    ).toBeNull()
  })

  it('skips when no runId or imports already present', () => {
    expect(
      resolveEmptyOverlayWorkflowError({
        rawImportCount: 0,
        existingWorkflowError: null,
        emptyMessage: WORKFLOW_COPY.noMapLayers,
      }),
    ).toBeNull()
    expect(
      resolveEmptyOverlayWorkflowError({
        runId: 'run-1',
        rawImportCount: 2,
        existingWorkflowError: null,
        emptyMessage: WORKFLOW_COPY.noMapLayers,
      }),
    ).toBeNull()
  })
})
