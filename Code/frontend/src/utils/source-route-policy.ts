/**
 * source-route-policy — 本地优先 / 在线回退（与 data_input_policies.source_route_local_first 对齐）。
 *
 * 仅对声明 workflow_variants.local + .online 的图层生效；画布显式 workflow 不改写。
 */
import type { DataInputPolicyItem, DataInputPolicyMode } from '../services/data-input-policies-api'
import {
  INPUT_KEY_SOURCE_ROUTE_LOCAL_FIRST,
  resolvePolicyMode,
} from '../services/data-input-policies-api'
import type { LayerDataCoverageResponse } from '../services/layer-coverage-api'
import { isDateCoveredByAnyChannel } from '../services/layer-coverage-api'
import { timeListCoversTimeKey } from './time-key-coverage'

export type SourceRouteVariant = 'online' | 'local'

export type SourceRouteDecision =
  | { action: 'use'; variant: SourceRouteVariant; reason: string }
  | { action: 'confirm_online'; reason: string }
  | { action: 'skip'; reason: string }

export type WorkflowVariantsLike = Record<
  string,
  { workflow_id?: string | null; label?: string | null } | undefined
> | null

/** 兼容历史/笔误 mode 别名 → 规范三值 */
export function normalizePolicyMode(raw: string | null | undefined): DataInputPolicyMode {
  const m = String(raw || '').trim()
  if (m === 'allow_silent' || m === 'silent') return 'allow_silent'
  if (m === 'allow_with_confirm' || m === 'confirm') return 'allow_with_confirm'
  if (m === 'deny') return 'deny'
  return 'deny'
}

/** 门闩：需同时具备 local + online 变体种子 */
export function descriptorEligibleForSourceRoute(
  descriptor:
    | {
        workflow_variants?: WorkflowVariantsLike
      }
    | null
    | undefined,
): boolean {
  const variants = descriptor?.workflow_variants
  if (!variants || typeof variants !== 'object') return false
  const localId = variants.local?.workflow_id
  const onlineId = variants.online?.workflow_id
  return Boolean(
    typeof localId === 'string' &&
    localId.trim() &&
    typeof onlineId === 'string' &&
    onlineId.trim(),
  )
}

/** 由 descriptor.workflow_id 与 variants 推断默认变体（ω 常默认 online） */
export function inferDefaultVariant(
  descriptor:
    | {
        workflow_id?: string | null
        workflow_variants?: WorkflowVariantsLike
      }
    | null
    | undefined,
): SourceRouteVariant | null {
  const variants = descriptor?.workflow_variants
  if (!variants) return null
  const wid = String(descriptor?.workflow_id || '').trim()
  const onlineId = String(variants.online?.workflow_id || '').trim()
  const localId = String(variants.local?.workflow_id || '').trim()
  if (wid && onlineId && wid === onlineId) return 'online'
  if (wid && localId && wid === localId) return 'local'
  if (onlineId) return 'online'
  if (localId) return 'local'
  return null
}

export function resolveSourceRoutePolicyMode(
  policies: DataInputPolicyItem[],
  opts: { layerId?: string | null; workflowId?: string | null; module?: string | null },
): DataInputPolicyMode {
  return normalizePolicyMode(resolvePolicyMode(policies, INPUT_KEY_SOURCE_ROUTE_LOCAL_FIRST, opts))
}

function localDatesCoverTimeKey(
  coverage: LayerDataCoverageResponse | null | undefined,
  timeKey: string | null | undefined,
): boolean {
  if (!timeKey || !coverage) return false
  const dates = coverage.channels?.local?.dates ?? []
  if (!dates.length) return false
  return timeListCoversTimeKey(dates, timeKey)
}

function onlineWindowCoversTimeKey(
  coverage: LayerDataCoverageResponse | null | undefined,
  timeKey: string | null | undefined,
): boolean {
  if (!coverage?.channels?.online?.available) return false
  if (!timeKey) return true
  return isDateCoveredByAnyChannel(timeKey, coverage, { allowOnlinePrefetchOnly: true })
}

