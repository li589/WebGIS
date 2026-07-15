<script setup lang="ts">
import { computed, ref } from 'vue'
import { useLogStore, type LogCategory } from '../../stores/log'

const emit = defineEmits<{
  close: []
}>()

const logStore = useLogStore()

type FilterTag = 'all' | LogCategory
const activeFilter = ref<FilterTag>('all')
const expandedId = ref<string | null>(null)

const filteredEntries = computed(() => {
  const entries = logStore.entries
  if (activeFilter.value === 'all') return entries
  return entries.filter((e) => e.category === activeFilter.value)
})

// 倒序显示（最新在上）
const displayEntries = computed(() => [...filteredEntries.value].reverse())

const operationCount = computed(() => logStore.entries.filter((e) => e.category === 'operation').length)
const workflowCount = computed(() => logStore.entries.filter((e) => e.category === 'workflow').length)

function formatTime(ts: number): string {
  const d = new Date(ts)
  const h = String(d.getHours()).padStart(2, '0')
  const m = String(d.getMinutes()).padStart(2, '0')
  const s = String(d.getSeconds()).padStart(2, '0')
  return `${h}:${m}:${s}`
}

function toggleExpand(id: string) {
  expandedId.value = expandedId.value === id ? null : id
}

function handleClearAll() {
  logStore.clearLogs()
}

function handleClearCategory(cat: LogCategory) {
  logStore.clearCategory(cat)
}
</script>

<template>
  <div class="log-panel-overlay" @click.self="emit('close')">
    <div class="log-panel">
      <div class="panel-header">
        <span class="panel-icon" aria-hidden="true">📋</span>
        <span>系统日志</span>
        <span class="entry-count">{{ logStore.entries.length }}</span>
        <button class="close-btn" @click="emit('close')" title="关闭">
          <span aria-hidden="true">✕</span>
        </button>
      </div>

      <!-- 筛选标签 -->
      <div class="filter-tabs">
        <button
          class="filter-tab"
          :class="{ active: activeFilter === 'all' }"
          @click="activeFilter = 'all'"
        >
          全部 <span class="tab-count">{{ logStore.entries.length }}</span>
        </button>
        <button
          class="filter-tab"
          :class="{ active: activeFilter === 'operation' }"
          @click="activeFilter = 'operation'"
        >
          操作日志 <span class="tab-count">{{ operationCount }}</span>
        </button>
        <button
          class="filter-tab"
          :class="{ active: activeFilter === 'workflow' }"
          @click="activeFilter = 'workflow'"
        >
          工作流日志 <span class="tab-count">{{ workflowCount }}</span>
        </button>
        <button class="clear-btn" @click="handleClearAll" title="清空所有日志">
          清空
        </button>
      </div>

      <!-- 日志列表 -->
      <div class="log-list">
        <div v-if="displayEntries.length === 0" class="empty-hint">
          暂无日志记录
        </div>
        <div
          v-for="entry in displayEntries"
          :key="entry.id"
          class="log-entry"
          :class="`cat-${entry.category}`"
          @click="toggleExpand(entry.id)"
        >
          <div class="entry-row">
            <span class="entry-time">{{ formatTime(entry.timestamp) }}</span>
            <span class="entry-cat" :class="`cat-badge-${entry.category}`">
              {{ entry.category === 'operation' ? '操作' : '工作流' }}
            </span>
            <span class="entry-message">{{ entry.message }}</span>
            <span v-if="entry.details" class="entry-expand" aria-hidden="true">
              {{ expandedId === entry.id ? '▾' : '▸' }}
            </span>
          </div>
          <div v-if="entry.details && expandedId === entry.id" class="entry-details">
            {{ entry.details }}
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.log-panel-overlay {
  position: fixed;
  inset: 0;
  z-index: 998;
  display: flex;
  justify-content: flex-end;
  background: rgba(4, 10, 18, 0.4);
}

.log-panel {
  width: 24rem;
  max-width: 90vw;
  height: 100vh;
  display: flex;
  flex-direction: column;
  background: rgba(8, 17, 31, 0.98);
  border-left: 1px solid rgba(136, 192, 255, 0.14);
  box-shadow: -12px 0 36px rgba(1, 8, 16, 0.32);
}

