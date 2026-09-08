/**
 * 分区/自动统计表「图层」列显示名：优先活动层映射，拒绝把 layer_id 当显示名。
 */
export function looksLikeLayerId(text: string): boolean {
  const t = text.trim()
  if (!t) return true
  // 系统内 layer_id 均带确定前缀；裸 snake_case 更可能是字段/变量名
  // （如 Brightness_Temperature），不应判为 id 而吞掉真实显示名。
  return (
    t.startsWith('imported-') ||
    t.startsWith('wf-run-') ||
    t.startsWith('wf-out-') ||
    t.startsWith('ref-') ||
    t.startsWith('method-') ||
    t.startsWith('prod-')
  )
}

export function resolveStatLayerDisplayName(options: {
  layerId: string
  layerName?: string | null
  displayNameByOverlayId: Map<string, string>
  fallbackLabel?: string
}): string {
  const mapped = options.displayNameByOverlayId.get(options.layerId)
  if (mapped) return mapped
  const backendName = (options.layerName || '').trim()
  if (backendName && !looksLikeLayerId(backendName)) return backendName
  return options.fallbackLabel ?? '未命名图层'
}
