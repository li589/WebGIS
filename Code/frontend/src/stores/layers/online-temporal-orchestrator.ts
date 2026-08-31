/**
 * Online Temporal Orchestrator — 在线时间获取编排器
 *
 * 核心职责：
 * 1. 监听时间轴位置变化，当用户选中 'fetchable' 段时自动提交工作流获取数据
 * 2. 避免对同一时间点重复提交（in-flight 去重 + cooling 记录）
 * 3. 与现有 workflow-run 域协作：提交后由 poller 自动轮询终态 + 物化产物
 * 4. 提供 prefetchAdjacent 预获取相邻时间点（Phase 5 扩展）
 *
 * 设计约束：
 * - 不直接调用 submitWorkflow，而是委托 runWorkflowForCatalog，复用 payload 构建 / 乐观占位 / 轮询启动
 * - 编排器是无状态 computed + 有状态 ref 的混合体，通过 composable 暴露
 * - 获取失败后进入 cooling（60s），期间不重复提交同一时间点
 */
import { computed, ref, type ComputedRef, type Ref } from 'vue'
import type { LayerOnlineSyncResponse, OnlineTemporalCapability } from '../../services/runtime-api'
import type { TimeGranularity } from '../../utils/layer-timeline'
import { parseTimeStep, type TimeStep } from '../../utils/temporal-interval'

// ── 类型 ──────────────────────────────────────────────────────────────────

/** 单个在线获取请求的跟踪状态 */
export interface OnlineFetchEntry {
  /** `${catalogId}:${timeKey}` */
  key: string
  catalogId: string
  timeKey: string
  /** 工作流 run_id（提交后获得） */
  runId?: string
  status: 'submitting' | 'in-flight' | 'succeeded' | 'failed' | 'cooling'
  /** 提交时间戳 */
  submittedAt: number
  /** 终态时间戳 */
  settledAt?: number
  /** 失败原因 */
  error?: string
}

/** 编排器依赖的外部接口（由调用方注入） */
export interface OnlineTemporalOrchestratorDeps {
  /** 获取图层的在线时间配置 */
  getOnlineTemporalConfig: (catalogId: string) => OnlineTemporalCapability | null
  /** 提交工作流（委托 workflow-run 域；P2 起作为回退路径） */
  runWorkflowForCatalog: (
    catalogId: string,
    options: {
      timeRange?: Record<string, unknown>
      algorithmRequest?: Record<string, unknown>
      resourceProfile?: 'realtime' | 'standard' | 'heavy' | 'batch'
      commandLabel?: string
    },
  ) => Promise<string | undefined>
  /**
   * P2：统一在线同步入口（POST /layer-assets/{id}/sync）。
   * 后端承担同图层活跃 run 去重、time_key 解析、prefetch/low 批量队列与
   * 失败保留旧资产语义。缺省时编排器回退 runWorkflowForCatalog 旧路径。
   */
  syncLayerAssetOnline?: (
    catalogId: string,
    body: { time_key?: string; is_prefetch?: boolean; priority?: 'low' | 'normal' },
  ) => Promise<LayerOnlineSyncResponse>
  /**
   * P2：把后端返回的 online_sync run 注册进前端轮询链
   * （复用 workflow-runner 的 registerExternalWorkflowRun：拉取状态 +
   * upsertJobLayer + startPolling，终态后由既有 watcher 物化产物）。
   */
  registerExternalWorkflowRun?: (runId: string, catalogIdHint?: string) => Promise<void>
  /** 当前选中的 catalogId */
  selectedCatalogId: ComputedRef<string | null> | Ref<string | null>
  /** 当前时间轴日期 */
  currentDate: Ref<Date>
  /** 当前时间轴小时 */
  currentHour: Ref<number>
  /** 当前时间轴粒度 */
  activeLayerGranularity: ComputedRef<TimeGranularity> | Ref<TimeGranularity>
  /** 日志 */
  logOperation?: (tag: string, message: string) => void
}

// ── 时间键辅助 ────────────────────────────────────────────────────────────

/**
 * 根据时间轴位置和粒度生成时间键。
 * 时间键是编排器去重的唯一标识。
 */
