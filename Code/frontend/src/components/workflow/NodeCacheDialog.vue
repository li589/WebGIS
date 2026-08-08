<script setup lang="ts">
/**
 * 节点产物缓存管理对话框：列出每个算法模块的缓存大小/位置，
 * 支持逐项清理与全部清理（工作流编辑器内入口）。
 */
import { onMounted, ref, watch } from 'vue'
import { cleanupNodeCaches, listNodeCaches, type NodeCacheEntry } from '../../services/runtime-api'

const props = defineProps<{ open: boolean }>()
const emit = defineEmits<{ close: [] }>()

const entries = ref<NodeCacheEntry[]>([])
const totalBytes = ref(0)
const loading = ref(false)
const clearing = ref(false)
const errorMsg = ref<string | null>(null)
const busyName = ref<string | null>(null)

function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let value = bytes
  let unit = 0
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024
    unit += 1
  }
  return `${value.toFixed(value >= 100 ? 0 : 1)} ${units[unit]}`
}

async function refresh() {
  loading.value = true
  errorMsg.value = null
  try {
    const resp = await listNodeCaches()
    entries.value = resp.entries
    totalBytes.value = resp.total_bytes
  } catch (error) {
    errorMsg.value = error instanceof Error ? error.message : '加载节点缓存失败'
  } finally {
    loading.value = false
  }
}

async function clearOne(name: string) {
  busyName.value = name
  errorMsg.value = null
  try {
    await cleanupNodeCaches([name])
    await refresh()
  } catch (error) {
    errorMsg.value = error instanceof Error ? error.message : `清理 ${name} 失败`
  } finally {
    busyName.value = null
  }
}

async function clearAll() {
  if (
    !window.confirm(
      `确认清理全部节点缓存（共 ${formatBytes(totalBytes.value)}）？\n此操作不可恢复，历史 run 产物将删除。`,
    )
  ) {
    return
  }
  clearing.value = true
  errorMsg.value = null
  try {
    await cleanupNodeCaches()
    await refresh()
  } catch (error) {
    errorMsg.value = error instanceof Error ? error.message : '清理失败'
  } finally {
    clearing.value = false
  }
}

watch(
  () => props.open,
  (open) => {
    if (open) void refresh()
  },
)

onMounted(() => {
  if (props.open) void refresh()
})
</script>

<template>
  <Teleport to="body">
    <div v-if="props.open" class="nc-modal-mask" @click.self="emit('close')">
      <div class="nc-modal" role="dialog" aria-label="节点缓存管理">
        <div class="nc-header">
          <span class="nc-title">节点缓存管理</span>
          <button class="nc-close" type="button" aria-label="关闭" @click="emit('close')">×</button>
        </div>

        <div class="nc-summary">
          <span class="nc-summary-item">共 {{ entries.length }} 个模块</span>
          <span class="nc-summary-item">占用 {{ formatBytes(totalBytes) }}</span>
          <button
            class="nc-clear-all"
            type="button"
            :disabled="clearing || entries.length === 0"
            @click="clearAll"
          >
            {{ clearing ? '清理中…' : '清理全部' }}
          </button>
        </div>

        <div v-if="errorMsg" class="nc-error">{{ errorMsg }}</div>
        <div v-if="loading" class="nc-loading">扫描中…</div>

        <div v-else-if="entries.length === 0" class="nc-empty">暂无节点缓存</div>

        <ul v-else class="nc-list">
          <li v-for="entry in entries" :key="entry.name" class="nc-item">
            <div class="nc-item-main">
              <span class="nc-item-name" :title="entry.path">{{ entry.name }}</span>
              <span class="nc-item-size">{{ formatBytes(entry.size_bytes) }}</span>
              <span class="nc-item-files">{{ entry.file_count }} 文件</span>
              <span class="nc-item-path" :title="entry.path">{{ entry.path }}</span>
            </div>
            <button
              class="nc-item-clear"
              type="button"
              :disabled="busyName === entry.name"
              :title="`清理 ${entry.name}`"
              @click="clearOne(entry.name)"
            >
              {{ busyName === entry.name ? '…' : '清理' }}
            </button>
          </li>
        </ul>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.nc-modal-mask {
  position: fixed;
  inset: 0;
  z-index: 1200;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(3, 8, 16, 0.62);
  backdrop-filter: blur(4px);
}

.nc-modal {
  width: min(640px, 92vw);
  max-height: 78vh;
  display: flex;
  flex-direction: column;
  border-radius: 14px;
  border: 1px solid rgba(148, 163, 184, 0.22);
  background: #0c1524;
  color: #dbe7f5;
  box-shadow: 0 24px 48px rgba(0, 0, 0, 0.45);
  overflow: hidden;
}

.nc-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.8rem 1rem;
  border-bottom: 1px solid rgba(148, 163, 184, 0.16);
}

.nc-title {
  font-size: 14px;
  font-weight: 500;
  color: #f1f7ff;
}

.nc-close {
  border: none;
  background: transparent;
  color: #8aa2bd;
  font-size: 18px;
  line-height: 1;
  cursor: pointer;
}

.nc-summary {
  display: flex;
  align-items: center;
  gap: 0.8rem;
  padding: 0.6rem 1rem;
  border-bottom: 1px solid rgba(148, 163, 184, 0.12);
}

.nc-summary-item {
  font-size: 12px;
  color: #8aa2bd;
}

.nc-clear-all {
  margin-left: auto;
  padding: 0.3rem 0.8rem;
  border: 1px solid rgba(226, 75, 74, 0.45);
  border-radius: 6px;
  background: rgba(226, 75, 74, 0.14);
  color: #f7b3b3;
  font-size: 12px;
  cursor: pointer;
}

.nc-clear-all:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.nc-error {
  margin: 0.6rem 1rem;
  padding: 0.5rem 0.7rem;
  border-radius: 6px;
  background: rgba(226, 75, 74, 0.14);
  color: #f7b3b3;
  font-size: 12px;
}

.nc-loading,
.nc-empty {
  padding: 1.6rem 1rem;
  text-align: center;
  font-size: 13px;
  color: #8aa2bd;
}

.nc-list {
  list-style: none;
  margin: 0;
  padding: 0.4rem 0.8rem 0.8rem;
  overflow-y: auto;
}

.nc-item {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  padding: 0.5rem 0.4rem;
  border-bottom: 1px solid rgba(148, 163, 184, 0.08);
}

.nc-item-main {
  flex: 1;
  min-width: 0;
  display: flex;
  align-items: baseline;
  gap: 0.6rem;
}

.nc-item-name {
  font-size: 13px;
  font-weight: 500;
  color: #dbe7f5;
  flex-shrink: 0;
}

.nc-item-size {
  font-size: 12px;
  color: #ffd9a0;
  flex-shrink: 0;
}

.nc-item-files {
  font-size: 11px;
  color: #8aa2bd;
  flex-shrink: 0;
}

.nc-item-path {
  font-size: 11px;
  color: #5f7895;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  direction: rtl;
  text-align: left;
}

.nc-item-clear {
  padding: 0.2rem 0.6rem;
  border: 1px solid rgba(148, 163, 184, 0.25);
  border-radius: 5px;
  background: transparent;
  color: #8aa2bd;
  font-size: 12px;
  cursor: pointer;
  flex-shrink: 0;
}

.nc-item-clear:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}
</style>
