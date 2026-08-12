<script setup lang="ts">
/**
 * WorkflowTimerPanel.vue
 *
 * Phase 4: 工作流定时器管理面板（编辑器主区主从布局）。
 * Cron / 日期模板墙钟语义为 Asia/Shanghai；API 存 UTC ISO。
 */
import { computed, onBeforeUnmount, onMounted, onUnmounted, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { AlarmClock, X, CircleSlash, Timer, Play } from '../ui/icons'

import { useWorkflowTimersStore } from '../../stores/workflow-timers'
import { useWorkflowDefinitionsStore } from '../../stores/workflow-definitions'
import { previewCron, insertDateTemplateIntoOverridesJson } from '../../services/workflow-timer-api'
import type {
  WorkflowTimer,
  TriggerType,
  CreateTimerPayload,
  UpdateTimerPayload,
  TickStats,
} from '../../services/workflow-timer-api'
import WorkflowTimerEditorForm from './WorkflowTimerEditorForm.vue'
import './workflow-editor-chrome.css'

const TIMER_POLL_MS = 30_000
const LIST_MIN = 240
const LIST_MAX = 480
const LIST_DEFAULT = 320
const LIST_STORAGE_KEY = 'wf-timer-list-width'

const props = withDefaults(
  defineProps<{
    embedded?: boolean
    defaultWorkflowId?: string
  }>(),
  {
    embedded: false,
    defaultWorkflowId: '',
  },
)

const emit = defineEmits<{ close: [] }>()

const timersStore = useWorkflowTimersStore()
const definitionsStore = useWorkflowDefinitionsStore()
const { timers, loading, error, lastActionTimerId } = storeToRefs(timersStore)
const { summaries } = storeToRefs(definitionsStore)

function loadListWidth(): number {
  try {
    const raw = localStorage.getItem(LIST_STORAGE_KEY)
    const n = raw ? Number(raw) : LIST_DEFAULT
    if (Number.isFinite(n)) return Math.max(LIST_MIN, Math.min(LIST_MAX, n))
  } catch {
    /* ignore */
  }
  return LIST_DEFAULT
}

const listWidthPx = ref(loadListWidth())
const listResizing = ref(false)
let _listStartX = 0
let _listStartW = 0

function startListResize(event: MouseEvent) {
  listResizing.value = true
  _listStartX = event.clientX
  _listStartW = listWidthPx.value
  document.addEventListener('mousemove', onListResizeMove)
  document.addEventListener('mouseup', stopListResize)
  document.body.style.cursor = 'ew-resize'
  document.body.style.userSelect = 'none'
  event.preventDefault()
}

function onListResizeMove(event: MouseEvent) {
  if (!listResizing.value) return
  const next = _listStartW + (event.clientX - _listStartX)
  listWidthPx.value = Math.max(LIST_MIN, Math.min(LIST_MAX, next))
}

function stopListResize() {
  if (!listResizing.value) return
  listResizing.value = false
  document.removeEventListener('mousemove', onListResizeMove)
  document.removeEventListener('mouseup', stopListResize)
  document.body.style.cursor = ''
  document.body.style.userSelect = ''
  try {
    localStorage.setItem(LIST_STORAGE_KEY, String(listWidthPx.value))
  } catch {
    /* ignore */
  }
}

onBeforeUnmount(() => {
  if (listResizing.value) stopListResize()
})

const filterWorkflowId = ref(props.defaultWorkflowId || '')
const searchQuery = ref('')
watch(
  () => props.defaultWorkflowId,
  (id) => {
    if (id) filterWorkflowId.value = id
  },
)

const filteredTimers = computed(() => {
  let result = timers.value
  if (filterWorkflowId.value) {
    result = result.filter((t) => t.workflow_id === filterWorkflowId.value)
  }
  if (searchQuery.value.trim()) {
    const q = searchQuery.value.toLowerCase()
    result = result.filter(
      (t) =>
        t.name.toLowerCase().includes(q) ||
        t.timer_id.toLowerCase().includes(q) ||
        t.workflow_id.toLowerCase().includes(q),
    )
  }
  return result
})

const otherTimersCount = computed(() => {
  if (!filterWorkflowId.value) return 0
  return timers.value.filter((t) => t.workflow_id !== filterWorkflowId.value).length
})

const contextTitle = computed(() => {
  if (filterWorkflowId.value) {
    return `定时器 · ${workflowName(filterWorkflowId.value)}`
  }
  return '定时器 · 全部工作流'
})

const selectedTimerId = ref<string | null>(null)
const showEditor = ref(false)
const editingTimer = ref<WorkflowTimer | null>(null)

watch(filteredTimers, (list) => {
  if (selectedTimerId.value && !list.some((t) => t.timer_id === selectedTimerId.value)) {
    if (!editingTimer.value || editingTimer.value.timer_id === selectedTimerId.value) {
      selectedTimerId.value = null
      if (editingTimer.value) {
        showEditor.value = false
        editingTimer.value = null
      }
    }
  }
})

const cronPresets: Array<{ label: string; expr: string; description: string }> = [
  { label: '每小时', expr: '0 * * * *', description: '每整点触发（北京时间）' },
  { label: '每6小时', expr: '0 */6 * * *', description: '每天 0/6/12/18 点（北京时间）' },
  { label: '每天8点', expr: '0 8 * * *', description: '每天 08:00 北京时间' },
  { label: '每天0点', expr: '0 0 * * *', description: '每天 00:00 北京时间' },
  { label: '每周一', expr: '0 0 * * 1', description: '每周一 00:00 北京时间' },
  { label: '每月1日', expr: '0 0 1 * *', description: '每月 1 日 00:00 北京时间' },
  { label: '工作日8点', expr: '0 8 * * 1-5', description: '周一至周五 08:00 北京时间' },
  { label: '每15分钟', expr: '*/15 * * * *', description: '每 15 分钟触发（北京时间）' },
]

function applyCronPreset(expr: string) {
  editorForm.value.cron_expr = expr
  void fetchCronPreview(expr)
}

const cronPreviewTimes = ref<string[]>([])
const cronPreviewError = ref<string | null>(null)
const cronPreviewLoading = ref(false)
let _cronPreviewTimer: ReturnType<typeof setTimeout> | null = null

async function fetchCronPreview(expr: string) {
  cronPreviewError.value = null
  if (!expr.trim()) {
    cronPreviewTimes.value = []
    return
  }
  cronPreviewLoading.value = true
  try {
    const result = await previewCron(expr.trim(), 5)
    cronPreviewTimes.value = result.next_times
  } catch (err) {
    cronPreviewTimes.value = []
    cronPreviewError.value = err instanceof Error ? err.message : String(err)
  } finally {
    cronPreviewLoading.value = false
  }
}

function debouncedCronPreview(expr: string) {
  if (_cronPreviewTimer) clearTimeout(_cronPreviewTimer)
  _cronPreviewTimer = setTimeout(() => void fetchCronPreview(expr), 400)
}

const showDateTemplates = ref(false)

function insertDateTemplate(template: string) {
  const result = insertDateTemplateIntoOverridesJson(
    editorForm.value.payload_overrides_json,
    template,
  )
  if (result.error) {
    editorError.value = result.error
    return
  }
  editorForm.value.payload_overrides_json = result.json
  editorError.value = null
  showDateTemplates.value = false
}

const editorForm = ref({
  timer_id: '' as string,
  workflow_id: '' as string,
  name: '' as string,
  trigger_type: 'cron' as TriggerType,
  cron_expr: '0 * * * *' as string,
  interval_seconds: 3600 as number,
  event_type: '' as string,
  enabled: true as boolean,
  payload_overrides_json: '{}' as string,
})
const editorError = ref<string | null>(null)
const editorSaving = ref(false)

watch(
  () => editorForm.value.cron_expr,
  (expr) => {
    if (editorForm.value.trigger_type === 'cron' && expr) {
      debouncedCronPreview(expr)
    } else {
      cronPreviewTimes.value = []
      cronPreviewError.value = null
    }
  },
)

function onModelPatch(partial: Record<string, unknown>) {
  editorForm.value = { ...editorForm.value, ...partial } as typeof editorForm.value
}

function openCreate() {
  editingTimer.value = null
  selectedTimerId.value = null
  editorForm.value = {
    timer_id: '',
    workflow_id: filterWorkflowId.value || summaries.value[0]?.workflow_id || '',
    name: '',
    trigger_type: 'cron',
    cron_expr: '0 * * * *',
    interval_seconds: 3600,
    event_type: '',
    enabled: true,
    payload_overrides_json: '{}',
  }
  editorError.value = null
  showEditor.value = true
}

function selectTimer(timer: WorkflowTimer) {
  selectedTimerId.value = timer.timer_id
  editingTimer.value = timer
  editorForm.value = {
    timer_id: timer.timer_id,
    workflow_id: timer.workflow_id,
    name: timer.name,
    trigger_type: timer.trigger_type,
    cron_expr: timer.trigger_config.cron || '0 * * * *',
    interval_seconds: timer.trigger_config.seconds || 3600,
    event_type: timer.trigger_config.event_type || '',
    enabled: timer.enabled,
    payload_overrides_json: JSON.stringify(timer.payload_overrides, null, 2),
  }
  editorError.value = null
  showEditor.value = true
}

function cancelEditor() {
  showEditor.value = false
  editingTimer.value = null
  selectedTimerId.value = null
}

async function saveEditor() {
  editorError.value = null
  if (!editorForm.value.workflow_id.trim()) {
    editorError.value = 'workflow_id 必填'
    return
  }
  if (!editorForm.value.name.trim()) {
    editorError.value = 'name 必填'
    return
  }

  const trigger_type = editorForm.value.trigger_type
  let trigger_config: Record<string, unknown>
  if (trigger_type === 'cron') {
    if (!editorForm.value.cron_expr.trim()) {
      editorError.value = 'cron 表达式必填'
      return
    }
    trigger_config = { cron: editorForm.value.cron_expr.trim() }
  } else if (trigger_type === 'interval') {
    if (
      !Number.isFinite(editorForm.value.interval_seconds) ||
      editorForm.value.interval_seconds < 60
    ) {
      editorError.value = 'interval 秒数必须 >= 60'
      return
    }
    trigger_config = { seconds: Math.floor(editorForm.value.interval_seconds) }
  } else {
    if (!editorForm.value.event_type.trim()) {
      editorError.value = 'event_type 必填'
      return
    }
    trigger_config = { event_type: editorForm.value.event_type.trim() }
  }

  let payload_overrides: Record<string, unknown>
  try {
    payload_overrides = JSON.parse(editorForm.value.payload_overrides_json || '{}')
    if (
      payload_overrides === null ||
      typeof payload_overrides !== 'object' ||
      Array.isArray(payload_overrides)
    ) {
      throw new Error('not an object')
    }
  } catch (err) {
    editorError.value = `payload_overrides JSON 无效: ${(err as Error).message}`
    return
  }

  editorSaving.value = true
  try {
    if (editingTimer.value) {
      const updates: UpdateTimerPayload = {
        name: editorForm.value.name,
        enabled: editorForm.value.enabled,
        trigger_type,
        trigger_config: trigger_config as UpdateTimerPayload['trigger_config'],
        payload_overrides: payload_overrides as UpdateTimerPayload['payload_overrides'],
      }
      const updated = await timersStore.updateTimer(editingTimer.value.timer_id, updates)
      editingTimer.value = updated
      selectedTimerId.value = updated.timer_id
      selectTimer(updated)
    } else {
      const payload: CreateTimerPayload = {
        workflow_id: editorForm.value.workflow_id,
        name: editorForm.value.name,
        trigger_type,
        trigger_config: trigger_config as CreateTimerPayload['trigger_config'],
        payload_overrides: payload_overrides as CreateTimerPayload['payload_overrides'],
        enabled: editorForm.value.enabled,
      }
      const created = await timersStore.createTimer(payload)
      selectTimer(created)
    }
  } catch (err) {
    editorError.value = err instanceof Error ? err.message : String(err)
  } finally {
    editorSaving.value = false
  }
}

const confirmDeleteId = ref<string | null>(null)
const confirmDeleteName = ref('')
function askDelete(timer: WorkflowTimer) {
  confirmDeleteId.value = timer.timer_id
  confirmDeleteName.value = timer.name || timer.timer_id
}
function cancelDeleteConfirm() {
  confirmDeleteId.value = null
  confirmDeleteName.value = ''
}
async function confirmDelete() {
  if (!confirmDeleteId.value) return
  const deletedId = confirmDeleteId.value
  try {
    await timersStore.removeTimer(deletedId)
    if (selectedTimerId.value === deletedId) {
      selectedTimerId.value = null
      showEditor.value = false
      editingTimer.value = null
    }
  } catch (err) {
    console.error('[workflow-timer] delete failed:', err)
    alert(`删除失败: ${(err as Error).message}`)
  } finally {
    cancelDeleteConfirm()
  }
}

const runningTimerIds = ref<Set<string>>(new Set())
const lastTriggerResult = ref<{ timer_id: string; run_id: string } | null>(null)

function markTimerRunning(timerId: string, running: boolean) {
  const next = new Set(runningTimerIds.value)
  if (running) next.add(timerId)
  else next.delete(timerId)
  runningTimerIds.value = next
}

async function runTimer(timer: WorkflowTimer) {
  markTimerRunning(timer.timer_id, true)
  try {
    const result = await timersStore.runTimer(timer.timer_id)
    lastTriggerResult.value = { timer_id: timer.timer_id, run_id: result.run_id }
  } catch (err) {
    alert(`手动触发失败: ${(err as Error).message}`)
  } finally {
    markTimerRunning(timer.timer_id, false)
  }
}

const showEventDialog = ref(false)
const eventForm = ref({ event_type: '', payload_json: '{}' })
const eventResult = ref<{ matched: number; fired: number; failed: number } | null>(null)
const eventSaving = ref(false)

async function emitEvent() {
  eventResult.value = null
  if (!eventForm.value.event_type.trim()) {
    alert('event_type 必填')
    return
  }
  let payload: Record<string, unknown>
  try {
    payload = JSON.parse(eventForm.value.payload_json || '{}')
  } catch (err) {
    alert(`payload JSON 无效: ${(err as Error).message}`)
    return
  }
  eventSaving.value = true
  try {
    const result = await timersStore.emitEvent({
      event_type: eventForm.value.event_type.trim(),
      payload,
    })
    eventResult.value = result
  } catch (err) {
    alert(`事件发射失败: ${(err as Error).message}`)
  } finally {
    eventSaving.value = false
  }
}

const ticking = ref(false)
const tickResult = ref<TickStats | null>(null)
async function manualTick() {
  ticking.value = true
  tickResult.value = null
  try {
    tickResult.value = await timersStore.tick()
  } catch (err) {
    alert(`扫描失败: ${(err as Error).message}`)
  } finally {
    ticking.value = false
  }
}

function formatTime(iso: string | null): string {
  if (!iso) return '—'
  if (iso.startsWith('CLAIMED:')) return '触发中…'
  try {
    const d = new Date(iso)
    if (Number.isNaN(d.getTime())) return iso
    const beijing = d.toLocaleString('zh-CN', {
      hour12: false,
      timeZone: 'Asia/Shanghai',
    })
    const utc = d.toLocaleString('zh-CN', {
      hour12: false,
      timeZone: 'UTC',
    })
    return `${beijing}（北京） / ${utc} UTC`
  } catch {
    return iso
  }
}

function formatTimeShort(iso: string | null): string {
  if (!iso) return '—'
  if (iso.startsWith('CLAIMED:')) return '触发中…'
  try {
    const d = new Date(iso)
    if (Number.isNaN(d.getTime())) return iso
    return d.toLocaleString('zh-CN', {
      hour12: false,
      timeZone: 'Asia/Shanghai',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    })
  } catch {
    return iso
  }
}

function triggerSummary(t: WorkflowTimer): string {
  if (t.trigger_type === 'cron') return `cron: ${t.trigger_config.cron}`
  if (t.trigger_type === 'interval') {
    const s = t.trigger_config.seconds || 0
    if (s >= 86400) return `每 ${Math.floor(s / 86400)} 天`
    if (s >= 3600) return `每 ${Math.floor(s / 3600)} 小时`
    if (s >= 60) return `每 ${Math.floor(s / 60)} 分钟`
    return `每 ${s} 秒`
  }
  return `event: ${t.trigger_config.event_type}`
}

function triggerTypeLabel(t: TriggerType): string {
  return { cron: 'Cron', interval: '间隔', event: '事件' }[t]
}

function workflowName(workflowId: string): string {
  const s = summaries.value.find((item) => item.workflow_id === workflowId)
  return s?.name || workflowId
}

function showAllWorkflows() {
  filterWorkflowId.value = ''
}

const friendlyError = computed(() => {
  const raw = error.value || ''
  if (/404/.test(raw) && /workflow-timers/i.test(raw)) {
    return '定时器接口不可用（404）。请确认后端已重启并包含 /workflow-timers 路由；开发模式需 Vite 代理到后端。'
  }
  return raw
})

const workflowOptions = computed(() =>
  summaries.value.map((s) => ({ workflow_id: s.workflow_id, name: s.name })),
)

let _pollTimer: ReturnType<typeof setInterval> | null = null

onMounted(async () => {
  await Promise.all([timersStore.loadTimers(), definitionsStore.loadSummaries()])
  _pollTimer = setInterval(() => {
    void timersStore.loadTimers(undefined, { silent: true })
  }, TIMER_POLL_MS)
})

onUnmounted(() => {
  if (_cronPreviewTimer) {
    clearTimeout(_cronPreviewTimer)
    _cronPreviewTimer = null
  }
  if (_pollTimer) {
    clearInterval(_pollTimer)
    _pollTimer = null
  }
})
</script>

<template>
  <div
    :class="[embedded ? 'timer-embedded' : 'timer-overlay', !embedded && 'timer-overlay-anim']"
    @click.self="!embedded && emit('close')"
  >
    <div class="timer-panel" :class="{ 'timer-panel--embedded': embedded }">
      <div class="panel-header">
        <AlarmClock :size="18" class="header-icon" aria-hidden="true" />
        <span class="header-title">{{ contextTitle }}</span>
        <span class="header-tz-hint" title="Cron 与日期模板按 Asia/Shanghai 解释；存储为 UTC ISO"
          >北京时间</span
        >
        <div class="header-actions">
          <button
            class="header-btn"
            type="button"
            :disabled="ticking"
            title="立即扫描到期定时器（调试用，正常由 Celery Beat 每分钟自动执行）"
            @click="manualTick"
          >
            {{ ticking ? '扫描中...' : '立即扫描' }}
          </button>
          <button
            class="header-btn"
            type="button"
            title="发射外部事件，触发匹配的 event 类型定时器"
            @click="showEventDialog = true"
          >
            发射事件
          </button>
          <button
            class="header-btn"
            type="button"
            :disabled="loading"
            @click="timersStore.loadTimers()"
          >
            {{ loading ? '刷新中...' : '刷新' }}
          </button>
          <button class="header-btn primary" type="button" @click="openCreate">+ 新建</button>
          <button
            v-if="!embedded"
            class="close-btn"
            type="button"
            title="关闭"
            aria-label="关闭"
            @click="emit('close')"
          >
            <X :size="14" aria-hidden="true" />
          </button>
        </div>
      </div>

      <div class="panel-body panel-body--split">
        <div v-if="error" class="error-banner">
          <div>{{ friendlyError }}</div>
          <button class="header-btn" type="button" @click="timersStore.loadTimers()">重试</button>
        </div>
        <div v-if="tickResult" class="info-banner">
          扫描完成: 检查 {{ tickResult.checked }} 个，触发 {{ tickResult.fired }} 个，失败
          {{ tickResult.failed }} 个，跳过 {{ tickResult.skipped }} 个<template
            v-if="(tickResult.reclaimed ?? 0) > 0"
            >，回收 {{ tickResult.reclaimed }} 个</template
          >。
        </div>
        <div v-if="lastTriggerResult" class="info-banner">
          已触发 {{ lastTriggerResult.timer_id }} → run_id = {{ lastTriggerResult.run_id }}
        </div>

        <div class="timer-split" :class="{ resizing: listResizing }">
          <aside class="timer-list-pane" :style="{ width: `${listWidthPx}px` }">
            <div class="list-toolbar">
              <input
                v-model="searchQuery"
                type="text"
                class="search-input"
                placeholder="搜索定时器…"
              />
              <button
                v-if="filterWorkflowId"
                class="link-btn"
                type="button"
                @click="showAllWorkflows"
              >
                查看全部{{ otherTimersCount > 0 ? `（另有 ${otherTimersCount}）` : '' }}
              </button>
            </div>

            <div v-if="!loading && filteredTimers.length === 0" class="empty-state compact">
              <CircleSlash :size="20" class="empty-icon" aria-hidden="true" />
              <span>暂无定时器</span>
              <span class="empty-hint">为当前工作流创建调度任务</span>
              <button class="header-btn primary" type="button" @click="openCreate">
                + 新建定时器
              </button>
            </div>

            <div v-else class="timer-list wf-scroll">
              <button
                v-for="timer in filteredTimers"
                :key="timer.timer_id"
                type="button"
                class="timer-card"
                :class="{
                  disabled: !timer.enabled,
                  selected: selectedTimerId === timer.timer_id,
                }"
                @click="selectTimer(timer)"
              >
                <div class="card-title-row">
                  <span class="timer-name">{{ timer.name }}</span>
                  <span class="type-badge" :class="`badge-${timer.trigger_type}`">
                    {{ triggerTypeLabel(timer.trigger_type) }}
                  </span>
                </div>
                <div class="card-meta">
                  <span class="meta-line mono">{{ triggerSummary(timer) }}</span>
                  <span class="meta-line">下次 {{ formatTimeShort(timer.next_fire_at) }}</span>
                </div>
                <div class="card-actions" @click.stop>
                  <button
                    class="toggle-switch"
                    :class="{ on: timer.enabled }"
                    type="button"
                    :disabled="lastActionTimerId === timer.timer_id"
                    :title="timer.enabled ? '点击禁用' : '点击启用'"
                    :aria-label="timer.enabled ? '点击禁用' : '点击启用'"
                    @click="timersStore.toggleEnabled(timer)"
                  >
                    <span class="toggle-knob"></span>
                  </button>
                  <button
                    class="action-btn primary"
                    type="button"
                    :disabled="runningTimerIds.has(timer.timer_id)"
                    aria-label="运行定时器"
                    @click="runTimer(timer)"
                  >
                    {{ runningTimerIds.has(timer.timer_id) ? '…' : ''
                    }}<Play
                      v-if="!runningTimerIds.has(timer.timer_id)"
                      :size="14"
                      aria-hidden="true"
                    />
                  </button>
                  <button
                    class="action-btn danger"
                    type="button"
                    aria-label="删除定时器"
                    @click="askDelete(timer)"
                  >
                    <X :size="14" aria-hidden="true" />
                  </button>
                </div>
              </button>
            </div>
          </aside>

          <div
            class="wf-sidebar-resizer left timer-split-resizer"
            :class="{ active: listResizing }"
            title="拖拽调整列表宽度"
            @mousedown="startListResize"
          />

          <section class="timer-detail-pane wf-scroll">
            <div v-if="showEditor" class="detail-editor">
              <h3 class="detail-title">
                {{ editingTimer ? '编辑定时器' : '新建定时器' }}
              </h3>
              <p v-if="editingTimer" class="detail-sub mono">{{ editingTimer.timer_id }}</p>
              <div v-if="editingTimer" class="detail-stats">
                <span>上次触发：{{ formatTime(editingTimer.last_fired_at) }}</span>
                <span>触发次数：{{ editingTimer.fire_count }}</span>
                <span v-if="editingTimer.last_run_id" class="mono"
                  >run：{{ editingTimer.last_run_id }}</span
                >
                <span v-if="editingTimer.last_error" class="err" :title="editingTimer.last_error"
                  >上次失败</span
                >
              </div>
              <WorkflowTimerEditorForm
                :model="editorForm"
                :workflow-options="workflowOptions"
                :workflow-locked="!!editingTimer"
                :cron-presets="cronPresets"
                :cron-preview-times="cronPreviewTimes"
                :cron-preview-error="cronPreviewError"
                :cron-preview-loading="cronPreviewLoading"
                :show-date-templates="showDateTemplates"
                :editor-error="editorError"
                :editor-saving="editorSaving"
                :format-time="formatTime"
                @update:model="onModelPatch"
                @update:show-date-templates="showDateTemplates = $event"
                @apply-cron-preset="applyCronPreset"
                @insert-date-template="insertDateTemplate"
                @save="saveEditor"
                @cancel="cancelEditor"
              />
            </div>
            <div v-else class="detail-empty">
              <Timer :size="20" class="empty-icon" aria-hidden="true" />
              <h3>选择左侧定时器</h3>
              <p>查看详情、编辑触发规则，或新建调度任务。</p>
              <button class="header-btn primary" type="button" @click="openCreate">
                + 新建定时器
              </button>
            </div>
          </section>
        </div>
      </div>

      <div v-if="confirmDeleteId" class="dialog-overlay" @click.self="cancelDeleteConfirm">
        <div class="dialog">
          <h3 class="dialog-title">确认删除</h3>
          <p class="dialog-text">
            确定要删除定时器「{{ confirmDeleteName }}」（{{ confirmDeleteId }}）吗？此操作无法撤销。
          </p>
          <div class="dialog-actions">
            <button class="dialog-btn cancel" type="button" @click="cancelDeleteConfirm">
              取消
            </button>
            <button class="dialog-btn danger" type="button" @click="confirmDelete">删除</button>
          </div>
        </div>
      </div>

      <div v-if="showEventDialog" class="dialog-overlay" @click.self="showEventDialog = false">
        <div class="dialog">
          <h3 class="dialog-title">发射事件</h3>
          <p class="dialog-text">触发所有匹配 event_type 的已启用事件定时器。</p>
          <div class="dialog-form">
            <div class="form-row">
              <label class="form-label">事件类型 *</label>
              <input
                v-model="eventForm.event_type"
                type="text"
                class="form-input"
                placeholder="data_ready"
              />
            </div>
            <div class="form-row">
              <label class="form-label">Payload (JSON)</label>
              <textarea
                v-model="eventForm.payload_json"
                class="form-input mono textarea"
                rows="4"
                placeholder="{}"
              />
            </div>
          </div>
          <div v-if="eventResult" class="dialog-info">
            匹配 {{ eventResult.matched }} · 触发 {{ eventResult.fired }} · 失败
            {{ eventResult.failed }}
          </div>
          <div class="dialog-actions">
            <button class="dialog-btn cancel" type="button" @click="showEventDialog = false">
              关闭
            </button>
            <button
              class="dialog-btn primary"
              type="button"
              :disabled="eventSaving"
              @click="emitEvent"
            >
              {{ eventSaving ? '发射中...' : '发射' }}
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.timer-overlay {
  position: fixed;
  inset: 0;
  z-index: 998;
  display: flex;
  justify-content: flex-end;
  background: var(--surface-raised);
}

