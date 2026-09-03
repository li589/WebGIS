/**
 * 工作流 succeeded 后 attach 物化竞态 / 会话瞬断时的延迟重试（poller + restore 共用）。
 */

export const SUCCEEDED_ATTACH_RETRY_MS = 4_000

/** 空态横幅应在 attach 重试之后确认（略大于 retry 间隔）。 */
export const EMPTY_OVERLAY_CONFIRM_AFTER_RETRY_MS = SUCCEEDED_ATTACH_RETRY_MS + 1_500

const succeededAttachRetryTimers = new Map<string, ReturnType<typeof setTimeout>>()

export function hasPendingAttachRetry(runId: string | undefined | null): boolean {
  const id = String(runId || '').trim()
  return Boolean(id && succeededAttachRetryTimers.has(id))
}

export function clearAttachRetry(runId: string | undefined | null): void {
  const id = String(runId || '').trim()
  if (!id) return
  const handle = succeededAttachRetryTimers.get(id)
  if (handle !== undefined) {
    window.clearTimeout(handle)
    succeededAttachRetryTimers.delete(id)
  }
}

export interface ScheduleAttachRetryOptions {
  runId: string
  catalogId: string
  resultRefs: unknown
  attach: (
    resultRefs: unknown,
    catalogId: string,
    runId: string,
    opts?: { forceBind?: boolean },
  ) => Promise<number>
  cleanup: (runId: string, opts?: { succeeded?: boolean }) => void
  isRunDismissed: (runId: string) => boolean
  /** 组内仍有未绑定占位（如缺 OMEGA）时，重试后也不要立刻 cleanup */
  hasUnboundPlaceholders?: (runId: string) => boolean
}

function maybeCleanupAfterAttach(
  runId: string,
  boundCount: number,
  cleanup: ScheduleAttachRetryOptions['cleanup'],
  hasUnboundPlaceholders?: (runId: string) => boolean,
): void {
  if (boundCount <= 0) return
  if (hasUnboundPlaceholders?.(runId)) return
  cleanup(runId, { succeeded: true })
}

/** 终态 succeeded 但首次 attach 返回 0 / 部分绑定时调度 forceBind 重试。 */
export function scheduleSucceededAttachRetry(opts: ScheduleAttachRetryOptions): void {
  const {
    runId,
    catalogId,
    resultRefs,
    attach,
    cleanup,
    isRunDismissed,
    hasUnboundPlaceholders,
  } = opts
  if (!runId || succeededAttachRetryTimers.has(runId)) return
  succeededAttachRetryTimers.set(
    runId,
    window.setTimeout(() => {
      succeededAttachRetryTimers.delete(runId)
      if (isRunDismissed(runId)) return
      void attach(resultRefs, catalogId, runId, { forceBind: true }).then((boundCount) => {
        maybeCleanupAfterAttach(runId, boundCount, cleanup, hasUnboundPlaceholders)
      })
    }, SUCCEEDED_ATTACH_RETRY_MS),
  )
}