export function buildTimeKey(date: Date, hour: number, granularity: TimeGranularity): string {
  const y = date.getFullYear()
  const m = String(date.getMonth() + 1).padStart(2, '0')
  if (granularity === 'year') return `${y}`
  if (granularity === 'month') return `${y}-${m}`
  const d = String(date.getDate()).padStart(2, '0')
  if (granularity === 'day') return `${y}-${m}-${d}`
  const h = String(Math.floor(hour)).padStart(2, '0')
  return `${y}-${m}-${d}T${h}:00:00`
}

/**
 * 根据时间键和 native_step 构建工作流 time_range。
 * 返回 { start_at, end_at, granularity } 供 WorkflowSubmitRequest.time_range 使用。
 */
export function buildTimeRangeFromKey(
  timeKey: string,
  nativeStep: string,
  granularity: TimeGranularity,
): { start_at: string; end_at: string; granularity: TimeGranularity } | null {
  const step = parseTimeStep(nativeStep)
  if (!step) return null

  // 解析 timeKey 为开始时间
  let start: Date
  if (/^\d{4}$/.test(timeKey)) {
    start = new Date(parseInt(timeKey), 0, 1)
  } else if (/^\d{4}-\d{2}$/.test(timeKey)) {
    const [y, m] = timeKey.split('-')
    start = new Date(parseInt(y), parseInt(m) - 1, 1)
  } else if (/^\d{4}-\d{2}-\d{2}$/.test(timeKey)) {
    const [y, m, d] = timeKey.split('-')
    start = new Date(parseInt(y), parseInt(m) - 1, parseInt(d))
  } else if (/^\d{4}-\d{2}-\d{2}T\d{2}:00:00$/.test(timeKey)) {
    start = new Date(timeKey)
  } else {
    return null
  }

  if (isNaN(start.getTime())) return null

  // 计算 end_at = start + step
  const end = new Date(start)
  addStep(end, step)

  // granularity 映射到 WorkflowSubmitRequest.TimeRange.granularity
  const gran = granularity === 'static' ? 'hour' : granularity

  return {
    start_at: toIsoLocal(start),
    end_at: toIsoLocal(end),
    granularity: gran,
  }
}

function addStep(date: Date, step: TimeStep): void {
  const value = step.value > 0 ? step.value : 1
  if (step.unit === 'hour') {
    date.setTime(date.getTime() + value * 3600_000)
  } else if (step.unit === 'day') {
    date.setDate(date.getDate() + value)
  } else if (step.unit === 'month') {
    date.setMonth(date.getMonth() + value)
  } else {
    date.setFullYear(date.getFullYear() + value)
  }
}

/** 转为后端可解析的本地 ISO 字符串（不含时区后缀，与现有 time_range 一致） */
function toIsoLocal(date: Date): string {
  const y = date.getFullYear()
  const m = String(date.getMonth() + 1).padStart(2, '0')
  const d = String(date.getDate()).padStart(2, '0')
  const h = String(date.getHours()).padStart(2, '0')
  const min = String(date.getMinutes()).padStart(2, '0')
  const s = String(date.getSeconds()).padStart(2, '0')
  return `${y}-${m}-${d}T${h}:${min}:${s}`
}

// ── 编排器核心 ────────────────────────────────────────────────────────────

const COOLING_DURATION_MS = 60_000 // 失败后冷却 60s
const MAX_CONCURRENT_FETCHES = 2 // 最大并发获取数
const PREFETCH_DELAY_MS = 2000 // 预获取延迟（避免与用户操作抢占）

/**
 * 根据时间键和步长生成相邻时间键。
 * delta > 0 向未来方向，delta < 0 向过去方向。
 */
