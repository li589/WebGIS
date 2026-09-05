/**
 * 工作流运行展示名：状态指示器 / 图层计算组标题优先用种子中文名
 * （如「SMAP 动态散射约束产品反演（本地）」），禁止 wf-run-* / 英文 workflow id 泄漏。
 */
import { getActivePinia } from 'pinia'
import { isEnglishInversionCatalogId } from '@/stores/layers/inversion-catalog'
import { useWorkflowDefinitionsStore } from '@/stores/workflow-definitions'

export type WorkflowSummaryLike = { workflow_id: string; name?: string | null }

/**
 * 判断是否为动作命令/重跑指令标签（如「按时间轴重跑 2026-07」、「按时段重跑 20250701_20250708」、
 * 「切换在线并重跑 2026-09」）。动作指令只应作为芯片/副标题显示，严禁作为实体卡片或图层组的主标题。
 */
export function isActionCommandLabel(label: string | null | undefined): boolean {
  const raw = String(label || '').trim()
  if (!raw) return false
  if (/^(?:按时段|按时间轴|切换在线并|计划会话在线)?重跑(?:\s|$)/u.test(raw)) return true
  if (/^重跑(?:\s|$)/u.test(raw)) return true
  if (/^运行分析(?:\s*[·•]|\s|$)/u.test(raw)) return true
  if (/^运行\s+.*\s+分析(?:\s*[·•]|\s|$)/u.test(raw)) return true
  if (/^运行画布工作流(?:\s|$)/u.test(raw)) return true
  return false
}

/** Pinia 未就绪时返回空，不阻断提交/恢复路径。 */
export function tryWorkflowSummaries(): WorkflowSummaryLike[] {
  try {
    const pinia = getActivePinia()
    if (pinia && '_a' in pinia && (pinia as { _a?: unknown })._a) {
      return useWorkflowDefinitionsStore(pinia).summaries ?? []
    }
    return []
  } catch {
    return []
  }
}

/** 是否为技术占位 id 或动作指令（不得作为组名/状态主标题） */
export function isTechnicalRunTitle(title: string | null | undefined): boolean {
  const raw = String(title || '').trim()
  if (!raw) return true
  if (/^wf-(?:run|out)-/i.test(raw)) return true
  if (/^run-group-/i.test(raw)) return true
  if (/^local-submit-/i.test(raw)) return true
  if (isEnglishInversionCatalogId(raw)) return true
  if (isActionCommandLabel(raw)) return true
  return false
}

/** 去掉运行中组标题后缀，便于状态指示器显示纯工作流名。 */
export function stripComputingGroupSuffix(title: string): string {
  return title.replace(/\s*·\s*计算中\s*$/u, '').trim()
}

export function lookupWorkflowSummaryName(
  workflowId: string,
  summaries: WorkflowSummaryLike[] | undefined,
): string | undefined {
  const id = workflowId.trim()
  if (!id || !summaries?.length) return undefined
  const hit = summaries.find((s) => s.workflow_id === id)
  const name = hit?.name?.trim()
  return name && !isTechnicalRunTitle(name) ? name : undefined
}

/** 从提交载荷或 command_label 提取 workflow_entry / workflow_id */
export function extractWorkflowEntryId(
  algorithmRequest?: Record<string, unknown> | null,
  commandLabel?: string | null,
): string | undefined {
  const ar = algorithmRequest
  if (ar && typeof ar === 'object') {
    const direct = ar.workflow_entry_name ?? ar.workflow_name
    if (typeof direct === 'string' && direct.trim()) return direct.trim()
    const wd = ar.workflow_definition
    if (wd && typeof wd === 'object' && !Array.isArray(wd)) {
      const wid = (wd as { workflow_id?: unknown }).workflow_id
      if (typeof wid === 'string' && wid.trim()) return wid.trim()
    }
  }
  const label = String(commandLabel || '').trim()
  const canvas = label.match(/^运行画布工作流\s+(\S+)/)
  if (canvas?.[1]) return canvas[1]
  return undefined
}

/** 从 algorithm_request.workflow_definition.name 读种子/画布中文名 */
export function extractWorkflowDefinitionName(
  algorithmRequest?: Record<string, unknown> | null,
): string | undefined {
  const wd = algorithmRequest?.workflow_definition
  if (!wd || typeof wd !== 'object' || Array.isArray(wd)) return undefined
  const name = (wd as { name?: unknown }).name
  if (typeof name !== 'string') return undefined
  const trimmed = name.trim()
  return trimmed && !isTechnicalRunTitle(trimmed) ? trimmed : undefined
}

