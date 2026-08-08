/**
 * Resolve restore bridge fields from a runtime catalog map (no hard-coded seeds).
 */

export type RestoreBridgeDescriptor = {
  layer_id: string
  workflow_id?: string | null
  workflow_name?: string | null
  display_name?: string
}

export function resolveRestoreWorkflowBridge(
  catalog: Record<string, RestoreBridgeDescriptor>,
  layerId: string,
  catalogId: string,
): { sourceLayerId?: string; workflowId?: string } {
  const candidates = [layerId, catalogId].filter(Boolean)
  let descriptor: RestoreBridgeDescriptor | undefined
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