export function shiftTimeKey(
  timeKey: string,
  nativeStep: string,
  delta: number,
  granularity: 'hour' | 'day' | 'month' | 'year' | 'static',
): string | null {
  const step = parseTimeStep(nativeStep)
  if (!step || delta === 0) return timeKey

  let date: Date
  if (/^\d{4}$/.test(timeKey)) {
    date = new Date(parseInt(timeKey), 0, 1)
  } else if (/^\d{4}-\d{2}$/.test(timeKey)) {
    const [y, m] = timeKey.split('-')
    date = new Date(parseInt(y), parseInt(m) - 1, 1)
  } else if (/^\d{4}-\d{2}-\d{2}$/.test(timeKey)) {
    const [y, m, d] = timeKey.split('-')
    date = new Date(parseInt(y), parseInt(m) - 1, parseInt(d))
  } else if (/^\d{4}-\d{2}-\d{2}T\d{2}:00:00$/.test(timeKey)) {
    date = new Date(timeKey)
  } else {
    return null
  }

  if (isNaN(date.getTime())) return null

  const value = step.value * Math.abs(delta)
  const sign = delta > 0 ? 1 : -1
  if (step.unit === 'hour') {
    date.setTime(date.getTime() + sign * value * 3600_000)
  } else if (step.unit === 'day') {
    date.setDate(date.getDate() + sign * value)
  } else if (step.unit === 'month') {
    date.setMonth(date.getMonth() + sign * value)
  } else {
    date.setFullYear(date.getFullYear() + sign * value)
  }

  return buildTimeKey(date, date.getHours(), granularity)
}

