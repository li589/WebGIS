/**
 * 判断是否应在「工作流已成功但无可上图图层」时写入可见空态。
 * 用户已 dismiss 全部 overlay 时 rawImportCount 仍 >0（过滤前），由调用方在过滤后再处理，不走此函数。
 */
export function resolveEmptyOverlayWorkflowError(args: {
  runId?: string
  /** materialize / result_refs 提取后、dismiss 过滤前的 import 数 */
  rawImportCount: number
  existingWorkflowError: string | null
  emptyMessage: string
}): string | null {
  if (!args.runId) return null
  if (args.existingWorkflowError) return null
  if (args.rawImportCount > 0) return null
  return args.emptyMessage
}
