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
 * Backend overall stage: weighted span from ScopedProgressLogger (``workflow.dispatch``).
 * ``workflow_dispatch`` is only a bookend (0% start / 100% end) — do not Math.max it
 * with the weighted stage or a finished bookend will pin the bar at 100% mid-run.
 */
export function isOverallProgressStage(nodeIdOrStage: string | null | undefined): boolean {
  const id = String(nodeIdOrStage ?? '').trim()
  return id === 'workflow.dispatch' || id === 'workflow_dispatch'
}

/** Weighted overall bar only — excludes lifecycle bookend ``workflow_dispatch``. */
export function isWeightedOverallProgressStage(
  nodeIdOrStage: string | null | undefined,
): boolean {
  return String(nodeIdOrStage ?? '').trim() === 'workflow.dispatch'
}

/** Internal per-node bookkeeping stages — hide from the node-progress list. */
const HIDDEN_MODULE_STAGES = new Set(['data_prepare'])

export function isInternalWorkflowNodeStage(nodeIdOrStage: string | null | undefined): boolean {
  const id = String(nodeIdOrStage ?? '').trim()
  if (HIDDEN_MODULE_STAGES.has(id)) return true
  return id.startsWith('workflow.node.')
}

/** Whether a node stage should appear in the per-node progress list (not job bar). */
export function isDisplayableNodeStage(nodeIdOrStage: string | null | undefined): boolean {
  const id = String(nodeIdOrStage ?? '').trim()
  if (!id) return false
  if (isOverallProgressStage(id)) return false
  if (isInternalWorkflowNodeStage(id)) return false
  return true
}

/** Module stage suffix: ``n12:omega_sf_fenkuai`` → ``omega_sf_fenkuai``. */
export function nodeProgressModuleKey(nodeId: string): string {
  const id = String(nodeId ?? '').trim()
  if (!id) return ''
  const colon = id.lastIndexOf(':')
  if (colon >= 0) return id.slice(colon + 1)
  return id
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

function pickRicherMessage(a?: string, b?: string): string | undefined {
  if (!a?.trim()) return b
  if (!b?.trim()) return a
  return b.length >= a.length ? b : a
}

function pickBetterNodeProgress<
  T extends {
    nodeId: string
    progress: number
    updatedAt?: string
    eventId?: string
    terminalHint?: string
    detail?: Record<string, unknown> | null
  },
>(a: T, b: T): T {
  if (a.progress !== b.progress) return a.progress > b.progress ? a : b
  const aScoped = a.nodeId.includes(':')
  const bScoped = b.nodeId.includes(':')
  if (aScoped !== bScoped) return aScoped ? a : b
  const aDetail = a.detail && Object.keys(a.detail).length > 0
  const bDetail = b.detail && Object.keys(b.detail).length > 0
  if (aDetail !== bDetail) return aDetail ? a : b
  return nodeProgressSortKey(b) >= nodeProgressSortKey(a) ? b : a
}

function mergeBareScopedNodeProgress<
  T extends {
    nodeId: string
    nodeLabel?: string
    stage?: string
    progress: number
    message?: string
    terminalHint?: string
    detail?: Record<string, unknown> | null
    artifacts?: string[]
    updatedAt?: string
    eventId?: string
  },
>(bare: T, scoped: T): T {
  const primary = pickBetterNodeProgress(bare, scoped)
  const secondary = primary === bare ? scoped : bare
  return {
    ...primary,
    progress: Math.max(bare.progress, scoped.progress),
    terminalHint: bare.terminalHint ?? scoped.terminalHint ?? secondary.terminalHint,
    message: pickRicherMessage(bare.message, scoped.message),
    detail: (primary.detail ?? secondary.detail) as T['detail'],
    artifacts: scoped.artifacts?.length ? scoped.artifacts : bare.artifacts,
    updatedAt: primary.updatedAt ?? secondary.updatedAt,
    eventId: primary.eventId ?? secondary.eventId,
  }
}

/**
 * Dedupe by nodeId, then collapse bare module stages into their scoped
 * ``graphNode:stage`` twin (stage_start/end vs emit_progress), while keeping
 * multiple scoped instances (``n1:download`` vs ``n2:download``) separate.
 */
export function dedupeNodeProgress<
  T extends {
    nodeId: string
    nodeLabel?: string
    stage?: string
    progress: number
    message?: string
    terminalHint?: string
    detail?: Record<string, unknown> | null
    artifacts?: string[]
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

  const grouped = new Map<string, T[]>()
  for (const node of byId.values()) {
    const key = nodeProgressModuleKey(node.nodeId)
    grouped.set(key, [...(grouped.get(key) ?? []), node])
  }

  const merged: T[] = []
  for (const [moduleKey, group] of grouped) {
    const bare = group.filter((n) => n.nodeId === moduleKey)
    const scoped = group.filter((n) => n.nodeId !== moduleKey && n.nodeId.includes(':'))
    const rest = group.filter((n) => !bare.includes(n) && !scoped.includes(n))

    if (bare.length === 1 && scoped.length === 1) {
      merged.push(mergeBareScopedNodeProgress(bare[0]!, scoped[0]!))
    } else if (bare.length === 1 && scoped.length > 1) {
      merged.push(...scoped, ...rest)
    } else if (bare.length === 1 && scoped.length === 0) {
      merged.push(bare[0]!, ...rest)
    } else {
      merged.push(...group)
    }
  }

  const byStageLabel = new Map<string, T>()
  for (const node of merged) {
    if (node.nodeId.includes(':')) {
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
  const weighted = (opts.nodeProgress ?? []).filter((n) =>
    isWeightedOverallProgressStage(n.nodeId),
  )
  if (weighted.length) {
    return Math.max(...weighted.map((n) => normalizeWorkflowProgress(n.progress)))
  }
  // No weighted dispatch yet: keep monotonic max of snapshot/current.
  // Mid-run 100% inflation is prevented upstream (ignore naked event.progress /
  // workflow_dispatch bookend), not by forcing snapshot-only here.
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
