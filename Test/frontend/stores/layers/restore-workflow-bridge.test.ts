/**
 * ensureRestoredRunGroup 桥接：workflowId / sourceLayerId 来自 descriptor，不写死 seed。
 */
import { describe, expect, it } from 'vitest'

import { resolveRestoreWorkflowBridge } from '@/stores/layers/restore-workflow-bridge'

describe('restore workflow bridge', () => {
  it('uses descriptor workflow_id instead of hard-coded omega seed', () => {
    const catalog = {
      'omega-sf-fenkuai': {
        layer_id: 'omega-sf-fenkuai',
        workflow_id: 'omega_sf_fenkuai_smap_single',
        display_name: 'SF',
      },
    }
    const bridge = resolveRestoreWorkflowBridge(catalog, 'omega-sf-fenkuai', 'omega-sf-fenkuai')
    expect(bridge.sourceLayerId).toBe('omega-sf-fenkuai')
    expect(bridge.workflowId).toBe('omega_sf_fenkuai_smap_single')
  })

  it('falls back without inventing a seed id when descriptor missing', () => {
    const bridge = resolveRestoreWorkflowBridge({}, 'custom-layer', 'custom-layer')
    expect(bridge.sourceLayerId).toBe('custom-layer')
    expect(bridge.workflowId).toBeUndefined()
  })
})
