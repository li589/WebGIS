import { describe, expect, it } from 'vitest'

import { WORKFLOW_COPY } from '@/ui-copy/workflow'

describe('progressive overlay copy (P-01)', () => {
  it('exposes progressive sync failure / partial / ok strings', () => {
    expect(WORKFLOW_COPY.progressiveSyncFailed?.length).toBeGreaterThan(0)
    expect(WORKFLOW_COPY.progressiveSyncPartial).toContain('{count}')
    expect(WORKFLOW_COPY.progressiveSyncOk).toContain('{count}')
  })
})
