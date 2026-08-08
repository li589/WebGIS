/** local-submit 乐观 ID：仅前端占位，不可 track / retry API / cancel API。 */

export const LOCAL_SUBMIT_PREFIX = 'local-submit-'

export function isLocalSubmitJobId(jobId: string | null | undefined): boolean {
  return Boolean(jobId && String(jobId).startsWith(LOCAL_SUBMIT_PREFIX))
}

export function localSubmitJobId(catalogId: string): string {
  return `${LOCAL_SUBMIT_PREFIX}${catalogId}`
}

/** 是否应写入 tracked-workflow-runs（恢复列表） */
export function shouldTrackWorkflowRunId(jobId: string | null | undefined): boolean {
  return Boolean(jobId) && !isLocalSubmitJobId(jobId)
}

/** 取消乐观提交时不应调用后端 cancel */
export function shouldCallCancelApi(jobId: string | null | undefined): boolean {
  return Boolean(jobId) && !isLocalSubmitJobId(jobId)
}

/** 假 ID 重试应走重新提交，而非 POST /retry */
export function shouldResubmitInsteadOfRetry(jobId: string | null | undefined): boolean {
  return isLocalSubmitJobId(jobId)
}
