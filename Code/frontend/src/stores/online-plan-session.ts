/**
 * online-plan-session — 在线计划会话（1B + parked）
 *
 * - 旧 workflow run 保持 failed；确认前不造 queued
 * - session: open | parked | resolved
 * - tabs = 多图层 chips；failCount 驱动 L0→L1 升级（≥3）
 */
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

export const ONLINE_PLAN_ESCALATE_AFTER = 3

export type OnlinePlanVariant = 'online' | 'local'

export type PlanTimeRange = {
  start_at: string
  end_at: string
  granularity?: string
}

/** P1：双通道可用性快照（本地日期列表 + 在线覆盖窗） */
export type PlanCoverageSnapshot = {
  localDates: string[]
  onlineStart?: string | null
  onlineEnd?: string | null
  nativeStep?: string | null
  fetchedAt?: string
}

export type PlanTabDraft = {
  catalogId: string
  failCount: number
  lastFailMessage?: string
  lastJobId?: string
  preferredVariant: OnlinePlanVariant
  timeRange?: PlanTimeRange
  timeKey?: string | null
  /** P1：与流水线在线表单同源的参数覆盖 */
  paramOverrides?: Record<string, unknown>
  coverageSnapshot?: PlanCoverageSnapshot | null
  displayName?: string
}

export type OnlinePlanSessionStatus = 'open' | 'parked' | 'resolved'

export type OnlinePlanSession = {
  id: string
  status: OnlinePlanSessionStatus
  activeCatalogId: string
  tabs: PlanTabDraft[]
}

function newSessionId(): string {
  return `ops-${Date.now().toString(36)}`
}

