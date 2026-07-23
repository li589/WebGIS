<script setup lang="ts">
/**
 * WorkflowTimerPanel.vue
 *
 * Phase 4: 工作流定时器管理面板。
 * 提供 CRUD + 启用/禁用 + 手动触发 + 事件发射 + 立即扫描 等操作。
 *
 * 集成方式：作为模态弹窗从 WorkflowList 或 DashboardView 触发。
 */
import { computed, onMounted, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'

import { useWorkflowTimersStore } from '../../stores/workflow-timers'
import { useWorkflowDefinitionsStore } from '../../stores/workflow-definitions'
import type {
  WorkflowTimer,
  TriggerType,
  CreateTimerPayload,
  UpdateTimerPayload,
} from '../../services/workflow-timer-api'

const props = withDefaults(
  defineProps<{
    /** 嵌入流配置面板时使用（无全屏遮罩） */
    embedded?: boolean
    /** 默认按该 workflow 过滤 */
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

// ─── 过滤 ────────────────────────────────────────────────────────────────────
const filterWorkflowId = ref(props.defaultWorkflowId || '')
watch(
  () => props.defaultWorkflowId,
  (id) => {
    if (id) filterWorkflowId.value = id
  },
)
const filteredTimers = computed(() => {
  if (!filterWorkflowId.value) return timers.value
  return timers.value.filter((t) => t.workflow_id === filterWorkflowId.value)
})

// ─── 新建/编辑对话框 ────────────────────────────────────────────────────────
const editingTimer = ref<WorkflowTimer | null>(null)
const showEditor = ref(false)

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

function openCreate() {
  editingTimer.value = null
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

function openEdit(timer: WorkflowTimer) {
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

  // 构造 trigger_config
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

  // 解析 payload_overrides JSON
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
        trigger_config: trigger_config as any,
        payload_overrides: payload_overrides as any,
      }
      await timersStore.updateTimer(editingTimer.value.timer_id, updates)
    } else {
      const payload: CreateTimerPayload = {
        workflow_id: editorForm.value.workflow_id,
        name: editorForm.value.name,
        trigger_type,
        trigger_config: trigger_config as any,
        payload_overrides: payload_overrides as any,
        enabled: editorForm.value.enabled,
      }
      await timersStore.createTimer(payload)
    }
    showEditor.value = false
  } catch (err) {
    editorError.value = err instanceof Error ? err.message : String(err)
  } finally {
    editorSaving.value = false
  }
}

// ─── 删除确认 ────────────────────────────────────────────────────────────────
const confirmDeleteId = ref<string | null>(null)
function askDelete(timer: WorkflowTimer) {
  confirmDeleteId.value = timer.timer_id
}
async function confirmDelete() {
  if (!confirmDeleteId.value) return
  try {
    await timersStore.removeTimer(confirmDeleteId.value)
  } catch (err) {
    console.error('[workflow-timer] delete failed:', err)
  } finally {
    confirmDeleteId.value = null
  }
}

// ─── 手动触发 ────────────────────────────────────────────────────────────────
const runningTimerIds = ref<Set<string>>(new Set())
const lastTriggerResult = ref<{ timer_id: string; run_id: string } | null>(null)

async function runTimer(timer: WorkflowTimer) {
  runningTimerIds.value.add(timer.timer_id)
  try {
    const result = await timersStore.runTimer(timer.timer_id)
    lastTriggerResult.value = { timer_id: timer.timer_id, run_id: result.run_id }
  } catch (err) {
    alert(`手动触发失败: ${(err as Error).message}`)
  } finally {
    runningTimerIds.value.delete(timer.timer_id)
  }
}

// ─── 事件发射对话框 ─────────────────────────────────────────────────────────
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

// ─── 立即扫描（手动触发 Beat） ─────────────────────────────────────────────
const ticking = ref(false)
const tickResult = ref<{ checked: number; fired: number; failed: number } | null>(null)
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

// ─── 格式化辅助 ─────────────────────────────────────────────────────────────
function formatTime(iso: string | null): string {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleString('zh-CN', { hour12: false })
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
  const s = summaries.value.find((s) => s.workflow_id === workflowId)
  return s?.name || workflowId
}

const friendlyError = computed(() => {
  const raw = error.value || ''
  if (/404/.test(raw) && /workflow-timers/i.test(raw)) {
    return '定时器接口不可用（404）。请确认后端已重启并包含 /workflow-timers 路由；开发模式需 Vite 代理到后端。'
  }
  return raw
})

// ─── 生命周期 ────────────────────────────────────────────────────────────────
onMounted(async () => {
  await Promise.all([timersStore.loadTimers(), definitionsStore.loadSummaries()])
})
</script>

<template>
  <div
    :class="embedded ? 'timer-embedded' : 'timer-overlay'"
    @click.self="!embedded && emit('close')"
  >
    <div class="timer-panel" :class="{ 'timer-panel--embedded': embedded }">
      <div class="panel-header">
        <span class="header-icon" aria-hidden="true">⏰</span>
        <span class="header-title">工作流定时器</span>
        <div class="header-actions">
          <button
            class="header-btn"
            type="button"
            :disabled="ticking"
            @click="manualTick"
            title="立即扫描到期定时器（调试用，正常由 Celery Beat 每分钟自动执行）"
          >
            {{ ticking ? '扫描中...' : '立即扫描' }}
          </button>
          <button
            class="header-btn"
            type="button"
            @click="showEventDialog = true"
            title="发射外部事件，触发匹配的 event 类型定时器"
          >
            发射事件
          </button>
          <button class="header-btn primary" type="button" @click="openCreate">+ 新建</button>
          <button
            v-if="!embedded"
            class="close-btn"
            type="button"
            @click="emit('close')"
            title="关闭"
          >
            <span aria-hidden="true">✕</span>
          </button>
        </div>
      </div>

      <div class="panel-body">
        <!-- 过滤器 -->
        <div class="filter-row">
          <label class="filter-label">按工作流过滤</label>
          <select v-model="filterWorkflowId" class="filter-select">
            <option value="">全部工作流</option>
            <option v-for="s in summaries" :key="s.workflow_id" :value="s.workflow_id">
              {{ s.name }} ({{ s.workflow_id }})
            </option>
          </select>
          <button
            class="refresh-btn"
            type="button"
            :disabled="loading"
            @click="timersStore.loadTimers()"
          >
            {{ loading ? '刷新中...' : '刷新' }}
          </button>
        </div>

        <!-- 错误提示 -->
        <div v-if="error" class="error-banner">
          <div>{{ friendlyError }}</div>
          <button
            class="header-btn"
            type="button"
            style="margin-top: 0.4rem"
            @click="timersStore.loadTimers()"
          >
            重试
          </button>
        </div>

        <!-- 扫描结果 -->
        <div v-if="tickResult" class="info-banner">
          扫描完成: 检查 {{ tickResult.checked }} 个，触发 {{ tickResult.fired }} 个， 失败
          {{ tickResult.failed }} 个。
        </div>

        <!-- 手动触发结果 -->
        <div v-if="lastTriggerResult" class="info-banner">
          定时器 {{ lastTriggerResult.timer_id }} 已触发： run_id = {{ lastTriggerResult.run_id }}
        </div>

        <!-- 空状态 -->
        <div v-if="!loading && filteredTimers.length === 0" class="empty-state">
          <span class="empty-icon" aria-hidden="true">∅</span>
          <span>暂无定时器</span>
          <span class="empty-hint">点击"+ 新建"创建第一个定时器</span>
        </div>

        <!-- 定时器列表 -->
        <div v-else class="timer-list">
          <div
            v-for="timer in filteredTimers"
            :key="timer.timer_id"
            class="timer-card"
            :class="{ disabled: !timer.enabled }"
          >
            <div class="card-header">
              <div class="card-title-row">
                <span class="timer-name">{{ timer.name }}</span>
                <span class="type-badge" :class="`badge-${timer.trigger_type}`">
                  {{ triggerTypeLabel(timer.trigger_type) }}
                </span>
                <span v-if="!timer.enabled" class="disabled-badge">已禁用</span>
                <span v-if="timer.last_error" class="error-badge" :title="timer.last_error">
                  ⚠ 上次失败
                </span>
              </div>
              <div class="card-meta">
                <span class="meta-row">
                  <span class="meta-label">工作流:</span>
                  <span class="meta-value">{{ workflowName(timer.workflow_id) }}</span>
                </span>
                <span class="meta-row">
                  <span class="meta-label">触发器:</span>
                  <code class="meta-value mono">{{ triggerSummary(timer) }}</code>
                </span>
                <span class="meta-row">
                  <span class="meta-label">下次触发:</span>
                  <span class="meta-value">{{ formatTime(timer.next_fire_at) }}</span>
                </span>
                <span class="meta-row">
                  <span class="meta-label">上次触发:</span>
                  <span class="meta-value">{{ formatTime(timer.last_fired_at) }}</span>
                </span>
                <span v-if="timer.last_run_id" class="meta-row">
                  <span class="meta-label">上次运行:</span>
                  <code class="meta-value mono">{{ timer.last_run_id }}</code>
                </span>
                <span class="meta-row">
                  <span class="meta-label">触发次数:</span>
                  <span class="meta-value">{{ timer.fire_count }}</span>
                </span>
              </div>
            </div>

            <div class="card-actions">
              <button
                class="toggle-switch"
                :class="{ on: timer.enabled }"
                type="button"
                :disabled="lastActionTimerId === timer.timer_id"
                :title="timer.enabled ? '点击禁用' : '点击启用'"
                @click="timersStore.toggleEnabled(timer)"
              >
                <span class="toggle-knob"></span>
              </button>
              <button
                class="action-btn primary"
                type="button"
                :disabled="runningTimerIds.has(timer.timer_id)"
                @click="runTimer(timer)"
              >
                {{ runningTimerIds.has(timer.timer_id) ? '运行中...' : '▶ 立即运行' }}
              </button>
              <button class="action-btn" type="button" @click="openEdit(timer)">⚙ 编辑</button>
              <button class="action-btn danger" type="button" @click="askDelete(timer)">
                ✕ 删除
              </button>
            </div>
          </div>
        </div>
      </div>

      <!-- 新建/编辑对话框 -->
      <div v-if="showEditor" class="dialog-overlay" @click.self="showEditor = false">
        <div class="dialog">
          <h3 class="dialog-title">
            {{ editingTimer ? '编辑定时器' : '新建定时器' }}
          </h3>
          <div class="dialog-form">
            <div class="form-row">
              <label class="form-label">工作流 *</label>
              <select
                v-model="editorForm.workflow_id"
                class="form-input"
                :disabled="!!editingTimer"
              >
                <option value="" disabled>请选择工作流</option>
                <option v-for="s in summaries" :key="s.workflow_id" :value="s.workflow_id">
                  {{ s.name }} ({{ s.workflow_id }})
                </option>
              </select>
            </div>
            <div class="form-row">
              <label class="form-label">名称 *</label>
              <input
                v-model="editorForm.name"
                type="text"
                class="form-input"
                placeholder="例如：每天 8 点运行"
              />
            </div>
            <div class="form-row">
              <label class="form-label">触发类型</label>
              <div class="radio-group">
                <label class="radio-label">
                  <input v-model="editorForm.trigger_type" type="radio" value="cron" />
                  <span>Cron 表达式</span>
                </label>
                <label class="radio-label">
                  <input v-model="editorForm.trigger_type" type="radio" value="interval" />
                  <span>固定间隔</span>
                </label>
                <label class="radio-label">
                  <input v-model="editorForm.trigger_type" type="radio" value="event" />
                  <span>事件触发</span>
                </label>
              </div>
            </div>
            <div v-if="editorForm.trigger_type === 'cron'" class="form-row">
              <label class="form-label">
                Cron 表达式 *
                <span class="form-hint"
                  >（5 字段：分 时 日 月 周，例如 "0 8 * * *" 每天 8 点）</span
                >
              </label>
              <input
                v-model="editorForm.cron_expr"
                type="text"
                class="form-input mono"
                placeholder="0 8 * * *"
              />
            </div>
            <div v-else-if="editorForm.trigger_type === 'interval'" class="form-row">
              <label class="form-label">
                间隔秒数 * <span class="form-hint">（>= 60，例如 3600 = 每小时）</span>
              </label>
              <input
                v-model.number="editorForm.interval_seconds"
                type="number"
                min="60"
                step="60"
                class="form-input"
              />
            </div>
            <div v-else class="form-row">
              <label class="form-label">
                事件类型 *
                <span class="form-hint"
                  >（例如 "data_ready"、"user_login"，调用 /workflow-timers/events 触发）</span
                >
              </label>
              <input
                v-model="editorForm.event_type"
                type="text"
                class="form-input"
                placeholder="data_ready"
              />
            </div>
            <div class="form-row">
              <label class="form-label">
                Payload Overrides (JSON)
                <span class="form-hint">（可选，覆盖默认 WorkflowSubmitRequest 字段）</span>
              </label>
              <textarea
                v-model="editorForm.payload_overrides_json"
                class="form-input mono textarea"
                rows="5"
                placeholder="{}"
              ></textarea>
            </div>
            <div class="form-row">
              <label class="form-label">
                <input v-model="editorForm.enabled" type="checkbox" />
                立即启用
              </label>
            </div>
          </div>
          <div v-if="editorError" class="dialog-error">❌ {{ editorError }}</div>
          <div class="dialog-actions">
            <button class="dialog-btn cancel" type="button" @click="showEditor = false">
              取消
            </button>
            <button
              class="dialog-btn primary"
              type="button"
              :disabled="editorSaving"
              @click="saveEditor"
            >
              {{ editorSaving ? '保存中...' : '保存' }}
            </button>
          </div>
        </div>
      </div>

      <!-- 删除确认 -->
      <div v-if="confirmDeleteId" class="dialog-overlay" @click.self="confirmDeleteId = null">
        <div class="dialog">
          <h3 class="dialog-title">确认删除</h3>
          <p class="dialog-text">确定要删除定时器 "{{ confirmDeleteId }}" 吗？此操作无法撤销。</p>
          <div class="dialog-actions">
            <button class="dialog-btn cancel" type="button" @click="confirmDeleteId = null">
              取消
            </button>
            <button class="dialog-btn danger" type="button" @click="confirmDelete">删除</button>
          </div>
        </div>
      </div>

      <!-- 事件发射对话框 -->
      <div v-if="showEventDialog" class="dialog-overlay" @click.self="showEventDialog = false">
        <div class="dialog">
          <h3 class="dialog-title">发射事件</h3>
          <p class="dialog-text">
            发射外部事件，将触发所有 event 类型且 event_type 匹配的已启用定时器。
          </p>
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
              <label class="form-label">
                Payload (JSON)
                <span class="form-hint">（可选，将作为 event_payload 注入工作流 parameters）</span>
              </label>
              <textarea
                v-model="eventForm.payload_json"
                class="form-input mono textarea"
                rows="4"
                placeholder="{}"
              ></textarea>
            </div>
          </div>
          <div v-if="eventResult" class="dialog-info">
            匹配 {{ eventResult.matched }} 个，触发 {{ eventResult.fired }} 个，失败
            {{ eventResult.failed }} 个。
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
  background: rgba(4, 10, 18, 0.5);
}

