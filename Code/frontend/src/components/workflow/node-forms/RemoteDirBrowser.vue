<script setup lang="ts">
/**
 * RemoteDirBrowser.vue
 *
 * 远程目录浏览对话框：调用 GET /api/remote/list 浏览远程目录，
 * 双击进入子目录，"确定"回选当前路径。
 *
 * Props: visible / server / initialPath
 * Emits: close / select(path)
 */
import { ref, watch } from 'vue'
import { requestJson } from '../../../services/_http'

interface RemoteItem {
  name: string
  isDir: boolean
  size: number
}

interface RemoteListResponse {
  server: string
  path: string
  items: RemoteItem[]
}

const props = defineProps<{
  visible: boolean
  server: string
  initialPath: string
}>()

const emit = defineEmits<{
  close: []
  select: [path: string]
}>()

const currentPath = ref('/')
const items = ref<RemoteItem[]>([])
const loading = ref(false)
const errorMsg = ref('')
const selectedName = ref('')

function normalizePath(p: string): string {
  if (!p) return '/'
  let s = p.trim()
  if (!s.startsWith('/')) s = '/' + s
  s = s.replace(/\/+/g, '/')
  if (s.length > 1 && s.endsWith('/')) s = s.slice(0, -1)
  return s || '/'
}

async function loadDir(path: string) {
  if (!props.server) {
    errorMsg.value = '未指定服务器'
    return
  }
  loading.value = true
  errorMsg.value = ''
  const target = normalizePath(path)
  try {
    const data = await requestJson<RemoteListResponse>(
      `/api/remote/list?server=${encodeURIComponent(props.server)}&path=${encodeURIComponent(target)}`,
      { silent: true, timeoutMs: 20000 },
    )
    currentPath.value = normalizePath(data.path || target)
    // 目录在前、文件在后，各自字母序
    items.value = [...(data.items ?? [])].sort((a, b) => {
      if (a.isDir !== b.isDir) return a.isDir ? -1 : 1
      return a.name.localeCompare(b.name)
    })
    selectedName.value = ''
  } catch (err) {
    errorMsg.value = err instanceof Error ? err.message : String(err)
    items.value = []
  } finally {
    loading.value = false
  }
}

function enterDir(item: RemoteItem) {
  if (!item.isDir) return
  const base = currentPath.value.replace(/\/$/, '')
  loadDir(`${base}/${item.name}`)
}

function goUp() {
  const parts = currentPath.value.replace(/\/$/, '').split('/').filter(Boolean)
  parts.pop()
  loadDir('/' + parts.join('/'))
}

function onItemClick(item: RemoteItem) {
  selectedName.value = item.name
}

function onItemDblClick(item: RemoteItem) {
  if (item.isDir) enterDir(item)
  else selectedName.value = item.name
}

function confirm() {
  emit('select', currentPath.value)
  emit('close')
}

function formatSize(size: number): string {
  if (!size) return ''
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  if (size < 1024 * 1024 * 1024) return `${(size / 1024 / 1024).toFixed(1)} MB`
  return `${(size / 1024 / 1024 / 1024).toFixed(2)} GB`
}

watch(
  () => props.visible,
  (v) => {
    if (v) loadDir(props.initialPath || '/')
  },
  { immediate: true },
)
</script>

<template>
  <Teleport to="body">
    <div v-if="visible" class="remote-browser-overlay" @click.self="emit('close')">
      <div class="remote-browser-dialog" role="dialog" aria-modal="true">
        <div class="dialog-header">
          <span class="dialog-title">远程目录浏览 · {{ server || '—' }}</span>
          <button type="button" class="dialog-close" aria-label="关闭" @click="emit('close')">
            ×
          </button>
        </div>

        <div class="dialog-pathbar">
          <button
            type="button"
            class="path-btn"
            :disabled="currentPath === '/'"
            title="返回上级"
            aria-label="返回上级"
            @click="goUp"
          >
            ↑
          </button>
          <span class="path-current" :title="currentPath">{{ currentPath }}</span>
          <button
            type="button"
            class="path-btn"
            title="刷新"
            aria-label="刷新"
            @click="loadDir(currentPath)"
          >
            ↻
          </button>
        </div>

        <div class="dialog-body">
          <div v-if="loading" class="dialog-state">加载中…</div>
          <div v-else-if="errorMsg" class="dialog-state error">{{ errorMsg }}</div>
          <div v-else-if="!items.length" class="dialog-state">空目录</div>
          <ul v-else class="dir-list">
            <li
              v-for="item in items"
              :key="item.name"
              class="dir-item"
              :class="{ dir: item.isDir, selected: selectedName === item.name }"
              :title="
                item.isDir ? `进入目录 ${item.name}` : `${item.name} (${formatSize(item.size)})`
              "
              @click="onItemClick(item)"
              @dblclick="onItemDblClick(item)"
            >
              <span class="item-icon" :class="{ dir: item.isDir }">{{
                item.isDir ? '▸' : '·'
              }}</span>
              <span class="item-name">{{ item.name }}</span>
              <span v-if="!item.isDir" class="item-size">{{ formatSize(item.size) }}</span>
            </li>
          </ul>
        </div>

        <div class="dialog-footer">
          <span class="footer-hint">双击目录进入，单击选中</span>
          <div class="footer-actions">
            <button type="button" class="dialog-btn" @click="emit('close')">取消</button>
            <button type="button" class="dialog-btn primary" @click="confirm">确定</button>
          </div>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.remote-browser-overlay {
  position: fixed;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(2, 6, 14, 0.62);
  backdrop-filter: blur(3px);
  z-index: 11000;
}