function tryRouteOnline(
  mode: DataInputPolicyMode,
  coverage: LayerDataCoverageResponse | null | undefined,
  timeKey: string | null | undefined,
  onlineBlocked: boolean | undefined,
  reasonStem: string,
): SourceRouteDecision {
  if (onlineBlocked) {
    return { action: 'skip', reason: 'online_blocked' }
  }
  if (!onlineWindowCoversTimeKey(coverage, timeKey)) {
    return { action: 'skip', reason: 'online_window_miss' }
  }
  if (mode === 'allow_with_confirm') {
    return { action: 'confirm_online', reason: `${reasonStem}_confirm` }
  }
  return { action: 'use', variant: 'online', reason: `${reasonStem}_silent` }
}

/**
 * 根据策略 + coverage 决定变体。
 *
 * - coverage 拉取失败 → skip（勿误乐观 local）
 * - deny → skip
 * - 本地 dates 命中 → local
 * - 本地 dates 有但不命中 → online（silent/confirm）
 * - 本地 dates 空：
 *   - defaultVariant=online → 尊重描述符默认（ω），走 online 窗或 skip
 *   - defaultVariant=local/未知 → 乐观 local（试跑；gap 由失败链二次路由）
 */
export function decideSourceRoute(opts: {
  mode: DataInputPolicyMode
  eligible: boolean
  coverage: LayerDataCoverageResponse | null | undefined
  timeKey?: string | null
  /** 在线凭据等阻断时勿自动 online */
  onlineBlocked?: boolean
  hasExplicitCanvasWorkflow?: boolean
  /** descriptor 默认变体；空 dates 时避免把默认 online 的 ω 强改 local */
  defaultVariant?: SourceRouteVariant | null
}): SourceRouteDecision {
  if (opts.hasExplicitCanvasWorkflow) {
    return { action: 'skip', reason: 'canvas_workflow' }
  }
  if (!opts.eligible) {
    return { action: 'skip', reason: 'not_eligible' }
  }
  const mode = normalizePolicyMode(opts.mode)
  if (mode === 'deny') {
    return { action: 'skip', reason: 'policy_deny' }
  }
  // coverage 不可用：不要乐观 local（否则 API 失败也会盲跑本地）
  if (opts.coverage == null) {
    return { action: 'skip', reason: 'coverage_unavailable' }
  }

  const dates = opts.coverage.channels?.local?.dates ?? []
  if (dates.length > 0) {
    if (localDatesCoverTimeKey(opts.coverage, opts.timeKey)) {
      return { action: 'use', variant: 'local', reason: 'local_dates_hit' }
    }
    return tryRouteOnline(mode, opts.coverage, opts.timeKey, opts.onlineBlocked, 'local_miss')
  }

  // time_list 空
  if (opts.defaultVariant === 'online') {
    // ω 等默认在线：空 dates 不强制 local；能走 online 窗则走，否则 skip 回落描述符默认
    const onlineTry = tryRouteOnline(
      mode,
      opts.coverage,
      opts.timeKey,
      opts.onlineBlocked,
      'default_online',
    )
    if (onlineTry.action !== 'skip') return onlineTry
    return { action: 'skip', reason: 'default_online_skip' }
  }

  // 默认 local / 未知：乐观 local（目录可能有数但未登记）；gap 后由失败链处理
  return { action: 'use', variant: 'local', reason: 'local_optimistic' }
}

/** coverage_gap 后：是否应按策略静默切在线 */
export function shouldSilentSwitchOnlineOnCoverageGap(mode: DataInputPolicyMode): boolean {
  return normalizePolicyMode(mode) === 'allow_silent'
}

/** coverage_gap 后：是否应用 Banner 确认切在线 */
export function shouldConfirmSwitchOnlineOnCoverageGap(mode: DataInputPolicyMode): boolean {
  return normalizePolicyMode(mode) === 'allow_with_confirm'
}