.timer-embedded {
  display: flex;
  flex-direction: column;
  flex: 1;
  align-self: stretch;
  width: 100%;
  min-width: 0;
  min-height: 0;
  height: 100%;
}

.timer-panel {
  width: 42rem;
  max-width: 92vw;
  height: 100vh;
  display: flex;
  flex-direction: column;
  background: var(--surface-2);
  border-left: 1px solid var(--border-default);
  box-shadow: -12px 0 36px rgba(1, 8, 16, 0.32);
}

.timer-panel.timer-panel--embedded {
  width: 100%;
  max-width: none;
  height: 100%;
  border-left: none;
  box-shadow: none;
  background: var(--surface-raised);
}

.panel-header {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  padding: 0.72rem 0.82rem;
  border-bottom: 1px solid var(--border-subtle);
  color: var(--text-strong);
  font-size: 0.88rem;
  font-weight: 600;
  flex: none;
}

.header-icon {
  font-size: 0.95rem;
  color: var(--accent);
}

.header-title {
  flex: 0 1 auto;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.header-tz-hint {
  margin-left: 0.5rem;
  margin-right: auto;
  font-size: var(--font-size-caption);
  font-weight: 500;
  color: var(--text-muted);
  border: 1px solid var(--border-strong);
  border-radius: 0.25rem;
  padding: 0.1rem 0.35rem;
  flex: none;
}

.header-actions {
  display: flex;
  gap: 0.32rem;
  align-items: center;
  flex: none;
}

.header-btn {
  padding: 0.36rem 0.68rem;
  border: 1px solid var(--accent-border);
  border-radius: 0.35rem;
  background: var(--surface-1);
  color: var(--text-primary);
  font-size: var(--font-size-caption);
  cursor: pointer;
}

.header-btn.primary {
  border-color: var(--border-strong);
  background: var(--accent-blue-deep, #1a5fcc);
  color: #fff;
}

.header-btn:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.close-btn {
  border: none;
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
  font-size: 0.85rem;
}

.panel-body {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.panel-body--split {
  padding: 0;
}

.error-banner,
.info-banner {
  margin: 0.5rem 0.72rem 0;
  padding: 0.45rem 0.62rem;
  border-radius: 0.35rem;
  font-size: var(--font-size-caption);
  flex: none;
}

.error-banner {
  background: var(--danger-surface);
  color: var(--danger);
  border: 1px solid var(--danger-border);
}

.info-banner {
  background: var(--surface-sunken);
  color: var(--text-secondary);
  border: 1px solid var(--accent-border);
}

.timer-split {
  flex: 1;
  min-height: 0;
  display: flex;
  position: relative;
  overflow: hidden;
}

.timer-split.resizing {
  user-select: none;
}

.timer-list-pane {
  flex: none;
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
  border-right: 1px solid var(--border-subtle);
  background: var(--surface-raised);
}

.wf-sidebar-resizer.timer-split-resizer {
  position: relative;
  flex: none;
  width: 8px;
  align-self: stretch;
  right: auto;
  left: auto;
}

.timer-detail-pane {
  flex: 1;
  min-width: 0;
  min-height: 0;
  overflow: auto;
  padding: 0.85rem 1rem;
  background: var(--surface-sunken);
}

.list-toolbar {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
  padding: 0.55rem 0.55rem 0.4rem;
  flex: none;
}

.search-input {
  width: 100%;
  padding: 0.35rem 0.45rem;
  border-radius: 0.3rem;
  border: 1px solid var(--border-default);
  background: var(--surface-1);
  color: var(--text-strong);
  font-size: var(--font-size-caption);
}

.link-btn {
  align-self: flex-start;
  border: none;
  background: transparent;
  color: var(--accent);
  font-size: var(--font-size-caption);
  cursor: pointer;
  padding: 0;
}

.timer-list {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: 0.35rem 0.45rem 0.7rem;
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
}

.timer-card {
  text-align: left;
  display: flex;
  flex-direction: column;
  gap: 0.32rem;
  padding: 0.55rem 0.55rem 0.45rem;
  border-radius: 0.4rem;
  border: 1px solid var(--border-default);
  background: var(--surface-1);
  color: inherit;
  cursor: pointer;
}

.timer-card:hover {
  border-color: var(--border-strong);
}

.timer-card.selected {
  border-color: var(--border-strong);
  box-shadow: inset 0 0 0 1px var(--border-accent);
}

.timer-card.disabled {
  opacity: 0.62;
}

.card-title-row {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  min-width: 0;
}

.timer-name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: var(--font-size-caption);
  font-weight: 600;
  color: var(--text-strong);
}

.type-badge {
  flex: none;
  font-size: var(--font-size-caption);
  padding: 0.08rem 0.32rem;
  border-radius: 0.25rem;
  background: rgba(60, 120, 180, 0.35);
  color: var(--text-secondary);
}

.badge-interval {
  background: rgba(80, 140, 90, 0.35);
}
.badge-event {
  background: rgba(140, 100, 60, 0.4);
}

.card-meta {
  display: flex;
  flex-direction: column;
  gap: 0.12rem;
}

.meta-line {
  font-size: var(--font-size-caption);
  color: var(--text-muted);
}

.mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
}

.card-actions {
  display: flex;
  align-items: center;
  gap: 0.28rem;
  margin-top: 0.1rem;
}

.toggle-switch {
  position: relative;
  width: 1.8rem;
  height: 1rem;
  border-radius: 999px;
  border: 1px solid var(--border-strong);
  background: var(--surface-2);
  cursor: pointer;
  padding: 0;
}

.toggle-switch.on {
  background: var(--success);
  border-color: var(--success-border);
}

.toggle-knob {
  position: absolute;
  top: 1px;
  left: 2px;
  width: 0.7rem;
  height: 0.7rem;
  border-radius: 50%;
  background: var(--text-primary);
  transition: left 0.15s ease;
}

.toggle-switch.on .toggle-knob {
  left: calc(100% - 0.78rem);
}

.action-btn {
  padding: 0.18rem 0.4rem;
  border-radius: 0.28rem;
  border: 1px solid var(--border-strong);
  background: var(--surface-1);
  color: var(--text-primary);
  font-size: var(--font-size-caption);
  cursor: pointer;
}

.action-btn.primary {
  border-color: var(--border-strong);
}

.action-btn.danger {
  border-color: rgba(255, 120, 120, 0.35);
  color: var(--danger);
}

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 0.45rem;
  padding: 1.5rem 1rem;
  color: var(--text-muted);
  font-size: var(--font-size-caption);
  text-align: center;
}

