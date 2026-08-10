/**
 * 从工作流定义推断预期地图产出标签（运行对话框 / 计算图层组共用）。
 * 优先级：extra.outputs → 节点 main_layers → 默认 ['result']
 */

export type WorkflowDefLike = {
  workflow_id?: string
  extra?: Record<string, unknown> | null
  nodes?: Array<{
    type?: string
    properties?: Record<string, unknown>
  }>
}

function asStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) return []
  return value.filter((t): t is string => typeof t === 'string' && t.trim().length > 0)
}

/** 从节点 properties / algorithm_params 读取 main_layers */
function mainLayersFromNode(node: { properties?: Record<string, unknown> }): string[] {
  const props = node.properties ?? {}
  const direct = asStringArray(props.main_layers)
  if (direct.length) return direct
  const algo = props.algorithm_params
  if (algo && typeof algo === 'object' && !Array.isArray(algo)) {
    const nested = asStringArray((algo as Record<string, unknown>).main_layers)
    if (nested.length) return nested
  }
  return []
}

/** 模块名作命名前缀（module/foo → foo） */
export function namePrefixFromDefinition(
  def: WorkflowDefLike | null | undefined,
  fallback = 'output',
): string {
  if (!def?.nodes?.length) return def?.workflow_id || fallback
  for (const node of def.nodes) {
    const t = node.type || ''
    if (t.startsWith('module/')) {
      const parts = t.split('/')
      return parts[parts.length - 1] || fallback
    }
  }
  return def.workflow_id || fallback
}

/** @deprecated 使用 namePrefixFromDefinition；保留别名兼容运行对话框 */
export const resolveOutputNamePrefix = namePrefixFromDefinition

/**
 * 预期产出标签列表；至少返回 ['result']（单产出也进计算组）。
 */
export function resolveExpectedOutputTags(def: WorkflowDefLike | null | undefined): string[] {
  if (!def) return ['result']
  const fromExtra = asStringArray(def.extra?.outputs)
  if (fromExtra.length) return fromExtra

  for (const node of def.nodes ?? []) {
    const layers = mainLayersFromNode(node)
    if (layers.length) return layers
  }

  return ['result']
}

export function defaultProductLayerNames(
  tags: string[],
  _prefix?: string,
): Array<{ name: string; productTag: string }> {
  return tags.map((tag) => ({
    productTag: tag,
    name: productTagLabel(tag),
  }))
}

/**
 * 产品标签 → 面向用户的显示名（单一事实来源）。
 * 内部 productTag 仍用 SM/VOD/OMEGA 原文（算法/文件名标识），
 * 仅展示层经此映射为「缩写 + 中文说明」。
 */
export const PRODUCT_TAG_LABELS: Record<string, string> = {
  SM: 'SM（土壤湿度）',
  VOD: 'VOD（植被光学厚度）',
  OMEGA: 'ω（反演参数）',
  result: '计算结果',
}

export function productTagLabel(tag: string): string {
  return PRODUCT_TAG_LABELS[tag] ?? tag
}