export function useOnlineTemporalOrchestrator(deps: OnlineTemporalOrchestratorDeps) {
  /** 活跃获取请求跟踪表，key = `${catalogId}:${timeKey}` */
  const fetchEntries = ref<Map<string, OnlineFetchEntry>>(new Map())

  /** 当前时间键 */
  const currentTimeKey = computed(() => {
    const catalogId = deps.selectedCatalogId.value
    if (!catalogId) return null
    return buildTimeKey(
      deps.currentDate.value,
      deps.currentHour.value,
      deps.activeLayerGranularity.value,
    )
  })

  /** 当前图层是否支持在线获取 */
  const currentLayerSupportsOnline = computed(() => {
    const catalogId = deps.selectedCatalogId.value
    if (!catalogId) return false
    return deps.getOnlineTemporalConfig(catalogId) !== null
  })

  /** 当前 in-flight 获取数（用于并发控制） */
  const inFlightCount = computed(() => {
    let count = 0
    for (const entry of fetchEntries.value.values()) {
      if (entry.status === 'submitting' || entry.status === 'in-flight') count++
    }
    return count
  })

  /** 当前时间键的获取状态（null = 无活跃获取） */
  const currentFetchStatus = computed<OnlineFetchEntry | null>(() => {
    const catalogId = deps.selectedCatalogId.value
    const timeKey = currentTimeKey.value
    if (!catalogId || !timeKey) return null
    const key = `${catalogId}:${timeKey}`
    return fetchEntries.value.get(key) ?? null
  })

  /**
   * 手动触发在线获取（用户点击 fetchable 段时调用）。
   * 也可由 watcher 自动调用。
   */
  async function triggerOnlineFetch(
    catalogId: string,
    timeKey: string,
    options?: { isPrefetch?: boolean },
  ): Promise<string | undefined> {
    const cap = deps.getOnlineTemporalConfig(catalogId)
    if (!cap) return undefined

    const key = `${catalogId}:${timeKey}`
    const existing = fetchEntries.value.get(key)

    // 已在提交中 / 已在飞行中 → 跳过
    if (existing && (existing.status === 'submitting' || existing.status === 'in-flight')) {
      return existing.runId
    }

    // 冷却期 → 跳过
    if (existing && existing.status === 'cooling') {
      const elapsed = Date.now() - (existing.settledAt ?? 0)
      if (elapsed < COOLING_DURATION_MS) return undefined
      // 冷却到期，清除记录
      fetchEntries.value.delete(key)
    }

    // 已成功 → 跳过（数据已就绪）
    if (existing && existing.status === 'succeeded') {
      return existing.runId
    }

    // 并发限制：非预获取请求优先；预获取在达到上限时跳过
    if (options?.isPrefetch && inFlightCount.value >= MAX_CONCURRENT_FETCHES) {
      return undefined
    }

    // 构建 time_range
    const timeRange = buildTimeRangeFromKey(
      timeKey,
      cap.native_step,
      deps.activeLayerGranularity.value,
    )
    if (!timeRange) {
      deps.logOperation?.('online-temporal', `无法构建 time_range: ${timeKey}`)
      return undefined
    }

    // 写入 submitting 状态
    const entry: OnlineFetchEntry = {
      key,
      catalogId,
      timeKey,
      status: 'submitting',
      submittedAt: Date.now(),
    }
    fetchEntries.value.set(key, entry)
    // 触发响应式
    fetchEntries.value = new Map(fetchEntries.value)

    const label = options?.isPrefetch ? '预获取' : '在线获取'
    deps.logOperation?.(
      'online-temporal',
      `${label} ${catalogId} @ ${timeKey} → ${timeRange.start_at} ~ ${timeRange.end_at}`,
    )

    // ── P2：优先走统一在线同步入口（后端承担去重/队列/预算语义） ──
    if (deps.syncLayerAssetOnline) {
      try {
        const resp = await deps.syncLayerAssetOnline(catalogId, {
          time_key: timeKey,
          is_prefetch: options?.isPrefetch,
          priority: cap.priority === 'low' ? 'low' : 'normal',
        })

        if (resp.status === 'succeeded') {
          // 资产已 fresh：无需 run，直接标记成功（时间轴经 lifecycle/overlayTimeStates 更新）
          updateEntry(key, { status: 'succeeded', settledAt: Date.now() })
          deps.logOperation?.(
            'online-temporal',
            `${label}完成（资产已就绪） ${catalogId} @ ${timeKey}`,
          )
          return undefined
        }

        if (resp.run_id && (resp.status === 'submitted' || resp.status === 'in-flight')) {
          updateEntry(key, { runId: resp.run_id, status: 'in-flight' })
          // 注册进前端轮询链：终态后由既有 watcher 物化产物 + markSucceeded
          if (deps.registerExternalWorkflowRun) {
            void deps.registerExternalWorkflowRun(resp.run_id, catalogId)
          }
          return resp.run_id
        }

        // skipped-unsupported 等异常分支 → 回退旧路径（见下方）
        deps.logOperation?.(
          'online-temporal',
          `${label}统一入口返回 ${resp.status}（${resp.message ?? ''}），回退直提路径 ${catalogId} @ ${timeKey}`,
        )
      } catch (err) {
        const message = err instanceof Error ? err.message : String(err)
        // 统一入口不可用（如旧后端无该路由 404）→ 回退旧路径而非直接失败
        deps.logOperation?.(
          'online-temporal',
          `${label}统一入口失败（${message}），回退直提路径 ${catalogId} @ ${timeKey}`,
        )
      }
    }

    // ── 回退路径：直接委托 workflow-run 域提交（P1 及之前行为） ──
    try {
      const runId = await deps.runWorkflowForCatalog(catalogId, {
        timeRange,
        resourceProfile: cap.priority === 'low' ? 'batch' : 'standard',
        commandLabel: `${label} ${timeKey}`,
      })

      if (runId) {
        updateEntry(key, { runId, status: 'in-flight' })
        // 工作流终态由现有 poller 跟踪；编排器通过 watcher 监听 jobLayers 状态变化
        return runId
      }

      // 提交未返回 run_id（可能是 429 限流等）
      updateEntry(key, { status: 'cooling', settledAt: Date.now(), error: '提交未返回 run_id' })
      return undefined
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err)
      updateEntry(key, { status: 'cooling', settledAt: Date.now(), error: message })
      deps.logOperation?.('online-temporal', `${label}失败 ${catalogId} @ ${timeKey}: ${message}`)
      return undefined
    }
  }

  /** 更新跟踪条目 */
  function updateEntry(key: string, patch: Partial<OnlineFetchEntry>) {
    const existing = fetchEntries.value.get(key)
    if (!existing) return
    const updated = { ...existing, ...patch }
    fetchEntries.value.set(key, updated)
    fetchEntries.value = new Map(fetchEntries.value)
  }

  /**
   * 标记获取成功（由外部 watcher 在 jobLayer 进入 succeeded 时调用）。
   * 成功后异步触发相邻时间点的预获取。
   */
  function markSucceeded(catalogId: string, runId: string) {
    for (const [key, entry] of fetchEntries.value.entries()) {
      if (entry.runId === runId) {
        updateEntry(key, { status: 'succeeded', settledAt: Date.now() })
        // 异步触发预获取
        const cap = deps.getOnlineTemporalConfig(catalogId)
        if (cap && cap.prefetch_depth > 0) {
          setTimeout(() => {
            prefetchAdjacent(catalogId, entry.timeKey, cap)
          }, PREFETCH_DELAY_MS)
        }
        break
      }
    }
  }

  /**
   * 预获取相邻时间点。
   * 向前后各 prefetch_depth 步发赽数据获取，使用 low priority 避免抢占用户操作。
   */
  async function prefetchAdjacent(
    catalogId: string,
    timeKey: string,
    cap: OnlineTemporalCapability,
  ) {
    const depth = cap.prefetch_depth
    const gran = deps.activeLayerGranularity.value
    const keysToPrefetch: string[] = []

    // 向前后各 depth 步生成时间键
    for (let d = 1; d <= depth; d++) {
      const futureKey = shiftTimeKey(timeKey, cap.native_step, d, gran)
      const pastKey = shiftTimeKey(timeKey, cap.native_step, -d, gran)
      if (futureKey && !keysToPrefetch.includes(futureKey)) keysToPrefetch.push(futureKey)
      if (pastKey && !keysToPrefetch.includes(pastKey)) keysToPrefetch.push(pastKey)
    }

    if (keysToPrefetch.length === 0) return

    deps.logOperation?.(
      'online-temporal',
      `预获取 ${catalogId} @ ${timeKey} → 相邻 ${keysToPrefetch.length} 个时间点`,
    )

    // 逐个提交（并发由 triggerOnlineFetch 内部控制）
    for (const adjKey of keysToPrefetch) {
      const adjKeyFull = `${catalogId}:${adjKey}`
      const existing = fetchEntries.value.get(adjKeyFull)
      // 已有终态记录 → 跳过
      if (
        existing &&
        (existing.status === 'succeeded' ||
          existing.status === 'in-flight' ||
          existing.status === 'submitting')
      ) {
        continue
      }
      // 延迟提交，避免与用户操作抢占
      await new Promise((resolve) => setTimeout(resolve, 500))
      void triggerOnlineFetch(catalogId, adjKey, { isPrefetch: true })
    }
  }

  /**
   * 标记获取失败（由外部 watcher 在 jobLayer 进入 failed 时调用）。
   */
  function markFailed(_catalogId: string, runId: string, error?: string) {
    for (const [key, entry] of fetchEntries.value.entries()) {
      if (entry.runId === runId) {
        updateEntry(key, { status: 'failed', settledAt: Date.now(), error })
        // 进入冷却
        setTimeout(() => updateEntry(key, { status: 'cooling' }), 0)
        break
      }
    }
  }

  /** 清理已终态且超过保留期的条目（5分钟） */
  function cleanupStaleEntries() {
    const now = Date.now()
    const RETENTION_MS = 5 * 60_000
    let changed = false
    for (const [key, entry] of fetchEntries.value.entries()) {
      if (
        (entry.status === 'succeeded' || entry.status === 'failed' || entry.status === 'cooling') &&
        entry.settledAt &&
        now - entry.settledAt > RETENTION_MS
      ) {
        fetchEntries.value.delete(key)
        changed = true
      }
    }
    if (changed) {
      fetchEntries.value = new Map(fetchEntries.value)
    }
  }

  return {
    fetchEntries: computed(() => fetchEntries.value),
    currentTimeKey,
    currentLayerSupportsOnline,
    currentFetchStatus,
    inFlightCount,
    triggerOnlineFetch,
    prefetchAdjacent,
    markSucceeded,
    markFailed,
    cleanupStaleEntries,
  }
}

export type OnlineTemporalOrchestrator = ReturnType<typeof useOnlineTemporalOrchestrator>
