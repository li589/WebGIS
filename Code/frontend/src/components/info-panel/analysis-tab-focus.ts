/** 分析面板 Tab id 与 focus 目标映射 */

export type AnalysisTabId = 'visual' | 'tools' | 'style' | 'meta'

/** DOM id → 所属 Tab（越靠前优先级越高） */
const FOCUS_ID_TAB: Record<string, AnalysisTabId> = {
  'point-weather': 'visual',
  'hotspot-section': 'visual',
  'result-section': 'visual',
  'overlay-compare': 'visual',
  'analysis-tools': 'tools',
  'layer-style': 'style',
  'global-overview': 'meta',
  'imported-layer': 'meta',
  'scheduler-status': 'meta',
  'report-section': 'meta',
  // 兼容旧 id
  'overview-section': 'meta',
}

/**
 * 根据 focus 请求的 DOM id 列表解析应切换的 Tab。
 * 优先匹配列表中第一个可识别 id。
 */
export function resolveAnalysisTabForFocusIds(ids: readonly string[]): AnalysisTabId | null {
  for (const id of ids) {
    if (!id) continue
    if (FOCUS_ID_TAB[id]) return FOCUS_ID_TAB[id]
    if (id.startsWith('layer-') && id !== 'layer-style') return 'meta'
    if (id.startsWith('hotspot-')) return 'visual'
  }
  return null
}

/** 归一化外部传入的 focus id（旧别名 → 现行 id） */
export function normalizeAnalysisFocusIds(ids: readonly string[]): string[] {
  return ids.map((id) => (id === 'overview-section' ? 'global-overview' : id))
}
