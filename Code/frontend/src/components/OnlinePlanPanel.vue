<script setup lang="ts">
/**
 * OnlinePlanPanel — L1 在线计划会话（多图层 chips + 时段 + 双通道可用性 + 确认在线重跑）。
 * parked 时收成左下角「待决策 N」角标；确认前不改 job status / 不造 queued。
 */
import { computed, onMounted, onScopeDispose, ref, watch } from 'vue'
import AppButton from './ui/AppButton.vue'
import {
  useOnlinePlanSessionStore,
  type PlanCoverageSnapshot,
} from '../stores/online-plan-session'
import { useLayerWorkspace, useWorkflowRun } from '../stores/layers/selectors'
import { useUiStore } from '../stores/ui'
import { buildTimeRangeFromKey } from '../stores/layers/online-temporal-orchestrator'
import {
  fetchLayerDataCoverage,
  isDateCoveredByAnyChannel,
  type LayerDataCoverageResponse,
} from '../services/layer-coverage-api'
import {
  mergePlanParamOverrides,
  toAlgorithmParamsFromPlan,
  ONLINE_PLAN_PARAM_KEYS,
} from '../utils/online-plan-params'
import type { TimeGranularity } from '../utils/layer-timeline'
import { isPlausiblePlanTimeKey } from '../utils/time-key-coverage'
import { ONLINE_PLAN_COPY } from '../ui-copy'
import { useTimelineActionBannerStore } from '../stores/timeline-action-banner'

const plan = useOnlinePlanSessionStore()
const workspace = useLayerWorkspace()
const workflowRun = useWorkflowRun()
const uiStore = useUiStore()
const banner = useTimelineActionBannerStore()

const submitting = ref(false)
/** 防止并发确认：仅最新一代提交可 resolveTab；park/关闭会作废 */
let confirmGeneration = 0
/** coverage 拉取世代：切 tab 时丢弃过期响应，避免串层 */
let coverageGeneration = 0
const coverageLoading = ref(false)
const coverage = ref<LayerDataCoverageResponse | null>(null)
const draftDate = ref('')
const confirmError = ref<string | null>(null)
const draftError = ref<string | null>(null)

/** 面板/角标拖动后的视口坐标；null 用默认 CSS 定位 */
const panelPlaced = ref<{ left: number; top: number } | null>(null)
const dockPlaced = ref<{ left: number; top: number } | null>(null)
const panelDragging = ref(false)
const dockDragging = ref(false)
const panelRootRef = ref<HTMLElement | null>(null)
const dockRootRef = ref<HTMLElement | null>(null)
const PAD = 8
let panelDragOx = 0
let panelDragOy = 0
let dockDragOx = 0
let dockDragOy = 0
let panelPointerId: number | null = null
let dockPointerId: number | null = null
let dockMoved = false

const panelPosStyle = computed(() => {
  if (!panelPlaced.value) return undefined
  return {
    left: `${panelPlaced.value.left}px`,
    top: `${panelPlaced.value.top}px`,
    right: 'auto',
    bottom: 'auto',
    margin: '0',
  } as Record<string, string>
})

const dockPosStyle = computed(() => {
  if (!dockPlaced.value) return undefined
  return {
    left: `${dockPlaced.value.left}px`,
    top: `${dockPlaced.value.top}px`,
    right: 'auto',
    bottom: 'auto',
  } as Record<string, string>
})

function clampPos(left: number, top: number, width: number, height: number) {
  const maxL = Math.max(PAD, window.innerWidth - width - PAD)
  const maxT = Math.max(PAD, window.innerHeight - height - PAD)
  return {
    left: Math.min(Math.max(PAD, left), maxL),
    top: Math.min(Math.max(PAD, top), maxT),
  }
}