.empty-state.compact {
  flex: 1;
}

.empty-icon {
  font-size: 1.6rem;
  opacity: 0.7;
}

.empty-hint {
  font-size: var(--font-size-caption);
  color: var(--text-faint);
}

.detail-empty {
  height: 100%;
  min-height: 16rem;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
  color: var(--text-muted);
  text-align: center;
}

.detail-empty h3 {
  margin: 0;
  font-size: 0.95rem;
  color: var(--text-primary);
}

.detail-empty p {
  margin: 0;
  font-size: var(--font-size-caption);
  max-width: 22rem;
}

.detail-editor {
  max-width: 40rem;
}

.detail-title {
  margin: 0 0 0.25rem;
  font-size: 0.92rem;
  color: var(--text-strong);
}

.detail-sub {
  margin: 0 0 0.55rem;
  font-size: var(--font-size-caption);
  color: var(--text-muted);
}

.detail-stats {
  display: flex;
  flex-wrap: wrap;
  gap: 0.55rem 0.9rem;
  margin-bottom: 0.85rem;
  font-size: var(--font-size-caption);
  color: var(--text-secondary);
}

.detail-stats .err {
  color: var(--danger);
}

.dialog-overlay {
  position: absolute;
  inset: 0;
  z-index: 20;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--surface-raised);
}