export const useOnlinePlanSessionStore = defineStore('online-plan-session', () => {
  const session = ref<OnlinePlanSession | null>(null)
  /** 跨会话保留的每层失败计数（成功清零） */
  const failCounts = ref<Record<string, number>>({})

  const status = computed(() => session.value?.status ?? null)
  const tabs = computed(() => session.value?.tabs ?? [])
  const activeCatalogId = computed(() => session.value?.activeCatalogId ?? null)
  const pendingCount = computed(() => session.value?.tabs.length ?? 0)
  const isOpen = computed(() => session.value?.status === 'open')
  const isParked = computed(() => session.value?.status === 'parked')
  const hasPending = computed(() =>
    Boolean(session.value && session.value.tabs.length > 0 && session.value.status !== 'resolved'),
  )

  const activeTab = computed(() => {
    const s = session.value
    if (!s) return null
    return s.tabs.find((t) => t.catalogId === s.activeCatalogId) ?? s.tabs[0] ?? null
  })

  function getFailCount(catalogId: string): number {
    return failCounts.value[catalogId] ?? 0
  }

  function incrementFailCount(catalogId: string): number {
    const next = (failCounts.value[catalogId] ?? 0) + 1
    failCounts.value = { ...failCounts.value, [catalogId]: next }
    return next
  }

  function clearFailCount(catalogId: string) {
    if (!(catalogId in failCounts.value)) return
    const { [catalogId]: _, ...rest } = failCounts.value
    failCounts.value = rest
  }

  function ensureSession(activeId: string): OnlinePlanSession {
    if (session.value && session.value.status !== 'resolved') {
      return session.value
    }
    const created: OnlinePlanSession = {
      id: newSessionId(),
      status: 'open',
      activeCatalogId: activeId,
      tabs: [],
    }
    session.value = created
    return created
  }

  function ensureTab(
    catalogId: string,
    patch?: Partial<
      Pick<
        PlanTabDraft,
        | 'lastFailMessage'
        | 'lastJobId'
        | 'timeRange'
        | 'timeKey'
        | 'preferredVariant'
        | 'displayName'
        | 'paramOverrides'
        | 'coverageSnapshot'
      >
    >,
  ): PlanTabDraft {
    const s = ensureSession(catalogId)
    const existing = s.tabs.find((t) => t.catalogId === catalogId)
    const count = getFailCount(catalogId)
    if (existing) {
      Object.assign(existing, {
        failCount: count,
        ...patch,
      })
      s.activeCatalogId = catalogId
      if (s.status === 'parked' || s.status === 'resolved') s.status = 'open'
      session.value = { ...s, tabs: [...s.tabs] }
      return existing
    }
    const tab: PlanTabDraft = {
      catalogId,
      failCount: count,
      preferredVariant: patch?.preferredVariant ?? 'online',
      lastFailMessage: patch?.lastFailMessage,
      lastJobId: patch?.lastJobId,
      timeRange: patch?.timeRange,
      timeKey: patch?.timeKey ?? null,
      displayName: patch?.displayName,
      paramOverrides: patch?.paramOverrides ? { ...patch.paramOverrides } : undefined,
      coverageSnapshot: patch?.coverageSnapshot ?? null,
    }
    s.tabs.push(tab)
    s.activeCatalogId = catalogId
    s.status = 'open'
    session.value = { ...s, tabs: [...s.tabs] }
    return tab
  }

  function setActiveCatalog(catalogId: string) {
    const s = session.value
    if (!s || !s.tabs.some((t) => t.catalogId === catalogId)) return
    s.activeCatalogId = catalogId
    session.value = { ...s }
  }

  function updateTab(catalogId: string, patch: Partial<PlanTabDraft>) {
    const s = session.value
    if (!s) return
    const idx = s.tabs.findIndex((t) => t.catalogId === catalogId)
    if (idx < 0) return
    s.tabs[idx] = { ...s.tabs[idx], ...patch, catalogId }
    session.value = { ...s, tabs: [...s.tabs] }
  }

  function openSession() {
    const s = session.value
    if (!s || s.tabs.length === 0) return
    s.status = 'open'
    session.value = { ...s }
  }

  function parkSession() {
    const s = session.value
    if (!s || s.tabs.length === 0) return
    s.status = 'parked'
    session.value = { ...s }
  }

  /** 确认成功后移除该 tab；无剩余则 resolved */
  function resolveTab(catalogId: string) {
    const s = session.value
    if (!s) return
    const tabsNext = s.tabs.filter((t) => t.catalogId !== catalogId)
    clearFailCount(catalogId)
    if (tabsNext.length === 0) {
      session.value = {
        ...s,
        status: 'resolved',
        tabs: [],
        activeCatalogId: '',
      }
      return
    }
    const active = s.activeCatalogId === catalogId ? tabsNext[0].catalogId : s.activeCatalogId
    session.value = { ...s, tabs: tabsNext, activeCatalogId: active, status: 'open' }
  }

  function dismissSession() {
    session.value = null
  }

  /** 只读：catalog 是否在未 resolved 会话 tabs 中（供侧栏/分析框 badge） */
  function isCatalogPendingPlan(catalogId: string): boolean {
    const s = session.value
    if (!s || s.status === 'resolved' || !catalogId) return false
    return s.tabs.some((t) => t.catalogId === catalogId)
  }

  /**
   * P2：统一时间锁下把同一 timeKey/timeRange 写入本会话全部 tab。
   * 返回更新的 tab 数。
   */
  function applyTimeRangeToAllTabs(patch: { timeKey: string; timeRange?: PlanTimeRange }): number {
    const s = session.value
    if (!s || s.tabs.length === 0) return 0
    const key = String(patch.timeKey || '').trim()
    if (!key) return 0
    const tabsNext = s.tabs.map((t) => ({
      ...t,
      timeKey: key,
      timeRange: patch.timeRange ? { ...patch.timeRange } : t.timeRange,
    }))
    session.value = { ...s, tabs: tabsNext }
    return tabsNext.length
  }

  return {
    session,
    failCounts,
    status,
    tabs,
    activeCatalogId,
    activeTab,
    pendingCount,
    isOpen,
    isParked,
    hasPending,
    getFailCount,
    incrementFailCount,
    clearFailCount,
    ensureTab,
    setActiveCatalog,
    updateTab,
    openSession,
    parkSession,
    resolveTab,
    dismissSession,
    isCatalogPendingPlan,
    applyTimeRangeToAllTabs,
  }
})
