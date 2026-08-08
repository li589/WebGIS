/**
 * 提交超时后短轮询认领孤儿 run：按 command_label + 时间窗匹配 active runs。
 */

export type ReconcileRunCandidate = {
  run_id: string
  command_label?: string | null
  created_at?: string | null
  status?: string | null
  layer_id?: string | null
}

export type ClaimOrphanRunOptions = {
  commandLabel?: string | null
  catalogIdHint?: string | null
  /** 提交开始时间（ISO 或 epoch ms） */
  submitStartedAt: string | number
  /** 认领窗口（毫秒），默认 3 分钟 */
  windowMs?: number
  /** 已占用的 run id，避免误领 */
  excludeRunIds?: Iterable<string>
}

function parseTime(value: string | number | null | undefined): number | null {
  if (typeof value === 'number' && Number.isFinite(value)) return value
  if (typeof value === 'string' && value.trim()) {
    const ms = Date.parse(value)
    return Number.isFinite(ms) ? ms : null
  }
  return null
}

/**
 * 从活跃 run 列表中认领最可能对应本次提交的孤儿 run。
 * 优先：command_label 精确匹配且 created_at 落在提交窗口内；
 * 次选：仅时间窗内最近的一条（无 label 时）。
 */
export function claimOrphanWorkflowRun(
  runs: ReconcileRunCandidate[],
  options: ClaimOrphanRunOptions,
): ReconcileRunCandidate | null {
  const windowMs = options.windowMs ?? 180_000
  const submitStart = parseTime(options.submitStartedAt)
  if (submitStart == null) return null
  const exclude = new Set(options.excludeRunIds ?? [])
  const label = (options.commandLabel || '').trim()

  const inWindow = runs.filter((run) => {
    if (!run.run_id || exclude.has(run.run_id)) return false
    if (String(run.run_id).startsWith('local-submit-')) return false
    const created = parseTime(run.created_at)
    if (created == null) return false
    // 允许服务端时钟略早于客户端起步
    return created >= submitStart - 15_000 && created <= submitStart + windowMs
  })

  if (!inWindow.length) return null

  const byLabel = label ? inWindow.filter((r) => (r.command_label || '').trim() === label) : []

  const pool = byLabel.length ? byLabel : inWindow
  pool.sort((a, b) => (parseTime(b.created_at) ?? 0) - (parseTime(a.created_at) ?? 0))
  return pool[0] ?? null
}

/** 判断错误是否像客户端提交超时（服务端可能已 202） */
export function isSubmitTimeoutError(error: unknown): boolean {
  const msg = error instanceof Error ? error.message : String(error ?? '')
  return /超时|timeout|AbortError|aborted/i.test(msg)
}
