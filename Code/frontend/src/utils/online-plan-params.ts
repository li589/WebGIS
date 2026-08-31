/**
 * online-plan-params — L1 计划草稿与流水线在线表单同源参数投影（P1）。
 *
 * 约定：PlanTabDraft.paramOverrides 与工作流节点 panel 共用键名
 *（如 orbit_mode），确认在线重跑时注入 algorithm_params。
 */
import { fetchWorkflowDefinition } from '../services/workflow-definition-api'

/** 计划会话与在线表单共用的可编辑键（白名单，避免把整图 params 灌进 UI） */
export const ONLINE_PLAN_PARAM_KEYS = ['orbit_mode'] as const

export type OnlinePlanParamKey = (typeof ONLINE_PLAN_PARAM_KEYS)[number]

export const ONLINE_PLAN_PARAM_DEFAULTS: Record<OnlinePlanParamKey, string> = {
  orbit_mode: 'MWRID',
}

export type OnlineVariantLike = {
  workflow_id?: string
  label?: string | null
}

export function resolveOnlineWorkflowId(
  descriptor: { workflow_variants?: Record<string, OnlineVariantLike> | null } | null | undefined,
): string | null {
  const online = descriptor?.workflow_variants?.online
  const id = online?.workflow_id
  return typeof id === 'string' && id.trim() ? id.trim() : null
}

/**
 * P2：图层是否可进在线计划会话 — 仅看 descriptor.workflow_variants.online，
 * 无前端 catalog 白名单。
 */
export function descriptorHasOnlineWorkflowVariant(
  descriptor: { workflow_variants?: Record<string, unknown> | null } | null | undefined,
): boolean {
  const variants = descriptor?.workflow_variants
  return Boolean(variants && typeof variants === 'object' && variants.online)
}

/** 从节点 params / default_params 投影白名单键（缺省填默认，供表单编辑合并） */
export function projectOnlinePlanParams(
  source: Record<string, unknown> | null | undefined,
): Record<string, unknown> {
  const out: Record<string, unknown> = {}
  if (!source || typeof source !== 'object') {
    for (const key of ONLINE_PLAN_PARAM_KEYS) {
      out[key] = ONLINE_PLAN_PARAM_DEFAULTS[key]
    }
    return out
  }
  for (const key of ONLINE_PLAN_PARAM_KEYS) {
    const v = source[key]
    out[key] = v !== undefined && v !== null && String(v).trim() !== ''
      ? v
      : ONLINE_PLAN_PARAM_DEFAULTS[key]
  }
  return out
}

/** 仅提取源中已有的白名单键（不填默认）— 新 online 层无该键则不出现在草稿 */
export function extractPresentOnlinePlanParams(
  source: Record<string, unknown> | null | undefined,
): Record<string, unknown> {
  const out: Record<string, unknown> = {}
  if (!source || typeof source !== 'object') return out
  for (const key of ONLINE_PLAN_PARAM_KEYS) {
    if (!(key in source)) continue
    const v = source[key]
    if (v === undefined || v === null) continue
    if (typeof v === 'string' && v.trim() === '') continue
    out[key] = v
  }
  return out
}

/**
 * 拉取 online 变体工作流定义，从首个含白名单键的节点 params 投影。
 * 失败或无键时返回 {}（P2：不因默认 orbit_mode 伪造 FY 专用 UI）。
 */
export async function loadOnlinePlanParamDefaults(
  descriptor: { workflow_variants?: Record<string, OnlineVariantLike> | null } | null | undefined,
): Promise<Record<string, unknown>> {
  const workflowId = resolveOnlineWorkflowId(descriptor)
  if (!workflowId) return {}

  try {
    const def = await fetchWorkflowDefinition(workflowId)
    const nodes = Array.isArray(def?.nodes) ? def.nodes : []
    for (const node of nodes) {
      const props =
        (node as { properties?: Record<string, unknown>; params?: Record<string, unknown> })
          ?.properties ||
        (node as { params?: Record<string, unknown> })?.params ||
        null
      if (!props || typeof props !== 'object') continue
      const nested =
        props.algorithm_params && typeof props.algorithm_params === 'object'
          ? (props.algorithm_params as Record<string, unknown>)
          : null
      const bag = nested || props
      const extracted = extractPresentOnlinePlanParams(bag)
      if (Object.keys(extracted).length > 0) return extracted
    }
  } catch {
    /* ignore */
  }
  return {}
}

/** 合并：表单/流水线侧变更写回计划草稿 */
export function mergePlanParamOverrides(
  current: Record<string, unknown> | null | undefined,
  patch: Record<string, unknown>,
): Record<string, unknown> {
  const base = projectOnlinePlanParams(current)
  for (const key of ONLINE_PLAN_PARAM_KEYS) {
    if (key in patch) base[key] = patch[key]
  }
  return base
}

/** 确认重跑时注入 algorithm_params（仅白名单） */
export function toAlgorithmParamsFromPlan(
  overrides: Record<string, unknown> | null | undefined,
): Record<string, unknown> | undefined {
  if (!overrides) return undefined
  const out: Record<string, unknown> = {}
  for (const key of ONLINE_PLAN_PARAM_KEYS) {
    if (key in overrides && overrides[key] !== undefined) {
      out[key] = overrides[key]
    }
  }
  return Object.keys(out).length ? out : undefined
}