.dialog {
  width: min(28rem, 92%);
  max-height: 86%;
  overflow: auto;
  padding: 1rem;
  border-radius: 0.5rem;
  border: 1px solid var(--border-default);
  background: var(--surface-2);
  box-shadow: 0 16px 40px rgba(0, 0, 0, 0.45);
}

.dialog-title {
  margin: 0 0 0.55rem;
  font-size: 0.9rem;
  color: var(--text-strong);
}

.dialog-text {
  margin: 0 0 0.75rem;
  font-size: var(--font-size-caption);
  color: var(--text-secondary);
}

.dialog-form {
  display: flex;
  flex-direction: column;
  gap: 0.65rem;
}

.form-row {
  display: flex;
  flex-direction: column;
  gap: 0.28rem;
}

.form-label {
  font-size: var(--font-size-caption);
  color: var(--text-primary);
}

.form-input {
  padding: 0.4rem 0.5rem;
  border-radius: 0.35rem;
  border: 1px solid var(--border-strong);
  background: var(--surface-1);
  color: var(--text-strong);
  font-size: var(--font-size-caption);
}

.form-input.textarea {
  resize: vertical;
  min-height: 4rem;
}

.dialog-info {
  margin: 0.55rem 0;
  font-size: var(--font-size-caption);
  color: var(--text-secondary);
}