function onPanelDragDown(e: PointerEvent) {
  if (e.button !== 0) return
  const t = e.target as HTMLElement | null
  if (t?.closest('button, input, label, a, select, textarea')) return
  if (!t?.closest('.ops-header--drag')) return
  const el = panelRootRef.value
  if (!el) return
  e.preventDefault()
  e.stopPropagation()
  const rect = el.getBoundingClientRect()
  if (!panelPlaced.value) panelPlaced.value = { left: rect.left, top: rect.top }
  panelDragOx = e.clientX - panelPlaced.value.left
  panelDragOy = e.clientY - panelPlaced.value.top
  panelDragging.value = true
  panelPointerId = e.pointerId
  el.setPointerCapture?.(e.pointerId)
  window.addEventListener('pointermove', onPanelDragMove)
  window.addEventListener('pointerup', onPanelDragUp)
  window.addEventListener('pointercancel', onPanelDragUp)
}

function onPanelDragMove(e: PointerEvent) {
  if (!panelDragging.value || panelPointerId !== e.pointerId || !panelPlaced.value) return
  const el = panelRootRef.value
  if (!el) return
  panelPlaced.value = clampPos(
    e.clientX - panelDragOx,
    e.clientY - panelDragOy,
    el.offsetWidth,
    el.offsetHeight,
  )
}

function onPanelDragUp(e: PointerEvent) {
  if (panelPointerId !== e.pointerId) return
  panelDragging.value = false
  panelPointerId = null
  window.removeEventListener('pointermove', onPanelDragMove)
  window.removeEventListener('pointerup', onPanelDragUp)
  window.removeEventListener('pointercancel', onPanelDragUp)
}

function onDockDragDown(e: PointerEvent) {
  if (e.button !== 0) return
  const el = dockRootRef.value
  if (!el) return
  e.preventDefault()
  const rect = el.getBoundingClientRect()
  if (!dockPlaced.value) dockPlaced.value = { left: rect.left, top: rect.top }
  dockDragOx = e.clientX - dockPlaced.value.left
  dockDragOy = e.clientY - dockPlaced.value.top
  dockDragging.value = true
  dockMoved = false
  dockPointerId = e.pointerId
  el.setPointerCapture?.(e.pointerId)
}

function onDockDragMove(e: PointerEvent) {
  if (!dockDragging.value || dockPointerId !== e.pointerId || !dockPlaced.value) return
  const el = dockRootRef.value
  if (!el) return
  const next = clampPos(
    e.clientX - dockDragOx,
    e.clientY - dockDragOy,
    el.offsetWidth,
    el.offsetHeight,
  )
  if (
    Math.abs(next.left - dockPlaced.value.left) > 3 ||
    Math.abs(next.top - dockPlaced.value.top) > 3
  ) {
    dockMoved = true
  }
  dockPlaced.value = next
}

function onDockDragUp(e: PointerEvent) {
  if (dockPointerId !== e.pointerId) return
  dockDragging.value = false
  dockPointerId = null
  if (!dockMoved) reopen()
}

function onViewportResize() {
  const panel = panelRootRef.value
  if (panel && panelPlaced.value) {
    panelPlaced.value = clampPos(
      panelPlaced.value.left,
      panelPlaced.value.top,
      panel.offsetWidth,
      panel.offsetHeight,
    )
  }
  const dock = dockRootRef.value
  if (dock && dockPlaced.value) {
    dockPlaced.value = clampPos(
      dockPlaced.value.left,
      dockPlaced.value.top,
      dock.offsetWidth,
      dock.offsetHeight,
    )
  }
}

const isOpen = computed(() => plan.isOpen)
const isParked = computed(() => plan.isParked)
const tabs = computed(() => plan.tabs)
const activeTab = computed(() => plan.activeTab)
const pendingCount = computed(() => plan.pendingCount)
const unifiedTimeLock = computed(() => Boolean(uiStore.unifiedTimeLock))

