<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import { cancelImportJob, listImportJobs } from '../core/api'
import { dataJobs, openDataWorkspace } from '../core/workspace-store'
import { DATA_COPY } from '../../ui-copy'

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

let timer: ReturnType<typeof setInterval> | null = null

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

onMounted(() => {
  void refresh()
  timer = setInterval(() => {
    void refresh()
  }, 2500)
})

onUnmounted(() => {
  if (timer) clearInterval(timer)
})
</script>

<template>
  <div class="jobs-panel">
    <div class="jobs-toolbar">
      <span class="hint">{{ DATA_COPY.jobsHint }}</span>
      <button class="ghost-btn" type="button" :disabled="loading" @click="refresh">
        {{ DATA_COPY.jobsRefresh }}
      </button>
    </div>
    <p v-if="error" class="err">{{ error }}</p>
    <p v-else-if="!items.length" class="empty">{{ DATA_COPY.jobsEmpty }}</p>
    <ul v-else class="job-list">
      <li v-for="j in items" :key="j.job_id" class="job-row">
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
}
.hint {
  font-size: 0.58rem;
  color: #8aa0b4;
}
.ghost-btn {
  border: 1px solid rgba(136, 192, 255, 0.2);
  border-radius: 0.38rem;
  padding: 0.28rem 0.5rem;
  background: rgba(4, 12, 23, 0.55);
  color: #c5d8ea;
  font: inherit;
  font-size: 0.58rem;
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
  border: 1px solid rgba(136, 192, 255, 0.12);
  border-radius: 0.42rem;
  padding: 0.45rem 0.55rem;
  background: rgba(4, 12, 23, 0.45);
}
.job-main {
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem;
  align-items: center;
  font-size: 0.6rem;
}
.kind {
  color: #5ad5ff;
  font-weight: 600;
}
.id {
  color: #6a8094;
  max-width: 12rem;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.status[data-status='succeeded'] {
  color: #7dffb3;
}
.status[data-status='failed'] {
  color: #ffb0b0;
}
.status[data-status='running'],
.status[data-status='queued'] {
  color: #ffd166;
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
  background: rgba(136, 192, 255, 0.12);
  overflow: hidden;
}
.bar i {
  display: block;
  height: 100%;
  background: linear-gradient(90deg, #0a84ff, #5ad5ff);
}
.pct {
  font-size: 0.52rem;
  color: #8aa0b4;
  min-width: 2.2rem;
  text-align: right;
}
.msg {
  margin: 0.28rem 0 0;
  font-size: 0.55rem;
  color: #9fb6cc;
}
.job-actions {
  margin-top: 0.35rem;
  display: flex;
  gap: 0.35rem;
}
.empty,
.err {
  margin: 0;
  font-size: 0.62rem;
}
.err {
  color: #ffb0b0;
}
.empty {
  color: #8aa0b4;
}
</style>
