/**
 * 图层 ID / 显示名约定（与 Docs/03-规范协议/layer-naming.md 对齐）。
 * 稳定目录 layer_id 不在此重命名；仅提供前缀判断与显示名规范化。
 */

import { isEnglishInversionCatalogId } from './inversion-catalog'

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

/**
 * productTag 归并规则表（P2-A 表化，2026-08-24）。
 *
 * 此前 OMEGA_BLOCK/OMEGA_PIXEL 归并以 if 分支散落
 * result-adapter.normalizeProductTag——本质是元数据可表达的东西。
 * 新增产品族只改此表，不再新增 if 分支。
 *
 * 注：SM/VOD 归并行与 LEGACY_RESTORE_TAGS/LEGACY_PRODUCT_TAG_LABELS
 * 已于 2026-08-24 交付前退役（61 种子全带中文配置后旧 run 快照不再
 * 回退三占位）；现行种子产物 tag（SM/VOD/OMEGA）为精确值，透传即可。
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
]

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
  // 旧长标签（LEGACY_PRODUCT_TAG_LABELS）与 OMEGA 旧显示名候选已随
  // LEGACY 退役移除（2026-08-24）；现行显示名来自种子 output_labels。
  if (tag === 'RESULT' || tag === 'result') {
    candidates.add('结果')
    candidates.add('结果（部分）')
    candidates.add('分析结果')
    candidates.add('分析结果（部分）')
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
 * 英文反演技术 id（omega_sf_fenkuai_* / imported-omega_*）不得出现在显示名链中。
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
    if (!t) continue
    if (isEnglishInversionCatalogId(t)) continue
    return t
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