/** 仅当草稿含白名单键时展示参数区（新 online 层无 orbit_mode 时不硬塞 FY UI） */
const showOrbitParam = computed(() => {
  const overrides = activeTab.value?.paramOverrides
  if (!overrides) return false
  return ONLINE_PLAN_PARAM_KEYS.some((k) => k in overrides)
})

const applyTimeLabel = computed(() =>
  unifiedTimeLock.value ? ONLINE_PLAN_COPY.applyToAll : ONLINE_PLAN_COPY.applyToActive,
)

const orbitMode = computed({
  get: () => String(activeTab.value?.paramOverrides?.orbit_mode ?? 'MWRID'),
  set: (v: string) => {
    const id = activeTab.value?.catalogId
    if (!id) return
    plan.updateTab(id, {
      paramOverrides: mergePlanParamOverrides(activeTab.value?.paramOverrides, {
        orbit_mode: v,
      }),
    })
  },
})

const failSummary = computed(() => {
  const t = activeTab.value
  if (!t) return ''
  const parts = [
    t.displayName || t.catalogId,
    `失败 ${t.failCount} 次`,
    t.lastFailMessage,
  ].filter(Boolean)
  return parts.join(' · ')
})

const localDatesPreview = computed(() => {
  const dates = coverage.value?.channels?.local?.dates ?? activeTab.value?.coverageSnapshot?.localDates ?? []
  return dates.slice(0, 12)
})

const onlineRangeLabel = computed(() => {
  const online = coverage.value?.channels?.online
  const snap = activeTab.value?.coverageSnapshot
  const start = online?.coverage_start ?? snap?.onlineStart
  const end = online?.coverage_end ?? snap?.onlineEnd
  if (!start && !end) return '在线覆盖未知'
  return `在线 ${start || '…'} → ${end || '…'}`
})

const dateCoveredHint = computed(() => {
  const key = draftDate.value.trim()
  if (!key) return ''
  if (!coverage.value) return ''
  const ok = isDateCoveredByAnyChannel(key, coverage.value, {
    allowOnlinePrefetchOnly: true,
  })
  return ok ? '选定日在本地或在线通道有数（可在线预拉）' : '选定日两侧均无覆盖，确认后仍可能缺数'
})

async function refreshCoverage(catalogId: string) {
  const gen = ++coverageGeneration
  coverageLoading.value = true
  coverage.value = null
  try {
    const backendId = workspace.resolveBackendLayerId?.(catalogId) ?? catalogId
    const resp = await fetchLayerDataCoverage(backendId)
    if (gen !== coverageGeneration) return
    coverage.value = resp
    const snap: PlanCoverageSnapshot = {
      localDates: resp.channels?.local?.dates ?? [],
      onlineStart: resp.channels?.online?.coverage_start,
      onlineEnd: resp.channels?.online?.coverage_end,
      nativeStep: resp.channels?.online?.native_step,
      fetchedAt: new Date().toISOString(),
    }
    // 仅当仍停留在该 tab 时写回，避免串层
    if (plan.activeCatalogId === catalogId) {
      plan.updateTab(catalogId, { coverageSnapshot: snap })
    }
  } catch {
    if (gen !== coverageGeneration) return
    // FE 兜底：descriptor online_temporal + 本地 job time 不可得时仅在线窗
    const cap = workspace.getOnlineTemporalConfig(catalogId)
    coverage.value = {
      layer_id: catalogId,
      channels: {
        online: {
          available: Boolean(cap),
          coverage_start: cap?.coverage_start ?? null,
          coverage_end: cap?.coverage_end ?? null,
          native_step: cap?.native_step ?? '1d',
        },
        local: { available: false, dates: [] },
      },
    }
  } finally {
    if (gen === coverageGeneration) coverageLoading.value = false
  }
}

function syncDraftFromTab() {
  const t = activeTab.value
  if (!t) return
  draftDate.value =
    t.timeKey ||
    t.timeRange?.start_at?.slice(0, 10) ||
    ''
  confirmError.value = null
  draftError.value = null
}

