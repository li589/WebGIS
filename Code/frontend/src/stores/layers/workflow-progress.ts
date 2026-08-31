/**
 * Normalize workflow/node progress to 0–100, preferring chunk ratios when available.
 *
 * Overall job progress must NOT be Math.max across module nodes: a finished
 * download at 100% would otherwise show the whole run as complete while inversion
 * has barely started. Prefer ``workflow.dispatch`` (backend weighted overall).
 */

export type WorkflowProgressDetail = {
  chunksDone?: number
  chunksTotal?: number
  pixelsDone?: number
  pixelsTotal?: number
}

export type WorkflowProgressNodeLike = {
  nodeId: string
  progress: number
  detail?: WorkflowProgressDetail | null
}

/**
 * Backend overall stage from WorkflowRunner._ScopedProgressLogger.
 * Exact match only — ``workflow.node.n1`` stage_end is also progress=100 and
 * must NOT be treated as the job bar.
 */
export function isOverallProgressStage(nodeIdOrStage: string | null | undefined): boolean {
  return String(nodeIdOrStage ?? '').trim() === 'workflow.dispatch'
}

/** Internal per-node bookkeeping stages — hide from the node-progress list. */
export function isInternalWorkflowNodeStage(nodeIdOrStage: string | null | undefined): boolean {
  return String(nodeIdOrStage ?? '')
    .trim()
    .startsWith('workflow.node.')
}

/** Whether a node stage should appear in the per-node progress list (not job bar). */
export function isDisplayableNodeStage(nodeIdOrStage: string | null | undefined): boolean {
  const id = String(nodeIdOrStage ?? '').trim()
  if (!id) return false
  if (isOverallProgressStage(id)) return false
  if (isInternalWorkflowNodeStage(id)) return false
  return true
}

function nodeProgressSortKey(node: {
  updatedAt?: string
  eventId?: string
  progress: number
}): number {
  const at = node.updatedAt ? Date.parse(node.updatedAt) : NaN
  if (Number.isFinite(at)) return at
  return node.progress
}

/**
 * Dedupe by nodeId. Legacy fallback: collapse bare module ids that share
 * stage+label only when neither uses ``graphNode:stage`` form (avoid merging
 * two parallel instances of the same module).
 */
export function dedupeNodeProgress<
  T extends {
    nodeId: string
    nodeLabel?: string
    stage?: string
    progress: number
    updatedAt?: string
    eventId?: string
  },
>(nodes: T[] | null | undefined): T[] {
  if (!nodes?.length) return []
  const byId = new Map<string, T>()
  for (const node of nodes) {
    const existing = byId.get(node.nodeId)
    if (!existing || nodeProgressSortKey(node) >= nodeProgressSortKey(existing)) {
      byId.set(node.nodeId, node)
    }
  }
  const deduped = [...byId.values()]
  const byStageLabel = new Map<string, T>()
  for (const node of deduped) {
    const scoped = node.nodeId.includes(':')
    if (scoped) {
      byStageLabel.set(`id:${node.nodeId}`, node)
      continue
    }
    const key = `${node.stage ?? ''}\0${node.nodeLabel ?? node.nodeId}`
    const existing = byStageLabel.get(key)
    if (!existing || nodeProgressSortKey(node) >= nodeProgressSortKey(existing)) {
      byStageLabel.set(key, node)
    }
  }
  return [...byStageLabel.values()]
}

export function filterDisplayableNodeProgress<
  T extends {
    nodeId: string
    nodeLabel?: string
    stage?: string
    progress: number
    updatedAt?: string
    eventId?: string
  },
>(nodes: T[] | null | undefined): T[] {
  return dedupeNodeProgress((nodes ?? []).filter((n) => isDisplayableNodeStage(n.nodeId)))
}

export function normalizeWorkflowProgress(
  raw: number | null | undefined,
  detail?: WorkflowProgressDetail | null,
): number {
  let pct = 0
  if (typeof raw === 'number' && Number.isFinite(raw)) {
    pct = raw >= 0 && raw <= 1 ? raw * 100 : raw
  }
  if (
    detail &&
    typeof detail.chunksTotal === 'number' &&
    detail.chunksTotal > 0 &&
    typeof detail.chunksDone === 'number' &&
    Number.isFinite(detail.chunksDone)
  ) {
    pct = Math.max(pct, (detail.chunksDone / detail.chunksTotal) * 100)
  } else if (
    detail &&
    typeof detail.pixelsTotal === 'number' &&
    detail.pixelsTotal > 0 &&
    typeof detail.pixelsDone === 'number' &&
    Number.isFinite(detail.pixelsDone)
  ) {
    pct = Math.max(pct, (detail.pixelsDone / detail.pixelsTotal) * 100)
  }
  return Math.max(0, Math.min(100, Math.round(pct)))
}

/**
 * Resolve the job-level progress bar value.
 *
 * When ``workflow.dispatch`` is present, it is authoritative: backend already
 * weights node spans. Chunk/pixel detail on that stage is module-local and must
 * not inflate the bar. Stale inflated ``current`` (e.g. from an older FE that
 * max'd module / workflow.node 100%) is corrected downward.
 *
 * Without a dispatch stage, fall back to snapshot/current only — never max
 * across fy_download / omega_sf_fenkuai / workflow.node.* .
 */
export function resolveJobOverallProgress(opts: {
  current?: number | null
  snapshot?: number | null
  nodeProgress?: WorkflowProgressNodeLike[] | null
}): number {
  const dispatch = (opts.nodeProgress ?? []).find((n) => isOverallProgressStage(n.nodeId))
  if (dispatch) {
    // Weighted overall only — ignore chunk/pixel detail attached to the same event.
    return normalizeWorkflowProgress(dispatch.progress)
  }
  const candidates: number[] = []
  if (typeof opts.snapshot === 'number' && Number.isFinite(opts.snapshot)) {
    candidates.push(normalizeWorkflowProgress(opts.snapshot))
  }
  if (typeof opts.current === 'number' && Number.isFinite(opts.current)) {
    candidates.push(normalizeWorkflowProgress(opts.current))
  }
  if (candidates.length === 0) return 0
  return Math.max(0, Math.min(100, Math.max(...candidates)))
}
