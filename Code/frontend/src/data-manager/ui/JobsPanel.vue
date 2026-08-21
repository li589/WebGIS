<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { cancelImportJob, listImportJobs } from '../core/api'
import { dataJobs, openDataWorkspace } from '../core/workspace-store'
import { DATA_COPY } from '../../ui-copy'
import AppSelect from '../../components/ui/AppSelect.vue'

const loading = ref(false)
const error = ref('')
const items = ref<
  Array<{
    job_id: string
    kind: string
    status: string
    progress: number
    message?: string
    error?: string | null
    created_at?: string | number
  }>
>([])

const statusFilter = ref('all')

const filteredItems = computed(() => {
  if (statusFilter.value === 'all') return items.value
  if (statusFilter.value === 'active')
    return items.value.filter((j) => j.status === 'queued' || j.status === 'running')
  return items.value.filter((j) => j.status === statusFilter.value)
})

let timer: ReturnType<typeof setTimeout> | null = null

const POLL_ACTIVE_MS = 2000
const POLL_IDLE_MS = 15000

async function refresh() {
  loading.value = true
  error.value = ''
  try {
    const res = await listImportJobs(30)
    items.value = res.items || []
    dataJobs.value = items.value.map((j) => ({
      id: j.job_id,
      kind: j.kind,
      status: j.status,
      progress: Number(j.progress) || 0,
      message: j.message,
    }))
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}

async function cancel(jobId: string) {
  try {
    await cancelImportJob(jobId)
    await refresh()
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  }
}

function statusLabel(s: string) {
  const map: Record<string, string> = {
    queued: '排队',
    running: '运行中',
    succeeded: '成功',
    failed: '失败',
    cancelled: '已取消',
  }
  return map[s] || s
}

function hasActiveJobs(): boolean {
  return items.value.some((j) => j.status === 'queued' || j.status === 'running')
}

function scheduleNext() {
  if (timer) clearTimeout(timer)
  if (disposed) return
  const delay = hasActiveJobs() ? POLL_ACTIVE_MS : POLL_IDLE_MS
  timer = setTimeout(async () => {
    // 卸载可能发生在 refresh 在飞期间：clearTimeout 对已消费的句柄无效，
    // 回调入口必须再查 disposed，否则轮询链在组件销毁后自续（U-3）
    if (disposed) return
    await refresh()
    if (disposed) return
    scheduleNext()
  }, delay)
}

onMounted(() => {
  void refresh().then(() => scheduleNext())
})

let disposed = false

onUnmounted(() => {
  disposed = true
  if (timer) clearTimeout(timer)
})
</script>

<template>
  <div class="jobs-panel">
    <div class="jobs-toolbar">
      <span class="hint">{{ DATA_COPY.jobsHint }}</span>
      <label class="filter-label">
        筛选
        <AppSelect
          v-model="statusFilter"
          :options="[
            { label: '全部', value: 'all' },
            { label: '进行中', value: 'active' },
            { label: '排队', value: 'queued' },
            { label: '运行中', value: 'running' },
            { label: '成功', value: 'succeeded' },
            { label: '失败', value: 'failed' },
            { label: '已取消', value: 'cancelled' },
          ]"
        />
      </label>
      <button class="ghost-btn" type="button" :disabled="loading" @click="refresh">
        {{ DATA_COPY.jobsRefresh }}
      </button>
    </div>
    <p v-if="error" class="err">{{ error }}</p>
    <p v-else-if="!filteredItems.length" class="empty">
      {{ statusFilter === 'all' ? DATA_COPY.jobsEmpty : '无匹配作业' }}
    </p>
    <ul v-else class="job-list">
      <li v-for="j in filteredItems" :key="j.job_id" class="job-row">
        <div class="job-main">
          <span class="kind">{{ j.kind }}</span>
          <span class="id" :title="j.job_id">{{ j.job_id }}</span>
          <span class="status" :data-status="j.status">{{ statusLabel(j.status) }}</span>
        </div>
        <div class="job-progress">
          <div class="bar">
            <i :style="{ width: `${Math.round((Number(j.progress) || 0) * 100)}%` }" />
          </div>
          <span class="pct">{{ Math.round((Number(j.progress) || 0) * 100) }}%</span>
        </div>
        <p v-if="j.message || j.error" class="msg">{{ j.error || j.message }}</p>
        <div class="job-actions">
          <button
            v-if="j.status === 'queued' || j.status === 'running'"
            class="ghost-btn"
            type="button"
            @click="cancel(j.job_id)"
          >
            {{ DATA_COPY.jobsCancel }}
          </button>
          <button
            v-if="j.status === 'succeeded' && (j.kind === 'vector' || j.kind === 'document_commit')"
            class="ghost-btn"
            type="button"
            @click="openDataWorkspace({ tab: 'attributes' })"
          >
            {{ DATA_COPY.openAttributes }}
          </button>
        </div>
      </li>
    </ul>
  </div>
</template>

<style scoped>
.jobs-panel {
  display: flex;
  flex-direction: column;
  gap: 0.55rem;
  min-height: 0;
  height: 100%;
}
.jobs-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
  flex-wrap: wrap;
}
.filter-label {
  display: flex;
  flex-direction: column;
  gap: 0.14rem;
  font-size: var(--font-size-caption);
  color: var(--text-muted);
}
.hint {
  font-size: var(--font-size-caption);
  color: var(--text-muted);
}
.ghost-btn {
  border: 1px solid var(--border-strong);
  border-radius: 0.38rem;
  padding: 0.28rem 0.5rem;
  background: var(--surface-raised);
  color: var(--text-primary);
  font: inherit;
  font-size: var(--font-size-caption);
  cursor: pointer;
}
.job-list {
  list-style: none;
  margin: 0;
  padding: 0;
  overflow: auto;
  display: flex;
  flex-direction: column;
  gap: 0.45rem;
}
.job-row {
  border: 1px solid var(--border-default);
  border-radius: 0.42rem;
  padding: 0.45rem 0.55rem;
  background: var(--surface-raised);
}
.job-main {
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem;
  align-items: center;
  font-size: var(--font-size-caption);
}
.kind {
  color: var(--accent);
  font-weight: 600;
}
.id {
  color: var(--text-faint);
  max-width: 12rem;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.status[data-status='succeeded'] {
  color: var(--success);
}
.status[data-status='failed'] {
  color: var(--danger);
}
.status[data-status='running'],
.status[data-status='queued'] {
  color: var(--warning);
}
.job-progress {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  margin-top: 0.35rem;
}
.bar {
  flex: 1;
  height: 0.28rem;
  border-radius: 999px;
  background: var(--border-default);
  overflow: hidden;
}
.bar i {
  display: block;
  height: 100%;
  background: linear-gradient(90deg, var(--accent), var(--accent));
}
.pct {
  font-size: var(--font-size-caption);
  color: var(--text-muted);
  min-width: 2.2rem;
  text-align: right;
}
.msg {
  margin: 0.28rem 0 0;
  font-size: var(--font-size-caption);
  color: var(--text-secondary);
}
.job-actions {
  margin-top: 0.35rem;
  display: flex;
  gap: 0.35rem;
}
.empty,
.err {
  margin: 0;
  font-size: var(--font-size-caption);
}
.err {
  color: var(--danger);
}
.empty {
  color: var(--text-muted);
}
</style>
