/** Human-readable labels for workflow event channels. */

const CHANNEL_LABELS: Record<string, string> = {
  system: '系统',
  status: '状态',
  log: '日志',
  progress: '进度',
  artifact: '产物',
  validation: '校验',
}

export function formatWorkflowEventLine(channel: string, message: string): string {
  const label = CHANNEL_LABELS[channel.trim().toLowerCase()] ?? channel
  const body = message.trim()
  return body ? `${label} · ${body}` : label
}
