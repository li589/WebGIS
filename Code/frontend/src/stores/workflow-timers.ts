/**
 * 工作流定时器 Pinia Store
 *
 * Phase 4: 管理工作流定时器列表与生命周期操作。
 */
import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import {
  fetchWorkflowTimers,
  fetchWorkflowTimer,
  createWorkflowTimer,
  updateWorkflowTimer,
  deleteWorkflowTimer,
  runWorkflowTimer,
  emitWorkflowEvent,
  manualTickTimers,
  type WorkflowTimer,
  type CreateTimerPayload,
  type UpdateTimerPayload,
  type EmitEventPayload,
  type ManualTriggerResponse,
  type EmitEventResponse,
  type TickStats,
} from '../services/workflow-timer-api'

export const useWorkflowTimersStore = defineStore('workflow-timers', () => {
  // ─── 状态 ────────────────────────────────────────────────────────────────
  const timers = ref<WorkflowTimer[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)
  const lastActionTimerId = ref<string | null>(null)

  // ─── 计算属性 ─────────────────────────────────────────────────────────────
  const enabledCount = computed(() => timers.value.filter((t) => t.enabled).length)
  const cronTimers = computed(() => timers.value.filter((t) => t.trigger_type === 'cron'))
  const intervalTimers = computed(() => timers.value.filter((t) => t.trigger_type === 'interval'))
  const eventTimers = computed(() => timers.value.filter((t) => t.trigger_type === 'event'))

  function timersForWorkflow(workflowId: string): WorkflowTimer[] {
    return timers.value.filter((t) => t.workflow_id === workflowId)
  }

  // ─── 动作 ────────────────────────────────────────────────────────────────
  async function loadTimers(workflowId?: string) {
    loading.value = true
    error.value = null
    try {
      timers.value = await fetchWorkflowTimers(workflowId)
    } catch (err) {
      console.error('[workflow-timers] Failed to load timers:', err)
      error.value = err instanceof Error ? err.message : String(err)
    } finally {
      loading.value = false
    }
  }

  async function loadTimer(timerId: string): Promise<WorkflowTimer | null> {
    try {
      const timer = await fetchWorkflowTimer(timerId)
      // 替换列表中同 id 项
      const idx = timers.value.findIndex((t) => t.timer_id === timerId)
      if (idx >= 0) {
        timers.value.splice(idx, 1, timer)
      } else {
        timers.value.push(timer)
      }
      return timer
    } catch (err) {
      console.error('[workflow-timers] Failed to load timer:', err)
      error.value = err instanceof Error ? err.message : String(err)
      return null
    }
  }

  async function createTimer(payload: CreateTimerPayload): Promise<WorkflowTimer> {
    const created = await createWorkflowTimer(payload)
    timers.value.push(created)
    return created
  }

  async function updateTimer(timerId: string, payload: UpdateTimerPayload): Promise<WorkflowTimer> {
    const updated = await updateWorkflowTimer(timerId, payload)
    const idx = timers.value.findIndex((t) => t.timer_id === timerId)
    if (idx >= 0) {
      timers.value.splice(idx, 1, updated)
    }
    return updated
  }

  async function removeTimer(timerId: string): Promise<void> {
    await deleteWorkflowTimer(timerId)
    const idx = timers.value.findIndex((t) => t.timer_id === timerId)
    if (idx >= 0) {
      timers.value.splice(idx, 1)
    }
  }

  async function toggleEnabled(timer: WorkflowTimer): Promise<void> {
    lastActionTimerId.value = timer.timer_id
    try {
      await updateTimer(timer.timer_id, { enabled: !timer.enabled })
    } finally {
      lastActionTimerId.value = null
    }
  }

  async function runTimer(timerId: string): Promise<ManualTriggerResponse> {
    lastActionTimerId.value = timerId
    try {
      const result = await runWorkflowTimer(timerId)
      // 重新加载该定时器以获取最新 last_run_id
      await loadTimer(timerId)
      // 将触发的 run 注册到 layers store 进行状态跟踪
      if (result.run_id) {
        try {
          const { useLayersStore } = await import('./layers')
          const layersStore = useLayersStore()
          const catalogIdHint = timers.value.find((t) => t.timer_id === timerId)?.payload_overrides
            ?.layer_id
          void layersStore.registerExternalWorkflowRun(result.run_id, catalogIdHint)
        } catch (err) {
          console.warn('[workflow-timers] registerExternalWorkflowRun failed:', err)
        }
      }
      return result
    } finally {
      lastActionTimerId.value = null
    }
  }

  async function emitEvent(payload: EmitEventPayload): Promise<EmitEventResponse> {
    const result = await emitWorkflowEvent(payload)
    // 重新加载所有定时器以反映 last_fired_at 变化
    await loadTimers()
    return result
  }

  async function tick(): Promise<TickStats> {
    const stats = await manualTickTimers()
    await loadTimers()
    return stats
  }

  return {
    // 状态
    timers,
    loading,
    error,
    lastActionTimerId,
    // 计算属性
    enabledCount,
    cronTimers,
    intervalTimers,
    eventTimers,
    // 方法
    timersForWorkflow,
    loadTimers,
    loadTimer,
    createTimer,
    updateTimer,
    removeTimer,
    toggleEnabled,
    runTimer,
    emitEvent,
    tick,
  }
})
