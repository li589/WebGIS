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

/** 显式声明的产出标签（extra.outputs → 节点 main_layers）；未声明返回 []，由调用方自行回退 */
export function explicitExpectedOutputTags(def: WorkflowDefLike | null | undefined): string[] {
  if (!def) return []
  const fromExtra = asStringArray(def.extra?.outputs)
  if (fromExtra.length) return fromExtra

  for (const node of def.nodes ?? []) {
    const layers = mainLayersFromNode(node)
    if (layers.length) return layers
  }

  return []
}

/** 工作流定义的中文组名（extra.group_title）；未配置返回 undefined */
export function groupTitleFromDefinition(
  def: WorkflowDefLike | null | undefined,
): string | undefined {
  const raw = def?.extra?.group_title
  if (typeof raw === 'string' && raw.trim()) return raw.trim()
  return undefined
}

/**
 * 工作流定义的产出显示名映射（extra.output_labels）。
 *
 * 形态一（推荐，按 tag 键）：``{ "SM": "土壤水分", "VOD": "植被光学厚度" }``
 * 形态二（数组，与 extra.outputs 对齐）：``["土壤水分", "植被光学厚度"]``
 * 未配置返回空对象——由 productTagLabel 固定映射兜底。
 */
export function outputLabelsFromDefinition(
  def: WorkflowDefLike | null | undefined,
): Record<string, string> {
  const raw = def?.extra?.output_labels
  if (Array.isArray(raw)) {
    const tags = explicitExpectedOutputTags(def)
    const map: Record<string, string> = {}
    raw.forEach((label, i) => {
      if (typeof label === 'string' && label.trim() && tags[i]) {
        map[tags[i]] = label.trim()
      }
    })
    return map
  }
  if (raw && typeof raw === 'object') {
    const map: Record<string, string> = {}
    for (const [k, v] of Object.entries(raw as Record<string, unknown>)) {
      if (typeof v === 'string' && v.trim()) map[k] = v.trim()
    }
    return map
  }
  return {}
}

/** 产出标签 + 显示名（extra.output_labels 优先，productTagLabel 兜底） */
export function expectedOutputTargets(
  def: WorkflowDefLike | null | undefined,
): Array<{ name: string; productTag: string }> {
  const tags = explicitExpectedOutputTags(def)
  const labels = outputLabelsFromDefinition(def)
  return tags.map((tag) => ({
    productTag: tag,
    name: labels[tag] ?? productTagLabel(tag),
  }))
}

/**
 * 预期产出标签列表；至少返回 ['result']（单产出也进计算组）。
 */
export function resolveExpectedOutputTags(def: WorkflowDefLike | null | undefined): string[] {
  return explicitExpectedOutputTags(def).length > 0 ? explicitExpectedOutputTags(def) : ['result']
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
 * 产品标签 → TOC 短显示名（单一事实来源）。
 * 内部 productTag 仍用 SM/VOD/OMEGA 原文；全称见 PRODUCT_TAG_DESCRIPTIONS。
 * 见 Docs/03-规范协议/layer-naming.md
 */
export const PRODUCT_TAG_LABELS: Record<string, string> = {
  SM: 'SM',
  VOD: 'VOD',
  OMEGA: 'ω',
  result: '产出变量',
}

/** 变量层全称（InfoPanel / tooltip；不进 TOC） */
export const PRODUCT_TAG_DESCRIPTIONS: Record<string, string> = {
  SM: '土壤水分',
  VOD: '植被光学厚度',
  OMEGA: '反演参数 ω',
  result: '工作流产出变量',
}

export function productTagLabel(tag: string): string {
  return PRODUCT_TAG_LABELS[tag] ?? tag
}

export function productTagDescription(tag: string): string {
  const key = tag.trim()
  return PRODUCT_TAG_DESCRIPTIONS[key] ?? PRODUCT_TAG_DESCRIPTIONS[key.toUpperCase()] ?? tag
}