watch(
  () => activeTab.value?.catalogId,
  (id) => {
    if (!id || !plan.isOpen) return
    syncDraftFromTab()
    void refreshCoverage(id)
  },
  { immediate: true },
)

watch(
  () => plan.isOpen,
  (open) => {
    if (open) {
      // 面板打开时清掉 Banner，避免与 backdrop 叠层/残留反馈
      banner.dismissRecovery()
      banner.dismissNotice()
      if (activeTab.value?.catalogId) {
        syncDraftFromTab()
        void refreshCoverage(activeTab.value.catalogId)
      }
    } else {
      // 关闭/收起：作废进行中的确认与过期 coverage
      confirmGeneration += 1
      coverageGeneration += 1
      submitting.value = false
    }
  },
)

onMounted(() => {
  if (plan.isOpen && activeTab.value?.catalogId) {
    syncDraftFromTab()
    void refreshCoverage(activeTab.value.catalogId)
  }
  window.addEventListener('keydown', onPlanEscapeKey)
  window.addEventListener('resize', onViewportResize)
})

onScopeDispose(() => {
  window.removeEventListener('keydown', onPlanEscapeKey)
  window.removeEventListener('resize', onViewportResize)
  window.removeEventListener('pointermove', onPanelDragMove)
  window.removeEventListener('pointerup', onPanelDragUp)
  window.removeEventListener('pointercancel', onPanelDragUp)
  confirmGeneration += 1
  coverageGeneration += 1
})

function onPlanEscapeKey(e: KeyboardEvent) {
  if (e.key !== 'Escape') return
  if (!plan.isOpen) return
  e.preventDefault()
  park()
}

function selectTab(catalogId: string) {
  plan.setActiveCatalog(catalogId)
}

function park() {
  confirmGeneration += 1
  submitting.value = false
  plan.parkSession()
}

function reopen() {
  plan.openSession()
}

function applyDraftTimeToTab(): boolean {
  const key = draftDate.value.trim()
  draftError.value = null
  if (!key) {
    draftError.value = ONLINE_PLAN_COPY.invalidTimeKey
    return false
  }
  if (!isPlausiblePlanTimeKey(key)) {
    draftError.value = ONLINE_PLAN_COPY.invalidTimeKey
    return false
  }
  const t = activeTab.value
  if (!t && !unifiedTimeLock.value) return false

  const gran = (t?.timeRange?.granularity || 'day') as TimeGranularity

  if (unifiedTimeLock.value && plan.tabs.length > 0) {
    let applied = 0
    for (const tab of plan.tabs) {
      const cap = workspace.getOnlineTemporalConfig(tab.catalogId)
      const nativeStep = cap?.native_step || '1d'
      const range = buildTimeRangeFromKey(key, nativeStep, gran)
      if (!range) {
        draftError.value = ONLINE_PLAN_COPY.invalidTimeKey
        return false
      }
      plan.updateTab(tab.catalogId, {
        timeKey: key,
        timeRange: { start_at: range.start_at, end_at: range.end_at, granularity: gran },
      })
      applied += 1
    }
    return applied > 0
  }

  if (!t) return false
  const cap = workspace.getOnlineTemporalConfig(t.catalogId)
  const nativeStep = cap?.native_step || coverage.value?.channels?.online?.native_step || '1d'
  const range = buildTimeRangeFromKey(key, nativeStep, gran)
  if (!range) {
    draftError.value = ONLINE_PLAN_COPY.invalidTimeKey
    return false
  }
  plan.updateTab(t.catalogId, {
    timeKey: key,
    timeRange: { start_at: range.start_at, end_at: range.end_at, granularity: gran },
  })
  return true
}

