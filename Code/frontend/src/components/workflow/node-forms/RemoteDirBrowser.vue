<script setup lang="ts">
/**
 * RemoteDirBrowser.vue
 *
 * 远程目录浏览对话框：调用 POST /config/remote-storage/{id}/browse 浏览
 * 远程存储 profile 目录，双击进入子目录，"确定"回选当前路径。
 *
 * Props: visible / profileId / initialPath
 * Emits: close / select(path)
 */
import { ref, watch } from 'vue'
import { browseRemoteStorage } from '../../../services/settings-api'

interface RemoteItem {
  name: string
  is_dir: boolean
  size: number | null
}

const props = defineProps<{
  visible: boolean
  profileId: string
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
  if (!props.profileId) {
    errorMsg.value = '未指定远程存储 profile'
    return
  }
  loading.value = true
  errorMsg.value = ''
  const target = normalizePath(path)
  try {
    const data = await browseRemoteStorage(props.profileId, target)
    currentPath.value = normalizePath(data.path || target)
    // 目录在前、文件在后，各自字母序
    items.value = (data.items ?? [])
      .map((i) => ({ name: i.name, is_dir: !!i.is_dir, size: i.size ?? null }))
      .sort((a, b) => {
        if (a.is_dir !== b.is_dir) return a.is_dir ? -1 : 1
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
  if (!item.is_dir) return
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
  if (item.is_dir) enterDir(item)
  else selectedName.value = item.name
}

function confirm() {
  emit('select', currentPath.value)
  emit('close')
}

function formatSize(size: number | null): string {
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
          <span class="dialog-title">远程目录浏览 · {{ profileId || '—' }}</span>
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
              :class="{ dir: item.is_dir, selected: selectedName === item.name }"
              :title="
                item.is_dir ? `进入目录 ${item.name}` : `${item.name} (${formatSize(item.size)})`
              "
              @click="onItemClick(item)"
              @dblclick="onItemDblClick(item)"
            >
              <span class="item-icon" :class="{ dir: item.is_dir }">{{
                item.is_dir ? '▸' : '·'
              }}</span>
              <span class="item-name">{{ item.name }}</span>
              <span v-if="!item.is_dir" class="item-size">{{ formatSize(item.size) }}</span>
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
  background: var(--surface-1);
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
  color: var(--text-secondary);
  overflow: hidden;
}

.dialog-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.5rem 0.62rem;
  border-bottom: 1px solid var(--border-default);
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
  color: var(--danger);
}

.dialog-pathbar {
  display: flex;
  align-items: center;
  gap: 0.32rem;
  padding: 0.4rem 0.62rem;
  border-bottom: 1px solid var(--border-subtle);
  background: var(--surface-sunken);
}

.path-btn {
  flex: none;
  width: 1.4rem;
  height: 1.4rem;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 1px solid var(--border-default);
  border-radius: 0.32rem;
  background: var(--accent-surface);
  color: var(--text-muted);
  cursor: pointer;
  font-size: var(--font-size-caption);
}

.path-btn:hover:not(:disabled) {
  background: var(--accent-border);
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
  font-family: var(--font-mono);
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
  color: var(--danger);
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
  background: var(--accent-surface);
}

.dir-item.selected {
  background: var(--accent-border);
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
  font-family: var(--font-mono);
}

.dialog-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.42rem;
  padding: 0.42rem 0.62rem;
  border-top: 1px solid var(--border-default);
  background: var(--surface-sunken);
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
  border: 1px solid var(--border-strong);
  border-radius: 0.32rem;
  background: transparent;
  color: var(--text-secondary);
  font: inherit;
  font-size: var(--font-size-caption);
  cursor: pointer;
  transition:
    background-color var(--motion-interactive-duration) var(--motion-interactive-ease),
    border-color var(--motion-interactive-duration) var(--motion-interactive-ease),
    color var(--motion-interactive-duration) var(--motion-interactive-ease),
    box-shadow var(--motion-interactive-duration) var(--motion-interactive-ease),
    opacity var(--motion-interactive-duration) var(--motion-interactive-ease),
    transform var(--motion-interactive-duration) var(--motion-interactive-ease);
}

.dialog-btn:hover {
  background: var(--accent-surface);
  color: var(--text-primary);
}

.dialog-btn.primary {
  border-color: var(--border-strong);
  background: var(--accent-border);
  color: var(--accent);
}

.dialog-btn.primary:hover {
  background: var(--border-accent);
  color: var(--success);
}
</style>
