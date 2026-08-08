/** Map backend error_code / diagnostic tokens to user-facing Chinese messages. */

const ERROR_CODE_MESSAGES: Record<string, string> = {
  workflow_cancelled_by_user: '工作流已被用户取消。',
  workflow_capacity_reached: '工作流并发数已达上限，请稍后重试。',
  workflow_validation_failed: '工作流参数校验未通过。',
  compile_error: '工作流图编译失败。',
  no_bridge: '未找到匹配的工作流引擎，请检查图层与请求参数。',
  terminal_failure: '工作流执行失败（不可自动重试）。',
  transient_failure: '工作流瞬态失败，系统将自动重试。',
}

/** Translate a single diagnostic line (may include error_code= prefix). */
export function localizeWorkflowDiagnostic(line: string): string {
  const trimmed = line.trim()
  if (!trimmed) return trimmed

  const codeMatch = trimmed.match(/error_code=([a-z0-9_]+)/i)
  if (codeMatch?.[1] && ERROR_CODE_MESSAGES[codeMatch[1]]) {
    return ERROR_CODE_MESSAGES[codeMatch[1]]
  }

  if (trimmed.startsWith('error_message=')) {
    const raw = trimmed.slice('error_message='.length).trim()
    return localizeWorkflowErrorMessage(raw)
  }

  return trimmed
}

/** Translate raw backend / bridge error messages when possible. */
export function localizeWorkflowErrorMessage(message: string): string {
  const text = message.trim()
  if (!text) return text

  const lower = text.toLowerCase()
  if (lower.includes('workflow capacity reached') || lower.includes('429')) {
    return ERROR_CODE_MESSAGES.workflow_capacity_reached
  }
  if (lower.includes('no workflow bridge matched')) {
    return ERROR_CODE_MESSAGES.no_bridge
  }
  if (lower.includes('cancelled') && lower.includes('user')) {
    return ERROR_CODE_MESSAGES.workflow_cancelled_by_user
  }
  if (/[\u4e00-\u9fff]/.test(text)) return text
  return text
}

export function localizeWorkflowDiagnostics(lines: string[] | undefined): string[] {
  if (!lines?.length) return []
  return lines.map((line) => localizeWorkflowDiagnostic(line)).filter(Boolean)
}