async function confirmOnlineRerun() {
  const t = activeTab.value
  if (!t || submitting.value) return
  confirmError.value = null
  draftError.value = null

  if (!applyDraftTimeToTab()) {
    confirmError.value = draftError.value || ONLINE_PLAN_COPY.confirmNeedTime
    return
  }
  const tab = plan.activeTab
  if (!tab?.timeRange?.start_at || !tab.timeRange.end_at) {
    confirmError.value = ONLINE_PLAN_COPY.confirmNeedTime
    return
  }

  const block = (() => {
    const desc =
      workspace.resolveEffectiveDescriptor?.(tab.catalogId) ??
      workspace.resolveEffectiveDescriptor?.(
        workspace.resolveBackendLayerId?.(tab.catalogId) ?? tab.catalogId,
      ) ??
      null
    if ((desc as { online_ready?: boolean | null } | null)?.online_ready === false) {
      return (
        (desc as { run_readiness_summary?: string | null } | null)?.run_readiness_summary ||
        '在线变体凭据未就绪'
      )
    }
    return (
      workspace.getCatalogRunBlockReason?.(tab.catalogId) ??
      workspace.getCatalogRunBlockReason?.(
        workspace.resolveBackendLayerId?.(tab.catalogId) ?? tab.catalogId,
      ) ??
      null
    )
  })()
  if (block) {
    confirmError.value = `${block}（请先配置在线凭据）`
    return
  }

  const gen = ++confirmGeneration
  submitting.value = true
  banner.dismissRecovery()
  try {
    workflowRun.setWorkflowVariantPreference(tab.catalogId, 'online', { pinned: true })
    const backendId = workspace.resolveBackendLayerId?.(tab.catalogId) ?? tab.catalogId
    if (backendId !== tab.catalogId) {
      workflowRun.setWorkflowVariantPreference(backendId, 'online', { pinned: true })
    }

    // 安全中断：先 interrupt（停轮询 + fire-and-forget cancel），再 await 终态清理活跃 run
    workflowRun.interruptWorkflowForCatalog(tab.catalogId)
    const activeJobs = workflowRun.jobLayers.value.filter(
      (j) =>
        j.catalogId === tab.catalogId &&
        (j.status === 'running' || j.status === 'queued' || j.status === 'retry_pending'),
    )
    await Promise.all(
      activeJobs.map((job) =>
        workflowRun.cancelWorkflowRunForJob(job.jobId, tab.catalogId).catch(() => undefined),
      ),
    )
    if (gen !== confirmGeneration) return

    const algoParams = toAlgorithmParamsFromPlan(tab.paramOverrides)
    await workflowRun.runWorkflowForCatalog(tab.catalogId, {
      workflowVariant: 'online',
      timeRange: {
        start_at: tab.timeRange.start_at,
        end_at: tab.timeRange.end_at,
      },
      algorithmRequest: algoParams ? { algorithm_params: algoParams } : undefined,
      commandLabel: tab.timeKey
        ? `计划会话在线重跑 ${tab.timeKey}`
        : '计划会话在线重跑',
    })
    if (gen !== confirmGeneration) return

    if (tab.timeKey) uiStore.rememberLayerTime(tab.catalogId, { force: true })
    plan.resolveTab(tab.catalogId)
  } catch (err) {
    if (gen !== confirmGeneration) return
    confirmError.value = err instanceof Error ? err.message : String(err)
  } finally {
    if (gen === confirmGeneration) submitting.value = false
  }
}
</script>

<script lang="ts">
export default { name: 'OnlinePlanPanel' }
</script>

