/**
 * 图层 ID / 显示名约定（与 .ai/docs/specs/layer-naming.md 对齐）。
 * 稳定目录 layer_id 不在此重命名；仅提供前缀判断与显示名规范化。
 */

export const LAYER_ID_PREFIX = {
  ref: 'ref-',
  prod: 'prod-',
  method: 'method-',
  obs: 'obs-',
  imported: 'imported-',
  wfRun: 'wf-run-',
  wfOut: 'wf-out-',
} as const

/** TOC / prompt 显示名最大长度（超出截断） */
export const MAX_LAYER_DISPLAY_NAME_LENGTH = 80

/** 旧版变量层长显示名（兼容已持久化/已改写的 name） */
export const LEGACY_PRODUCT_TAG_LABELS: Record<string, string> = {
  SM: 'SM（土壤湿度）',
  VOD: 'VOD（植被光学厚度）',
  OMEGA: 'ω（反演参数）',
  result: '计算结果',
}

export function isRuntimeCatalogId(catalogId: string): boolean {
  const id = catalogId.trim()
  if (!id) return false
  return (
    id.startsWith(LAYER_ID_PREFIX.wfRun) ||
    id.startsWith(LAYER_ID_PREFIX.wfOut) ||
    id.startsWith(LAYER_ID_PREFIX.imported)
  )
}

/** 规范化用户输入的显示名；空串返回 null */
export function normalizeDisplayName(name: string): string | null {
  const trimmed = name.trim().replace(/\s+/g, ' ')
  if (!trimmed) return null
  if (trimmed.length > MAX_LAYER_DISPLAY_NAME_LENGTH) {
    return trimmed.slice(0, MAX_LAYER_DISPLAY_NAME_LENGTH)
  }
  return trimmed
}

/**
 * 是否仍为产品默认显示名（含「（部分）」后缀与旧长标签）。
 * 用于渐进失败路径：勿覆盖用户自定义名。
 */
export function isDefaultProductDisplayName(
  name: string | null | undefined,
  productTag: string | null | undefined,
  currentLabel: string,
): boolean {
  const n = (name ?? '').trim()
  if (!n) return true
  const tag = (productTag ?? '').trim().toUpperCase()
  const candidates = new Set<string>()
  if (currentLabel.trim()) {
    candidates.add(currentLabel.trim())
    candidates.add(`${currentLabel.trim()}（部分）`)
  }
  const legacy = tag ? LEGACY_PRODUCT_TAG_LABELS[tag] : undefined
  if (legacy) {
    candidates.add(legacy)
    candidates.add(`${legacy}（部分）`)
  }
  if (tag === 'OMEGA') {
    candidates.add('ω')
    candidates.add('ω（部分）')
    candidates.add('OMEGA')
  }
  return candidates.has(n)
}

/** 移除图层时需清理的 display-name 持久化键 */
export function collectLayerDisplayNameKeys(layer: {
  instanceId: string
  catalogId: string
  importedVector?: { backendLayerId?: string } | null
  importedRaster?: { overlayLayerId?: string } | null
}): string[] {
  const keys = new Set<string>()
  keys.add(layer.instanceId)
  keys.add(layer.catalogId)
  const backendId = layer.importedVector?.backendLayerId
  if (backendId) keys.add(backendId)
  const overlayId = layer.importedRaster?.overlayLayerId
  if (overlayId) keys.add(overlayId)
  return [...keys].filter(Boolean)
}