.panel-header {
  display: flex;
  align-items: center;
  gap: 0.38rem;
  padding: 0.72rem 0.82rem;
  border-bottom: 1px solid rgba(136, 192, 255, 0.1);
  color: #e8f3fc;
  font-size: 0.74rem;
  font-weight: 600;
  flex: none;
}

.panel-icon { font-size: 0.82rem; color: #5ad5ff; }

.entry-count {
  padding: 0.1rem 0.4rem;
  border-radius: 999px;
  background: rgba(10, 132, 255, 0.2);
  color: #5ad5ff;
  font-size: 0.56rem;
  font-weight: 600;
}

.close-btn {
  margin-left: auto;
  width: 1.4rem;
  height: 1.4rem;
  border: none;
  border-radius: 0.5rem;
  background: transparent;
  color: #6e8ba0;
  cursor: pointer;
  font-size: 0.7rem;
}
.close-btn:hover { background: rgba(136, 192, 255, 0.1); color: #d8e6f5; }

.filter-tabs {
  display: flex;
  gap: 0.22rem;
  padding: 0.52rem 0.82rem;
  border-bottom: 1px solid rgba(136, 192, 255, 0.08);
  flex: none;
  flex-wrap: wrap;
  align-items: center;
}

.filter-tab {
  display: inline-flex;
  align-items: center;
  gap: 0.22rem;
  padding: 0.26rem 0.52rem;
  border: 1px solid rgba(136, 192, 255, 0.1);
  border-radius: 999px;
  background: transparent;
  color: #8aa8bf;
  cursor: pointer;
  font: inherit;
  font-size: 0.58rem;
  transition: all 0.16s ease;
}

.filter-tab:hover { background: rgba(136, 192, 255, 0.08); color: #d8e6f5; }

.filter-tab.active {
  border-color: rgba(90, 213, 255, 0.36);
  background: rgba(10, 132, 255, 0.18);
  color: #5ad5ff;
}

.tab-count { font-size: 0.52rem; opacity: 0.7; }

.clear-btn {
  margin-left: auto;
  padding: 0.26rem 0.52rem;
  border: 1px solid rgba(255, 100, 100, 0.18);
  border-radius: 999px;
  background: transparent;
  color: #ff9999;
  cursor: pointer;
  font: inherit;
  font-size: 0.58rem;
}
.clear-btn:hover { background: rgba(255, 77, 77, 0.12); }

.log-list {
  flex: 1;
  overflow-y: auto;
  padding: 0.32rem 0;
}

.empty-hint {
  padding: 2rem 1rem;
  text-align: center;
  color: #5a7080;
  font-size: 0.62rem;
}

.log-entry {
  padding: 0.36rem 0.82rem;
  border-bottom: 1px solid rgba(136, 192, 255, 0.04);
  cursor: pointer;
  transition: background 0.12s ease;
}

.log-entry:hover { background: rgba(136, 192, 255, 0.04); }

.entry-row {
  display: flex;
  align-items: center;
  gap: 0.36rem;
}

.entry-time {
  color: #5a7080;
  font-size: 0.54rem;
  font-variant-numeric: tabular-nums;
  flex: none;
  min-width: 3.4rem;
}

.entry-cat {
  flex: none;
  padding: 0.08rem 0.32rem;
  border-radius: 0.26rem;
  font-size: 0.5rem;
  font-weight: 600;
}

.cat-badge-operation {
  background: rgba(103, 212, 255, 0.14);
  color: #67d4ff;
}

.cat-badge-workflow {
  background: rgba(201, 163, 255, 0.14);
  color: #c9a3ff;
}

.entry-message {
  flex: 1;
  min-width: 0;
  color: #d8e6f5;
  font-size: 0.6rem;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.entry-expand {
  color: #5a7080;
  font-size: 0.58rem;
  flex: none;
}

.entry-details {
  margin-top: 0.22rem;
  padding: 0.32rem 0.42rem;
  border-radius: 0.36rem;
  background: rgba(4, 12, 23, 0.6);
  color: #9fb6cc;
  font-size: 0.56rem;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-all;
}
</style>