<template>
  <!-- parked 角标（可拖；单击未移动则重新打开） -->
  <Teleport to="body">
    <div
      v-if="isParked && pendingCount > 0"
      ref="dockRootRef"
      class="ops-dock"
      :class="{ 'is-placed': Boolean(dockPlaced), 'is-dragging': dockDragging }"
      :style="dockPosStyle"
      role="button"
      tabindex="0"
      :aria-label="ONLINE_PLAN_COPY.parkedDockAria"
      @pointerdown="onDockDragDown"
      @pointermove="onDockDragMove"
      @pointerup="onDockDragUp"
      @pointercancel="onDockDragUp"
      @keydown.enter.prevent="reopen"
      @keydown.space.prevent="reopen"
    >
      <span class="ops-dock-grip" aria-hidden="true" />
      {{ ONLINE_PLAN_COPY.parkedDock(pendingCount) }}
    </div>
  </Teleport>

  <Teleport to="body">
    <div v-if="isOpen && tabs.length" class="ops-backdrop" @click.self="park">
      <section
        ref="panelRootRef"
        class="ops-panel"
        :class="{ 'is-placed': Boolean(panelPlaced), 'is-dragging': panelDragging }"
        :style="panelPosStyle"
        role="dialog"
        aria-label="在线计划会话"
      >
        <header class="ops-header ops-header--drag" title="拖动面板" @pointerdown="onPanelDragDown">
          <div class="ops-title-row">
            <span class="ops-drag-grip" aria-hidden="true" />
            <h2 class="ops-title">{{ ONLINE_PLAN_COPY.panelTitle }}</h2>
            <span class="ops-sub">{{ ONLINE_PLAN_COPY.panelSub }}</span>
          </div>
          <div class="ops-header-actions">
            <AppButton variant="ghost" size="xs" type="button" @click="park">{{
              ONLINE_PLAN_COPY.parkCta
            }}</AppButton>
          </div>
        </header>

        <div class="ops-chips" role="tablist" aria-label="计划图层">
          <button
            v-for="tab in tabs"
            :key="tab.catalogId"
            type="button"
            role="tab"
            class="ops-chip"
            :class="{ 'is-active': tab.catalogId === activeTab?.catalogId }"
            :aria-selected="tab.catalogId === activeTab?.catalogId"
            @click="selectTab(tab.catalogId)"
          >
            {{ tab.displayName || tab.catalogId }}
            <span class="ops-chip-count">{{ tab.failCount }}</span>
          </button>
        </div>

        <div v-if="activeTab" class="ops-body">
          <p class="ops-summary">{{ failSummary }}</p>

          <div class="ops-section">
            <h3 class="ops-section-title">时段</h3>
            <div class="ops-row">
              <label class="ops-label">
                日期 / timeKey
                <input v-model="draftDate" class="ops-input" type="text" placeholder="YYYY-MM-DD" />
              </label>
              <AppButton
                variant="secondary"
                size="xs"
                type="button"
                :title="unifiedTimeLock ? ONLINE_PLAN_COPY.applyToAllHint : undefined"
                @click="applyDraftTimeToTab"
              >
                {{ applyTimeLabel }}
              </AppButton>
            </div>
            <p v-if="unifiedTimeLock" class="ops-hint">{{ ONLINE_PLAN_COPY.applyToAllHint }}</p>
            <p v-if="draftError" class="ops-error" role="alert">{{ draftError }}</p>
            <p v-else-if="dateCoveredHint" class="ops-hint">{{ dateCoveredHint }}</p>
          </div>

          <div class="ops-section">
            <h3 class="ops-section-title">双通道可用性</h3>
            <p v-if="coverageLoading" class="ops-hint">加载覆盖…</p>
            <div v-else class="ops-coverage">
              <div class="ops-band ops-band--online">
                <span class="ops-band-label">在线</span>
                <span class="ops-band-val">{{ onlineRangeLabel }}</span>
              </div>
              <div class="ops-band ops-band--local">
                <span class="ops-band-label">本地</span>
                <span class="ops-band-val">
                  <template v-if="localDatesPreview.length">
                    {{ localDatesPreview.join(', ')
                    }}{{ (coverage?.channels?.local?.dates?.length || 0) > 12 ? '…' : '' }}
                  </template>
                  <template v-else>无本地日期索引</template>
                </span>
              </div>
            </div>
          </div>

          <div v-if="showOrbitParam" class="ops-section">
            <h3 class="ops-section-title">在线参数（与流水线同源）</h3>
            <label class="ops-label">
              orbit_mode
              <select v-model="orbitMode" class="ops-input">
                <option value="MWRID">MWRID</option>
                <option value="MWRIA">MWRIA</option>
                <option value="Both">Both</option>
                <option value="ORBA">ORBA</option>
              </select>
            </label>
          </div>

          <p v-if="confirmError" class="ops-error" role="alert">{{ confirmError }}</p>

          <footer class="ops-footer">
            <AppButton variant="secondary" size="sm" type="button" @click="park">{{
              ONLINE_PLAN_COPY.parkCta
            }}</AppButton>
            <AppButton
              variant="primary"
              size="sm"
              type="button"
              :disabled="submitting"
              @click="confirmOnlineRerun"
            >
              {{ submitting ? ONLINE_PLAN_COPY.submittingCta : ONLINE_PLAN_COPY.confirmCta }}
            </AppButton>
          </footer>
        </div>
      </section>
    </div>
  </Teleport>
