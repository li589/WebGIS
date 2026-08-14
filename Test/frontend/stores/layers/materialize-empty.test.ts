import { describe, expect, it } from 'vitest'
import { resolveEmptyOverlayWorkflowError } from '@/stores/layers/materialize-empty'
import { WORKFLOW_COPY } from '@/ui-copy/workflow'

describe('resolveEmptyOverlayWorkflowError (BUG-4)', () => {
  it('sets empty message only when run succeeded and raw imports empty', () => {
    expect(
      resolveEmptyOverlayWorkflowError({
        runId: 'run-1',
        rawImportCount: 0,
        existingWorkflowError: null,
        emptyMessage: WORKFLOW_COPY.noMapLayers,
        runStatus: 'succeeded',
      }),
    ).toBe(WORKFLOW_COPY.noMapLayers)
  })

  it('skips while running/queued (progressive materialize)', () => {
    expect(
      resolveEmptyOverlayWorkflowError({
        runId: 'run-1',
        rawImportCount: 0,
        existingWorkflowError: null,
        emptyMessage: WORKFLOW_COPY.noMapLayers,
        runStatus: 'running',
      }),
    ).toBeNull()
    expect(
      resolveEmptyOverlayWorkflowError({
        runId: 'run-1',
        rawImportCount: 0,
        existingWorkflowError: null,
        emptyMessage: WORKFLOW_COPY.noMapLayers,
        runStatus: 'queued',
      }),
    ).toBeNull()
  })

  it('skips when runStatus omitted (fail-closed)', () => {
    expect(
      resolveEmptyOverlayWorkflowError({
        runId: 'run-1',
        rawImportCount: 0,
        existingWorkflowError: null,
        emptyMessage: WORKFLOW_COPY.noMapLayers,
      }),
    ).toBeNull()
  })

  it('does not overwrite existing materialize error', () => {
    expect(
      resolveEmptyOverlayWorkflowError({
        runId: 'run-1',
        rawImportCount: 0,
        existingWorkflowError: '工作流结果图层加载失败：boom',
        emptyMessage: WORKFLOW_COPY.noMapLayers,
        runStatus: 'succeeded',
      }),
    ).toBeNull()
  })

  it('skips when no runId or imports already present', () => {
    expect(
      resolveEmptyOverlayWorkflowError({
        rawImportCount: 0,
        existingWorkflowError: null,
        emptyMessage: WORKFLOW_COPY.noMapLayers,
        runStatus: 'succeeded',
      }),
    ).toBeNull()
    expect(
      resolveEmptyOverlayWorkflowError({
        runId: 'run-1',
        rawImportCount: 2,
        existingWorkflowError: null,
        emptyMessage: WORKFLOW_COPY.noMapLayers,
        runStatus: 'succeeded',
      }),
    ).toBeNull()
  })
})