.remote-browser-dialog {
  display: flex;
  flex-direction: column;
  width: min(540px, 92vw);
  max-height: 78vh;
  border: 1px solid var(--border-accent);
  border-radius: 0.5rem;
  background: var(--surface-1);
  box-shadow: 0 12px 36px rgba(0, 0, 0, 0.55);
  color: #c4d6e8;
  overflow: hidden;
}

.dialog-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.5rem 0.62rem;
  border-bottom: 1px solid rgba(136, 192, 255, 0.12);
}

.dialog-title {
  font-size: var(--font-size-caption);
  font-weight: 600;
  color: var(--text-primary);
}

.dialog-close {
  width: 1.2rem;
  height: 1.2rem;
  display: flex;
  align-items: center;
  justify-content: center;
  border: none;
  border-radius: 0.28rem;
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
  font-size: 0.9rem;
  line-height: 1;
}

.dialog-close:hover {
  background: rgba(255, 138, 138, 0.16);
  color: #ff8a8a;
}

.dialog-pathbar {
  display: flex;
  align-items: center;
  gap: 0.32rem;
  padding: 0.4rem 0.62rem;
  border-bottom: 1px solid var(--border-subtle);
  background: rgba(4, 12, 23, 0.4);
}

.path-btn {
  flex: none;
  width: 1.4rem;
  height: 1.4rem;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 1px solid rgba(136, 192, 255, 0.18);
  border-radius: 0.32rem;
  background: rgba(10, 132, 255, 0.08);
  color: var(--text-muted);
  cursor: pointer;
  font-size: var(--font-size-caption);
}

.path-btn:hover:not(:disabled) {
  background: rgba(10, 132, 255, 0.2);
  color: var(--accent);
}

.path-btn:disabled {
  opacity: 0.4;
  cursor: default;
}

.path-current {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: var(--font-size-caption);
  font-family: 'Consolas', 'Monaco', monospace;
  color: var(--accent);
}

.dialog-body {
  flex: 1;
  overflow-y: auto;
  padding: 0.32rem 0.42rem;
}

.dialog-state {
  padding: 1.4rem 0.62rem;
  text-align: center;
  font-size: var(--font-size-caption);
  color: var(--text-faint);
}

.dialog-state.error {
  color: #ff8a8a;
}

.dir-list {
  margin: 0;
  padding: 0;
  list-style: none;
}

.dir-item {
  display: flex;
  align-items: center;
  gap: 0.36rem;
  padding: 0.3rem 0.42rem;
  border-radius: 0.3rem;
  font-size: var(--font-size-caption);
  color: var(--text-primary);
  cursor: pointer;
  user-select: none;
}

.dir-item:hover {
  background: rgba(10, 132, 255, 0.14);
}

.dir-item.selected {
  background: rgba(90, 213, 255, 0.2);
}

.dir-item.dir .item-name {
  color: var(--success);
  font-weight: 500;
}

.item-icon {
  flex: none;
  width: 0.8rem;
  text-align: center;
  color: var(--text-faint);
  font-size: var(--font-size-caption);
}

.item-icon.dir {
  color: var(--accent);
}

.item-name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.item-size {
  flex: none;
  font-size: var(--font-size-caption);
  color: var(--text-disabled);
  font-family: 'Consolas', 'Monaco', monospace;
}

.dialog-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.42rem;
  padding: 0.42rem 0.62rem;
  border-top: 1px solid rgba(136, 192, 255, 0.12);
  background: rgba(4, 12, 23, 0.4);
}

.footer-hint {
  font-size: var(--font-size-caption);
  color: var(--text-disabled);
}

.footer-actions {
  display: flex;
  gap: 0.32rem;
}

.dialog-btn {
  padding: 0.3rem 0.72rem;
  border: 1px solid rgba(136, 192, 255, 0.22);
  border-radius: 0.32rem;
  background: transparent;
  color: #c4d6e8;
  font: inherit;
  font-size: var(--font-size-caption);
  cursor: pointer;
  transition: all 0.16s ease;
}

.dialog-btn:hover {
  background: rgba(10, 132, 255, 0.16);
  color: var(--text-primary);
}

.dialog-btn.primary {
  border-color: rgba(90, 213, 255, 0.5);
  background: rgba(90, 213, 255, 0.2);
  color: var(--accent);
}

.dialog-btn.primary:hover {
  background: rgba(90, 213, 255, 0.32);
  color: var(--success);
}
</style>