.timer-embedded {
  display: flex;
  flex: 1;
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
  background: rgba(8, 17, 31, 0.98);
  border-left: 1px solid rgba(136, 192, 255, 0.14);
  box-shadow: -12px 0 36px rgba(1, 8, 16, 0.32);
}

.timer-panel--embedded {
  width: 100%;
  max-width: none;
  height: 100%;
  border-left: none;
  box-shadow: none;
  background: transparent;
}

.panel-header {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  padding: 0.72rem 0.82rem;
  border-bottom: 1px solid rgba(136, 192, 255, 0.1);
  color: #e8f3fc;
  font-size: 0.78rem;
  font-weight: 600;
}

.header-icon {
  font-size: 0.88rem;
  color: #5ad5ff;
}
.header-title {
  flex: 1;
}

.header-actions {
  display: flex;
  gap: 0.32rem;
  align-items: center;
}

.header-btn {
  padding: 0.32rem 0.62rem;
  border: 1px solid rgba(90, 213, 255, 0.3);
  border-radius: 0.4rem;
  background: rgba(10, 132, 255, 0.1);
  color: #5ad5ff;
  cursor: pointer;
  font: inherit;
  font-size: 0.6rem;
}

.header-btn:hover:not(:disabled) {
  background: rgba(10, 132, 255, 0.22);
}