.dialog-actions {
  display: flex;
  justify-content: flex-end;
  gap: 0.4rem;
  margin-top: 0.75rem;
}

.dialog-btn {
  padding: 0.38rem 0.72rem;
  border-radius: 0.35rem;
  border: 1px solid var(--border-strong);
  background: var(--surface-2);
  color: var(--text-primary);
  font-size: var(--font-size-caption);
  cursor: pointer;
}

.dialog-btn.primary {
  border-color: var(--border-strong);
  background: var(--surface-3);
}

.dialog-btn.danger {
  border-color: var(--danger-border);
  color: var(--danger);
  background: var(--danger-surface);
}

/* ── 定时器面板滑入动画（overlay 模式） ──────────────────────── */
.timer-overlay-anim {
  animation: timer-overlay-fade 0.2s ease;
}
.timer-overlay-anim .timer-panel {
  animation: timer-panel-slide-in 0.26s cubic-bezier(0.22, 1, 0.36, 1);
}
@keyframes timer-overlay-fade {
  from { opacity: 0; }
  to { opacity: 1; }
}
@keyframes timer-panel-slide-in {
  from { transform: translateX(100%); }
  to { transform: translateX(0); }
}

/* ── 确认/事件对话框动画 ────────────────────────────────────── */
.dialog-overlay {
  animation: dialog-fade-in 0.18s ease;
}
.dialog {
  animation: dialog-pop-in 0.22s cubic-bezier(0.22, 1, 0.36, 1);
}
@keyframes dialog-fade-in {
  from { opacity: 0; }
  to { opacity: 1; }
}
@keyframes dialog-pop-in {
  from {
    opacity: 0;
    transform: scale(0.95) translateY(6px);
  }
  to {
    opacity: 1;
    transform: scale(1) translateY(0);
  }
}

@media (prefers-reduced-motion: reduce) {
  .timer-overlay-anim,
  .timer-overlay-anim .timer-panel,
  .dialog-overlay,
  .dialog {
    animation: none;
    transition: opacity 0.01s ease;
  }
}
</style>
