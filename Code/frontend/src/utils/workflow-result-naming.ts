/** 统一结果图层显示名：`{工作流短名} · {PRODUCT} · {time_label|静态}` */

export function shortWorkflowName(name: string | null | undefined, maxLen = 24): string {
  const raw = (name || '').trim()
  if (!raw) return '工作流'
  if (raw.length <= maxLen) return raw
  return `${raw.slice(0, Math.max(1, maxLen - 1))}…`
}

export function formatRunResultLayerName(input: {
  workflowName?: string | null
  productTag?: string | null
  timeLabel?: string | null
  staticLabel?: string
}): string {
  const wf = shortWorkflowName(input.workflowName)
  const product = (input.productTag || '结果').trim().toUpperCase()
  const time =
    (input.timeLabel || '').trim() || (input.staticLabel != null ? input.staticLabel : '静态')
  return `${wf} · ${product} · ${time}`
}