.header-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.header-btn.primary {
  background: rgba(10, 132, 255, 0.24);
  font-weight: 600;
}

.close-btn {
  width: 1.4rem;
  height: 1.4rem;
  border: none;
  border-radius: 0.4rem;
  background: transparent;
  color: #6e8ba0;
  cursor: pointer;
  font-size: 0.7rem;
}

.close-btn:hover {
  background: rgba(136, 192, 255, 0.1);
  color: #d8e6f5;
}

.panel-body {
  flex: 1;
  overflow-y: auto;
  padding: 0.7rem 0.82rem;
}

.filter-row {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-bottom: 0.6rem;
}

.filter-label {
  font-size: 0.62rem;
  color: #b8cce0;
  flex: none;
}

.filter-select {
  flex: 1;
  padding: 0.32rem 0.5rem;
  border: 1px solid rgba(136, 192, 255, 0.2);
  border-radius: 0.32rem;
  background: rgba(8, 17, 31, 0.6);
  color: #e8f3fc;
  font: inherit;
  font-size: 0.62rem;
}

.refresh-btn {
  padding: 0.32rem 0.62rem;
  border: 1px solid rgba(90, 213, 255, 0.3);
  border-radius: 0.32rem;
  background: rgba(10, 132, 255, 0.1);
  color: #5ad5ff;
  cursor: pointer;
  font: inherit;
  font-size: 0.6rem;
  flex: none;
}

