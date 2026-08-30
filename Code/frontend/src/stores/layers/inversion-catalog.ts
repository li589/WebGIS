/**
 * 反演英文 workflow / overlay id → 目录 method-* 成员映射。
 * 独立模块，供 workflow-runner / run-layers / workspace-persist 共用，避免循环依赖。
 */

/** 历史 run 的 layer_id 直接落 workflow_id（omega_sf_fenkuai_* 等）→ 目录合并组成员 */
const INVERSION_RUN_CATALOG_MAP: Array<{ pattern: RegExp; catalogId: string }> = [
  { pattern: /omega[-_]sf[-_]fenkuai[-_]?fy/i, catalogId: 'method-fy-omega-doy-dynamic' },
  { pattern: /omega[-_]sf[-_]fenkuai[-_]?smap/i, catalogId: 'method-smap-omega-doy-dynamic' },
  { pattern: /omega[-_]avg[-_]daily[-_]?fy/i, catalogId: 'method-fy-omega-doy-avg' },
  { pattern: /omega[-_]avg[-_]daily[-_]?smap/i, catalogId: 'method-smap-omega-doy-avg' },
  // 无 fy/smap 记号的变体（omega_sf_fenkuai_online / dual 等）→ 默认 SMAP 动态组
  { pattern: /omega[-_]sf[-_]fenkuai/i, catalogId: 'method-smap-omega-doy-dynamic' },
  { pattern: /omega[-_]avg[-_]daily/i, catalogId: 'method-smap-omega-doy-avg' },
]

/** 匹配反演 run（fenkuai 动态链 / avg 逐日链 / omega_pixel）的 layer_id 识别。 */
export const INVERSION_RUN_LAYER_PATTERN =
  /omega[-_]sf[-_]fenkuai|omega[-_]avg[-_]daily|omega_sf_omega_pixel/i

/**
 * 英文反演技术 id 不得作为图层库 catalogId / 显示名泄漏。
 */
export function isEnglishInversionCatalogId(id: string | null | undefined): boolean {
  const raw = String(id || '').trim()
  if (!raw) return false
  // 目录 method-* 成员是合法展示入口，即使名称含 omega
  if (raw.startsWith('method-')) return false
  // wf-run / wf-out 占位 id 不是技术 workflow id
  if (/^wf-(?:run|out)-/i.test(raw)) return false
  if (/^imported-/i.test(raw) && INVERSION_RUN_LAYER_PATTERN.test(raw)) return true
  return INVERSION_RUN_LAYER_PATTERN.test(raw)
}

/** 英文反演 workflow/layer/overlay id → 目录 id；非反演 id 原样返回。 */
export function resolveInversionCatalogId(layerId: string): string {
  const raw = String(layerId || '').trim()
  if (!raw) return layerId
  // imported-omega_sf_fenkuai_* → 剥前缀与产物序号再映射
  const stripped = raw.replace(/^imported-/i, '').replace(/-\d{2}$/i, '')
  const probe = INVERSION_RUN_LAYER_PATTERN.test(stripped) ? stripped : raw
  for (const entry of INVERSION_RUN_CATALOG_MAP) {
    if (entry.pattern.test(probe)) return entry.catalogId
  }
  return layerId
}

/**
 * 计算组标题消毒：英文反演技术 id / 空串不得进 TOC 组名。
 * 供 ensureRestoredRunGroup / createRunLayerGroup 共用。
 */
export function sanitizeRunGroupTitle(
  title: string | null | undefined,
  fallback = '反演产物',
): string {
  const raw = String(title || '').trim()
  if (!raw || isEnglishInversionCatalogId(raw)) return fallback
  return raw
}
