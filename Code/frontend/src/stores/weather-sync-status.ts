/**
 * Open-Meteo sync 运行态（跨设置页 / 工作流状态面板共享）。
 * 规则 2B：sync 进行中时，本地无数据层应显示「等待重试」而非「失败」。
 */
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import {
  getWeatherSyncOverview,
  getWeatherSyncStatus,
  triggerWeatherSync,
  type WeatherSyncOverview,
} from '../services/runtime-api'

export const useWeatherSyncStatusStore = defineStore('weatherSyncStatus', () => {
  const overview = ref<WeatherSyncOverview | null>(null)
  const taskId = ref<string | null>(null)
  const taskState = ref<string | null>(null)
  const lastError = ref<string | null>(null)
  let pollTimer: ReturnType<typeof setInterval> | null = null

  const syncInProgress = computed(() => {
    if (overview.value?.sync_in_progress) return true
    const s = (taskState.value || '').toUpperCase()
    return s === 'PENDING' || s === 'STARTED' || s === 'RETRY'
  })

  const coverageError = computed(() => overview.value?.coverage_error ?? null)
  const modelEmpty = computed(
    () => coverageError.value === 'model_empty' || coverageError.value === 'local_unreachable',
  )

  function stopPolling() {
    if (pollTimer !== null) {
      clearInterval(pollTimer)
      pollTimer = null
    }
  }

  async function refreshOverview() {
    try {
      overview.value = await getWeatherSyncOverview()
      lastError.value = null
    } catch (err) {
      lastError.value = (err as Error)?.message ?? 'overview failed'
    }
  }

  async function pollTaskOnce() {
    if (!taskId.value) return
    try {
      const status = await getWeatherSyncStatus(taskId.value)
      taskState.value = status.state
      const done = ['SUCCESS', 'FAILURE', 'REVOKED'].includes((status.state || '').toUpperCase())
      if (done) {
        stopPolling()
        taskId.value = null
        await refreshOverview()
      }
    } catch {
      /* keep previous state */
    }
  }

  function startPolling(id: string) {
    taskId.value = id
    taskState.value = 'PENDING'
    stopPolling()
    void pollTaskOnce()
    pollTimer = setInterval(() => {
      void pollTaskOnce()
    }, 3000)
  }

  async function triggerSync(options?: { domains?: string }) {
    const res = await triggerWeatherSync(options)
    if (res.task_id) startPolling(res.task_id)
    await refreshOverview()
    return res
  }

  const syncServiceAvailable = computed(() => {
    if (!overview.value) return true
    if (typeof overview.value.sync_service_available === 'boolean') {
      return overview.value.sync_service_available
    }
    return Boolean(overview.value.docker_cli_available && overview.value.compose_file_exists)
  })

  return {
    overview,
    taskId,
    taskState,
    lastError,
    syncInProgress,
    syncServiceAvailable,
    coverageError,
    modelEmpty,
    refreshOverview,
    triggerSync,
    startPolling,
    stopPolling,
  }
})