.refresh-btn:hover:not(:disabled) {
  background: rgba(10, 132, 255, 0.22);
}

.error-banner {
  padding: 0.4rem 0.55rem;
  margin-bottom: 0.6rem;
  border: 1px solid rgba(255, 100, 100, 0.3);
  border-radius: 0.4rem;
  background: rgba(90, 20, 20, 0.25);
  color: #ffb0b0;
  font-size: 0.6rem;
}

.info-banner {
  padding: 0.4rem 0.55rem;
  margin-bottom: 0.6rem;
  border: 1px solid rgba(90, 213, 255, 0.25);
  border-radius: 0.4rem;
  background: rgba(10, 132, 255, 0.1);
  color: #5ad5ff;
  font-size: 0.6rem;
}

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.4rem;
  padding: 3rem 1rem;
  color: #5a7080;
  font-size: 0.68rem;
}

.empty-icon {
  font-size: 1.6rem;
  opacity: 0.6;
}

.empty-hint {
  font-size: 0.58rem;
  color: #4a5a70;
}

.timer-list {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.timer-card {
  padding: 0.55rem 0.62rem;
  border: 1px solid rgba(136, 192, 255, 0.12);
  border-radius: 0.5rem;
  background: rgba(16, 32, 54, 0.6);
  display: flex;
  flex-direction: column;
  gap: 0.45rem;
}

.timer-card.disabled {
  opacity: 0.55;
  background: rgba(16, 32, 54, 0.3);
}

.card-title-row {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  margin-bottom: 0.32rem;
}

.timer-name {
  font-size: 0.7rem;
  font-weight: 600;
  color: #e8f3fc;
}

.type-badge {
  padding: 0.12rem 0.4rem;
  border-radius: 0.32rem;
  font-size: 0.54rem;
  font-weight: 600;
}

.badge-cron {
  background: rgba(126, 224, 168, 0.16);
  color: #a0e8c0;
}
.badge-interval {
  background: rgba(90, 213, 255, 0.16);
  color: #5ad5ff;
}
.badge-event {
  background: rgba(255, 180, 90, 0.16);
  color: #ffd9a8;
}

.disabled-badge {
  padding: 0.12rem 0.4rem;
  border-radius: 0.32rem;
  background: rgba(110, 139, 160, 0.2);
  color: #8aa8bf;
  font-size: 0.54rem;
}

.error-badge {
  padding: 0.12rem 0.4rem;
  border-radius: 0.32rem;
  background: rgba(255, 100, 100, 0.16);
  color: #ffb0b0;
  font-size: 0.54rem;
  cursor: help;
}

.card-meta {
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
}

.meta-row {
  display: flex;
  gap: 0.4rem;
  font-size: 0.6rem;
  line-height: 1.4;
}

.meta-label {
  color: #6e8ba0;
  flex: none;
  width: 4.5rem;
}

.meta-value {
  color: #b8cce0;
  word-break: break-all;
}

.mono {
  font-family: ui-monospace, 'Cascadia Code', Consolas, monospace;
}

.card-actions {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  padding-top: 0.32rem;
  border-top: 1px solid rgba(136, 192, 255, 0.06);
}

.toggle-switch {
  width: 1.6rem;
  height: 0.9rem;
  border-radius: 0.45rem;
  border: none;
  background: rgba(110, 139, 160, 0.3);
  position: relative;
  cursor: pointer;
  flex: none;
  transition: background 0.18s;
  padding: 0;
}

.toggle-switch.on {
  background: rgba(10, 132, 255, 0.5);
}

.toggle-knob {
  position: absolute;
  top: 0.1rem;
  left: 0.1rem;
  width: 0.7rem;
  height: 0.7rem;
  border-radius: 50%;
  background: #e8f3fc;
  transition: transform 0.18s;
}

.toggle-switch.on .toggle-knob {
  transform: translateX(0.7rem);
}

.action-btn {
  padding: 0.28rem 0.55rem;
  border: 1px solid rgba(136, 192, 255, 0.2);
  border-radius: 0.32rem;
  background: rgba(16, 32, 54, 0.6);
  color: #b8cce0;
  cursor: pointer;
  font: inherit;
  font-size: 0.58rem;
}

.action-btn:hover:not(:disabled) {
  background: rgba(136, 192, 255, 0.1);
  color: #d8e6f5;
}

.action-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.action-btn.primary {
  border-color: rgba(90, 213, 255, 0.4);
  background: rgba(10, 132, 255, 0.18);
  color: #5ad5ff;
}

.action-btn.danger {
  border-color: rgba(255, 100, 100, 0.3);
  color: #ffb0b0;
}

.action-btn.danger:hover:not(:disabled) {
  background: rgba(255, 100, 100, 0.12);
}

/* ── 对话框 ── */
.dialog-overlay {
  position: fixed;
  inset: 0;
  z-index: 999;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(4, 10, 18, 0.6);
}

.dialog {
  width: 28rem;
  max-width: 92vw;
  max-height: 88vh;
  overflow-y: auto;
  padding: 0.82rem;
  border: 1px solid rgba(136, 192, 255, 0.2);
  border-radius: 0.62rem;
  background: rgba(12, 22, 38, 0.98);
  color: #e8f3fc;
}

.dialog-title {
  margin: 0 0 0.62rem;
  font-size: 0.76rem;
  color: #e8f3fc;
}

.dialog-text {
  margin: 0 0 0.62rem;
  font-size: 0.6rem;
  color: #8aa8bf;
  line-height: 1.5;
}

.dialog-form {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.form-row {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.form-label {
  font-size: 0.62rem;
  color: #b8cce0;
  display: flex;
  align-items: center;
  gap: 0.32rem;
}

.form-hint {
  font-size: 0.54rem;
  color: #6e8ba0;
  font-weight: normal;
}

.form-input {
  padding: 0.4rem 0.5rem;
  border: 1px solid rgba(136, 192, 255, 0.2);
  border-radius: 0.32rem;
  background: rgba(8, 17, 31, 0.6);
  color: #e8f3fc;
  font: inherit;
  font-size: 0.62rem;
}

.form-input:focus {
  outline: none;
  border-color: rgba(90, 213, 255, 0.5);
}

.textarea {
  resize: vertical;
  min-height: 4rem;
}

.radio-group {
  display: flex;
  gap: 0.82rem;
}

.radio-label {
  display: flex;
  align-items: center;
  gap: 0.32rem;
  font-size: 0.62rem;
  color: #b8cce0;
  cursor: pointer;
}

.dialog-error {
  margin-top: 0.5rem;
  padding: 0.4rem 0.55rem;
  border: 1px solid rgba(255, 100, 100, 0.3);
  border-radius: 0.32rem;
  background: rgba(90, 20, 20, 0.25);
  color: #ffb0b0;
  font-size: 0.58rem;
}

.dialog-info {
  margin-top: 0.5rem;
  padding: 0.4rem 0.55rem;
  border: 1px solid rgba(90, 213, 255, 0.25);
  border-radius: 0.32rem;
  background: rgba(10, 132, 255, 0.12);
  color: #5ad5ff;
  font-size: 0.58rem;
}

.dialog-actions {
  display: flex;
  justify-content: flex-end;
  gap: 0.4rem;
  margin-top: 0.72rem;
}

.dialog-btn {
  padding: 0.4rem 0.82rem;
  border: 1px solid rgba(136, 192, 255, 0.2);
  border-radius: 0.4rem;
  background: rgba(16, 32, 54, 0.6);
  color: #b8cce0;
  cursor: pointer;
  font: inherit;
  font-size: 0.62rem;
}

.dialog-btn:hover:not(:disabled) {
  background: rgba(136, 192, 255, 0.1);
}

.dialog-btn.primary {
  border-color: rgba(90, 213, 255, 0.4);
  background: rgba(10, 132, 255, 0.22);
  color: #5ad5ff;
}

.dialog-btn.danger {
  border-color: rgba(255, 100, 100, 0.3);
  color: #ffb0b0;
}

.dialog-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
</style>
