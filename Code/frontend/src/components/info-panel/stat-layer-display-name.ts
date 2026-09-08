/**
 * 分区/自动统计表「图层」列显示名：优先活动层映射，拒绝把 layer_id 当显示名。
 */
export function looksLikeLayerId(text: string): boolean {
  const t = text.trim()
  if (!t) return true
  return (
    t.startsWith('imported-') ||
    t.startsWith('wf-run-') ||
    t.startsWith('wf-out-') ||
    t.startsWith('ref-') ||
    t.startsWith('method-') ||
    t.startsWith('prod-') ||
    /^[a-z0-9]+(?:[_-][a-z0-9]+)+$/i.test(t)
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
