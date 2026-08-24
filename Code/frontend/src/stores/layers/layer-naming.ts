/**
 * 图层 ID / 显示名约定（与 Docs/03-规范协议/layer-naming.md 对齐）。
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

/**
 * productTag 归并规则表（P2-A 表化，2026-08-24）。
 *
 * 此前 OMEGA_BLOCK/OMEGA_PIXEL/SM/VOD 归并以 if 分支散落
 * result-adapter.normalizeProductTag（5 分支）与 workflow-runner
 * LEGACY 三件套——本质是元数据可表达的东西。新增产品族只改此表，
 * 不再新增 if 分支。
 */
export interface ProductTagMergeRule {
  /** 归并后的规范 tag */
  canonical: string
  /** 精确相等匹配 */
  equals?: string[]
  /** 后缀匹配（_ 或 - 连接的变体，如 XX_OMEGA） */
  endsWith?: string[]
  /** 子串匹配（变体 tag，如 OMEGA_BLOCK_20251201） */
  includes?: string[]
}

export const PRODUCT_TAG_MERGE_RULES: ProductTagMergeRule[] = [
  {
    canonical: 'OMEGA',
    equals: ['OMEGA'],
    endsWith: ['_OMEGA', '-OMEGA'],
    includes: ['OMEGA_BLOCK', 'OMEGA_PIXEL', 'OMEGA_PIX'],
  },
  { canonical: 'SM', equals: ['SM'], endsWith: ['_SM', '-SM'] },
  { canonical: 'VOD', equals: ['VOD'], endsWith: ['_VOD', '-VOD'] },
]

/**
 * 旧 run 恢复兜底 tag（SM/VOD/OMEGA 三件套）。
 *
 * **退役观察期**：仅服务旧实验室 run 快照恢复；2026-08-24 起 60 天
 * （2026-10-23）无旧快照恢复回归后可整体删除：删本常量、
 * PRODUCT_TAG_MERGE_RULES 的 SM/VOD 行、LEGACY_PRODUCT_TAG_LABELS、
 * isDefaultProductDisplayName 旧标签分支及 workflow-runner 的
 * LEGACY_RESTORE_TAGS 回退链（提交路径已禁止落此兜底，2026-08-23）。
 */
export const LEGACY_RESTORE_TAGS: readonly string[] = ['SM', 'VOD', 'OMEGA']

/** productTag 归并（查表驱动，规则见 PRODUCT_TAG_MERGE_RULES）。 */
export function mergeProductTag(tag: string): string {
  for (const rule of PRODUCT_TAG_MERGE_RULES) {
    if (rule.equals?.includes(tag)) return rule.canonical
    if (rule.endsWith?.some((suffix) => tag.endsWith(suffix))) return rule.canonical
    if (rule.includes?.some((fragment) => tag.includes(fragment))) return rule.canonical
  }
  return tag
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
  if (tag === 'RESULT' || tag === 'result') {
    candidates.add('结果')
    candidates.add('结果（部分）')
    candidates.add('产出变量')
    candidates.add('产出变量（部分）')
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

/**
 * UI 显示名回退链：显式名 → 持久化 → 目录名 → dataset_key → layer_id → 未命名。
 * 见 Docs/03-规范协议/layer-naming.md
 */
export function resolveLayerDisplayLabel(options: {
  name?: string | null
  persisted?: string | null
  catalogDisplayName?: string | null
  datasetKey?: string | null
  catalogId?: string | null
  /** 导入层文件 stem，仅在无 id 可用时使用 */
  fileStem?: string | null
}): string {
  const candidates = [
    options.name,
    options.persisted,
    options.catalogDisplayName,
    options.datasetKey,
    options.catalogId,
    options.fileStem,
  ]
  for (const c of candidates) {
    const t = typeof c === 'string' ? c.trim() : ''
    if (t) return t
  }
  return '未命名图层'
}

/**
 * 导出/下载文件名基座：优先 machine id（layer_id / catalogId），不用中文显示名。
 */
export function resolveExportBasename(options: {
  layerId?: string | null
  catalogId?: string | null
  datasetKey?: string | null
  overlayLayerId?: string | null
  backendLayerId?: string | null
  sourceFilename?: string | null
  displayName?: string | null
}): string {
  const stripExt = (s: string) => s.replace(/\.(geojson|json|shp|zip|csv|tif|tiff|nc)$/i, '')
  const candidates = [
    options.layerId,
    options.catalogId,
    options.overlayLayerId,
    options.backendLayerId,
    options.datasetKey,
    options.sourceFilename ? stripExt(options.sourceFilename) : null,
    options.displayName,
  ]
  for (const c of candidates) {
    const t = typeof c === 'string' ? c.trim() : ''
    if (t) return stripExt(t)
  }
  return 'export'
}