/**
 * 解析工作流运行的人类可读名称。
 * 优先级：种子 summary 名 → 定义内 name → 已消毒 command_label →
 * workflow id → fallback（catalog 名仅作最后兜底，且须非技术 id）。
 */
export function resolveWorkflowRunDisplayName(options: {
  workflowId?: string | null
  commandLabel?: string | null
  catalogName?: string | null
  definitionName?: string | null
  summaries?: WorkflowSummaryLike[]
  fallback?: string
}): string {
  const summaries = options.summaries ?? tryWorkflowSummaries()
  const workflowId = String(options.workflowId || '').trim()
  const fromSummary =
    workflowId && summaries.length ? lookupWorkflowSummaryName(workflowId, summaries) : undefined
  if (fromSummary) return fromSummary

  const fromDef = String(options.definitionName || '').trim()
  if (fromDef && !isTechnicalRunTitle(fromDef)) return fromDef

  const label = String(options.commandLabel || '').trim()
  if (label && !label.startsWith('运行画布工作流')) {
    // 「运行 SMAP 平均散射约束产品反演 分析 · 在线获取」→ 取工作流语义段
    const stripped = label
      .replace(/^运行\s+/, '')
      .replace(/\s+分析(?:\s*[·•].*)?$/u, '')
      .trim()
    if (stripped && !isTechnicalRunTitle(stripped) && !isActionCommandLabel(stripped)) {
      return stripped
    }
    if (!isTechnicalRunTitle(label) && !isActionCommandLabel(label)) {
      return label
    }
  }

  const catalog = String(options.catalogName || '').trim()

  // 1. 若 workflowId 本身是非技术的中文/人类可读名称（如「自定义演示工作流」），优先保留
  if (workflowId && !isTechnicalRunTitle(workflowId) && !/^[a-z0-9_\-.:]+$/i.test(workflowId)) {
    return workflowId
  }

  // 2. 若 catalog 是非技术人类可读业务名（含中文），优先于未翻译的裸英文 workflow/layer id（如 vegetation-ndvi）
  if (catalog && !isTechnicalRunTitle(catalog) && !/^[a-z0-9_\-.:]+$/i.test(catalog)) {
    return catalog
  }

  // 3. 兜底英文 workflowId 与 catalog
  if (workflowId && !isTechnicalRunTitle(workflowId)) return workflowId

  if (catalog && !isTechnicalRunTitle(catalog)) return catalog

  const fb = String(options.fallback || '').trim()
  if (fb && !isTechnicalRunTitle(fb)) return fb
  return '工作流运行'
}

/** 图层计算组标题：extra/提交名 > job 名 > 种子 workflow 名 > workflowId > fallback */
export function resolveRunGroupTitle(options: {
  workflowId?: string | null
  jobName?: string | null
  configuredTitle?: string | null
  commandLabel?: string | null
  definitionName?: string | null
  summaries?: WorkflowSummaryLike[]
  fallback?: string
}): string {
  const configured = String(options.configuredTitle || '').trim()
  if (configured && !isTechnicalRunTitle(configured)) {
    return stripComputingGroupSuffix(configured)
  }
  const job = String(options.jobName || '').trim()
  if (job && !isTechnicalRunTitle(job)) {
    return stripComputingGroupSuffix(job)
  }
  return resolveWorkflowRunDisplayName({
    workflowId: options.workflowId,
    commandLabel: options.commandLabel,
    definitionName: options.definitionName,
    summaries: options.summaries,
    fallback: options.fallback ?? '工作流产物',
  })
}

/** 状态指示器 / jobLayer 展示名（轮询时保留已有非技术名）。 */
export function resolveJobLayerDisplayName(
  run: {
    command_label?: string | null
    layer_id?: string | null
    result_dto?: unknown
  },
  catalogName: string,
  options?: {
    previousName?: string | null
    entryName?: string | null
    algorithmRequest?: Record<string, unknown> | null
  },
): string {
  const prev = String(options?.previousName || '').trim()
  if (prev && !isTechnicalRunTitle(prev)) return prev

  const entry = String(options?.entryName || '').trim()
  const workflowId =
    extractWorkflowEntryId(options?.algorithmRequest, run.command_label) ||
    (entry && !isTechnicalRunTitle(entry) ? entry : undefined) ||
    (typeof run.layer_id === 'string' && run.layer_id.trim() ? run.layer_id.trim() : undefined)

  return resolveWorkflowRunDisplayName({
    workflowId,
    commandLabel: run.command_label,
    catalogName,
    definitionName: extractWorkflowDefinitionName(options?.algorithmRequest),
    fallback: '工作流运行',
  })
}