</template>

<style scoped>
.ops-dock {
  position: fixed;
  left: 12px;
  bottom: 108px;
  z-index: var(--z-toast);
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  padding: 0.35rem 0.65rem;
  border-radius: var(--radius-md, 0.5rem);
  border: 1px solid var(--accent-border, var(--border-strong));
  background: var(--accent-surface, var(--surface-2));
  color: var(--accent-strong, var(--text-strong));
  font-size: 0.75rem;
  font-weight: 700;
  cursor: grab;
  touch-action: none;
  user-select: none;
  box-shadow: var(--elevation-2, 0 4px 14px var(--shadow-ambient));
  animation: ops-dock-in 0.28s ease-out;
}

.ops-dock.is-placed {
  bottom: auto;
  right: auto;
}

.ops-dock.is-dragging {
  cursor: grabbing;
  opacity: 0.96;
}

.ops-dock-grip {
  width: 0.9rem;
  height: 0.28rem;
  border-radius: 999px;
  background: var(--border-strong);
  opacity: 0.85;
  flex-shrink: 0;
}

.ops-dock:hover {
  background: var(--surface-hover, var(--surface-2));
}

.ops-backdrop {
  position: fixed;
  inset: 0;
  z-index: calc(var(--z-toast) + 2);
  display: flex;
  align-items: flex-end;
  justify-content: flex-start;
  padding: 0.75rem;
  background: color-mix(in srgb, var(--shadow-ambient, #000) 28%, transparent);
  pointer-events: auto;
  animation: ops-backdrop-in 0.2s ease-out;
}

.ops-panel {
  position: relative;
  width: min(28rem, calc(100vw - 1.5rem));
  max-height: min(78vh, 36rem);
  overflow: auto;
  border-radius: var(--radius-md, 0.5rem);
  background: var(--surface-2);
  border: 1px solid var(--border-strong);
  box-shadow: var(--elevation-3, 0 8px 28px var(--shadow-ambient));
  color: var(--text-strong);
  animation: ops-slide-in 0.26s cubic-bezier(0.22, 1, 0.36, 1);
}

.ops-panel.is-placed {
  position: fixed;
  z-index: calc(var(--z-toast) + 3);
}

.ops-panel.is-dragging {
  opacity: 0.97;
  user-select: none;
}

.ops-header--drag {
  cursor: grab;
  touch-action: none;
}

.ops-drag-grip {
  width: 1.1rem;
  height: 0.28rem;
  border-radius: 999px;
  background: var(--border-strong);
  opacity: 0.85;
  flex-shrink: 0;
}

@keyframes ops-backdrop-in {
  from {
    opacity: 0;
  }
  to {
    opacity: 1;
  }
}

@keyframes ops-slide-in {
  from {
    opacity: 0;
    transform: translateX(-16px) translateY(6px);
  }
  to {
    opacity: 1;
    transform: translateX(0) translateY(0);
  }
}

@keyframes ops-dock-in {
  from {
    opacity: 0;
    transform: translateY(8px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

@media (prefers-reduced-motion: reduce) {
  .ops-dock,
  .ops-backdrop,
  .ops-panel,
  .ops-chip {
    animation: none;
    transition: none;
  }
}

.ops-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 0.5rem;
  padding: 0.65rem 0.75rem 0.4rem;
  border-bottom: 1px solid var(--border-default);
}

.ops-title-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.35rem 0.5rem;
  min-width: 0;
}

.ops-title {
  margin: 0;
  font-size: 0.95rem;
  font-weight: 700;
}

.ops-sub {
  display: block;
  margin-top: 0.15rem;
  font-size: 0.68rem;
  color: var(--text-secondary);
}

.ops-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem;
  padding: 0.5rem 0.75rem;
  border-bottom: 1px solid var(--border-default);
}

.ops-chip {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  max-width: 100%;
  padding: 0.2rem 0.45rem;
  border-radius: 0.35rem;
  border: 1px solid var(--border-default);
  background: var(--surface-sunken);
  color: var(--text-primary);
  font-size: 0.72rem;
  cursor: pointer;
  transition:
    background 0.15s ease,
    border-color 0.15s ease,
    color 0.15s ease,
    transform 0.12s ease;
}

.ops-chip:hover {
  border-color: var(--border-strong);
}

.ops-chip.is-active {
  border-color: var(--accent-border, var(--border-strong));
  background: var(--accent-surface);
  color: var(--text-strong);
  font-weight: 600;
}

.ops-chip:active {
  transform: scale(0.98);
}

.ops-chip-count {
  font-variant-numeric: tabular-nums;
  font-size: 0.65rem;
  opacity: 0.85;
}

.ops-body {
  padding: 0.55rem 0.75rem 0.75rem;
  display: flex;
  flex-direction: column;
  gap: 0.65rem;
}

.ops-summary {
  margin: 0;
  font-size: 0.78rem;
  line-height: 1.35;
  color: var(--text-primary);
}

.ops-section-title {
  margin: 0 0 0.3rem;
  font-size: 0.72rem;
  font-weight: 700;
  color: var(--text-secondary);
  text-transform: none;
}

.ops-row {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  gap: 0.4rem;
}

.ops-label {
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
  flex: 1 1 10rem;
  font-size: 0.7rem;
  color: var(--text-secondary);
}

.ops-input {
  padding: 0.28rem 0.4rem;
  border-radius: 0.3rem;
  border: 1px solid var(--border-default);
  background: var(--surface-sunken);
  color: var(--text-strong);
  font-size: 0.78rem;
}

.ops-hint {
  margin: 0.25rem 0 0;
  font-size: 0.68rem;
  color: var(--text-secondary);
}

.ops-coverage {
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
}

.ops-band {
  display: flex;
  gap: 0.45rem;
  align-items: baseline;
  padding: 0.3rem 0.4rem;
  border-radius: 0.3rem;
  border: 1px solid var(--border-default);
  font-size: 0.72rem;
}

.ops-band--online {
  border-left: 3px solid var(--accent, #3b82f6);
}

.ops-band--local {
  border-left: 3px solid var(--info, #22c55e);
}

.ops-band-label {
  flex: 0 0 auto;
  font-weight: 700;
  color: var(--text-secondary);
}

.ops-band-val {
  min-width: 0;
  color: var(--text-primary);
  word-break: break-all;
}

.ops-error {
  margin: 0;
  font-size: 0.75rem;
  color: var(--danger);
}

.ops-footer {
  display: flex;
  justify-content: flex-end;
  gap: 0.4rem;
  padding-top: 0.25rem;
}
</style>
