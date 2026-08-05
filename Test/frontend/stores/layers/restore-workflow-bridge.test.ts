/**
 * ensureRestoredRunGroup 桥接：workflowId / sourceLayerId 来自 descriptor，不写死 seed。
 * 本测验证 resolve 逻辑的纯函数副本（与 stores/layers/index.ts 语义一致）。
 */
import { describe, expect, it } from 'vitest'

type Desc = {
  layer_id: string
  workflow_id?: string | null
  workflow_name?: string | null
  display_name?: string
}

function resolveRestoreWorkflowBridge(
  catalog: Record<string, Desc>,
  layerId: string,
  catalogId: string,
): { sourceLayerId?: string; workflowId?: string } {
  const candidates = [layerId, catalogId].filter(Boolean)
  let descriptor: Desc | undefined
  for (const id of candidates) {
    if (catalog[id]) {
      descriptor = catalog[id]
      break
    }
  }
  const sourceLayerId =
    descriptor?.layer_id || (catalogId.startsWith('wf-') ? undefined : catalogId)
  const workflowId = descriptor?.workflow_id || descriptor?.workflow_name || undefined
  return { sourceLayerId, workflowId }
}

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
