<script setup lang="ts">
/**
 * ProfileBrowserDialog — Profile 感知的远程目录浏览/搜索对话框。
 *
 * 走 POST /config/remote-storage/{id}/browse|search（后端处理双路径回退）。
 * 双击进入子目录；搜索仅对 searchable 协议开放。
 * 「添加为远程数据源」把当前目录写入 remote-source registry（别名默认 {profile_id}-{basename}）。
 */

import { computed, ref, watch } from 'vue'
import type { RemoteEntryItem, RemoteStorageProfile } from '../../../types/api-reexports'
import {
  browseRemoteStorage,
  searchRemoteStorage,
  upsertRemoteSource,
} from '../../../services/settings-api'
import { PROTOCOL_META } from './protocols'

const props = defineProps<{
  visible: boolean
  profile: RemoteStorageProfile | null
  initialPath?: string
}>()

const emit = defineEmits<{
  close: []
  added: [remoteSourceId: string]
}>()

const currentPath = ref('/')
const items = ref<RemoteEntryItem[]>([])
const loading = ref(false)
const errorMsg = ref('')
const viaLabel = ref('primary')
const viaPrimary = ref(true)

const searchQuery = ref('')
const searching = ref(false)
const searchResults = ref<RemoteEntryItem[]>([])

const addBusy = ref(false)
const addMsg = ref('')
const addAlias = ref('')

const meta = computed(() =>
  props.profile ? PROTOCOL_META[props.profile.protocol as keyof typeof PROTOCOL_META] : undefined,
)
const searchable = computed(() => Boolean(meta.value?.searchable))

function normalizePath(p: string): string {
  if (!p) return '/'
  let s = p.trim()
  if (!s.startsWith('/')) s = `/${s}`
  s = s.replace(/\/+/g, '/')
  if (s.length > 1 && s.endsWith('/')) s = s.slice(0, -1)
  return s || '/'
}

async function loadDir(path: string) {
  if (!props.profile) return
  loading.value = true
  errorMsg.value = ''
  addMsg.value = ''
  const target = normalizePath(path)
  try {
    const res = await browseRemoteStorage(props.profile.profile_id, target)
    currentPath.value = normalizePath(res.path || target)
    viaPrimary.value = res.via !== 'alt'
    viaLabel.value = res.via
    items.value = [...(res.items ?? [])].sort((a, b) => {
      if ((a.is_dir ?? false) !== (b.is_dir ?? false)) return a.is_dir ? -1 : 1
      return a.name.localeCompare(b.name)
    })
  } catch (e) {
    errorMsg.value = (e as Error).message
    items.value = []
  } finally {
    loading.value = false
  }
}

async function runSearch() {
  if (!props.profile || !searchQuery.value.trim()) return
  searching.value = true
  errorMsg.value = ''
  try {
    const res = await searchRemoteStorage(props.profile.profile_id, searchQuery.value.trim())
    searchResults.value = res.items ?? []
    viaPrimary.value = res.via !== 'alt'
    if (!searchResults.value.length) errorMsg.value = '无匹配结果（深度限制 3 层）'
  } catch (e) {
    errorMsg.value = (e as Error).message
    searchResults.value = []
  } finally {
    searching.value = false
  }
}

function enterDir(item: RemoteEntryItem) {
  if (!item.is_dir) return
  const base = currentPath.value.replace(/\/$/, '')
  void loadDir(`${base}/${item.name}`)
}

function goUp() {
  const parts = currentPath.value.replace(/\/$/, '').split('/').filter(Boolean)
  parts.pop()
  void loadDir(`/${parts.join('/')}`)
}

function breadcrumbParts(): Array<{ label: string; path: string }> {
  const parts = currentPath.value.replace(/^\//, '').split('/').filter(Boolean)
  const out = [{ label: '/', path: '/' }]
  let acc = ''
  for (const p of parts) {
    acc += `/${p}`
    out.push({ label: p, path: acc })
  }
  return out
}

function suggestAlias(dirPath: string): string {
  const base = dirPath.replace(/\/+$/, '').split('/').filter(Boolean).pop() || 'root'
  return `${props.profile?.profile_id ?? 'src'}-${base}`
}

/** 把当前浏览目录注册为「可访问远程数据源」。 */
async function addCurrentDirAsSource() {
  if (!props.profile) return
  const alias = (addAlias.value || suggestAlias(currentPath.value)).trim()
  if (!alias) {
    addMsg.value = '请填写别名 ID'
    return
  }
  addBusy.value = true
  addMsg.value = ''
  try {
    await upsertRemoteSource(alias, {
      kind: 'storage_profile',
      ref_id: props.profile.profile_id,
      remote_path: currentPath.value,
      display_name: props.profile.display_name || props.profile.profile_id,
      cache_policy: 'standard',
    })
    addMsg.value = `已添加远程数据源「${alias}」`
    addAlias.value = ''
    emit('added', alias)
  } catch (e) {
    addMsg.value = (e as Error).message
  } finally {
    addBusy.value = false
  }
}

function formatSize(size: number | null | undefined): string {
  if (size == null || size <= 0) return ''
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  if (size < 1024 * 1024 * 1024) return `${(size / 1024 / 1024).toFixed(1)} MB`
  return `${(size / 1024 / 1024 / 1024).toFixed(2)} GB`
}

watch(
  () => props.visible,
  (v) => {
    if (v && props.profile) {
      searchQuery.value = ''
      searchResults.value = []
      addMsg.value = ''
      addAlias.value = ''
      void loadDir(props.initialPath || '/')
    }
  },
  { immediate: true },
)
</script>

<template>
  <Teleport to="body">
    <div v-if="visible && profile" class="fb-overlay" @click.self="emit('close')">
      <div class="fb-dialog" role="dialog" aria-modal="true">
        <div class="fb-header">
          <span class="fb-title">
            目录浏览 · {{ profile.display_name || profile.profile_id }}
            <span class="fb-via" :class="{ alt: !viaPrimary }">
              {{ viaPrimary ? '主路径' : '备用路径' }}
            </span>
          </span>
          <button type="button" class="fb-close" aria-label="关闭" @click="emit('close')">×</button>
        </div>

        <div class="fb-pathbar">
          <button
            type="button"
            class="fb-mini-btn"
            :disabled="currentPath === '/'"
            title="返回上级"
            @click="goUp"
          >
            ↑
          </button>
          <nav class="fb-breadcrumb">
            <button
              v-for="seg in breadcrumbParts()"
              :key="seg.path"
              type="button"
              class="fb-crumb"
              @click="loadDir(seg.path)"
            >
              {{ seg.label }}
            </button>
          </nav>
          <button type="button" class="fb-mini-btn" title="刷新" @click="loadDir(currentPath)">
            ↻
          </button>
        </div>

        <div v-if="searchable" class="fb-searchbar">
          <input
            v-model="searchQuery"
            placeholder="按名称搜索（递归，最多 3 层 / 500 条）"
            @keyup.enter="runSearch"
          />
          <button type="button" class="fb-btn" :disabled="searching" @click="runSearch">
            {{ searching ? '搜索中…' : '搜索' }}
          </button>
        </div>

        <div class="fb-body">
          <div v-if="loading" class="fb-state">加载中…</div>
          <div v-else-if="errorMsg" class="fb-state error">{{ errorMsg }}</div>
          <template v-else>
            <div v-if="searchResults.length" class="fb-list">
              <div v-for="(row, i) in searchResults" :key="`s${i}`" class="fb-row">
                <span class="fb-name" :title="row.path || row.name">
                  {{ row.is_dir ? '📁' : '📄' }} {{ row.name }}
                </span>
                <code class="fb-meta">{{ row.path }}</code>
                <span class="fb-size">{{ formatSize(row.size) }}</span>
              </div>
            </div>
            <div v-else-if="!items.length" class="fb-state">空目录</div>
            <div v-else class="fb-list">
              <div
                v-for="row in items"
                :key="row.name"
                class="fb-row"
                :class="{ dir: row.is_dir, clickable: row.is_dir }"
                :title="row.is_dir ? '双击进入' : ''"
                @dblclick="enterDir(row)"
              >
                <span class="fb-name">{{ row.is_dir ? '📁' : '📄' }} {{ row.name }}</span>
                <span class="fb-size">{{ formatSize(row.size) }}</span>
              </div>
            </div>
          </template>
        </div>

        <div class="fb-footer">
          <div class="fb-add">
            <span class="fb-add-label">将当前目录添加为远程数据源：</span>
            <input
              v-model="addAlias"
              class="fb-add-input"
              :placeholder="suggestAlias(currentPath)"
            />
            <button
              type="button"
              class="fb-btn primary"
              :disabled="addBusy"
              @click="addCurrentDirAsSource"
            >
              {{ addBusy ? '添加中…' : '添加' }}
            </button>
          </div>
          <p v-if="addMsg" class="fb-add-msg">{{ addMsg }}</p>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.fb-overlay {
  position: fixed;
  inset: 0;
  z-index: 1100;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--surface-raised);
}
.fb-dialog {
  width: min(46rem, 92vw);
  max-height: 86vh;
  display: flex;
  flex-direction: column;
  border-radius: 0.6rem;
  border: 1px solid var(--border-default);
  background: var(--surface-2);
  box-shadow: 0 18px 48px rgba(1, 8, 16, 0.4);
  overflow: hidden;
}
.fb-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
  padding: 0.55rem 0.72rem;
  border-bottom: 1px solid var(--border-subtle);
}
.fb-title {
  color: var(--text-strong);
  font-size: var(--font-size-caption);
  font-weight: 600;
  display: inline-flex;
  align-items: center;
  gap: 0.45rem;
}
.fb-via {
  padding: 0.08rem 0.34rem;
  border-radius: 0.26rem;
  background: var(--accent-surface);
  color: var(--accent-strong);
  font-weight: 500;
}
.fb-via.alt {
  background: var(--warning-surface);
  color: var(--accent-warm);
}
.fb-close {
  width: 1.5rem;
  height: 1.5rem;
  border: none;
  border-radius: 0.4rem;
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
  font-size: 1rem;
}
.fb-close:hover {
  background: var(--border-subtle);
  color: var(--text-primary);
}
.fb-pathbar {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  padding: 0.42rem 0.72rem;
  border-bottom: 1px solid var(--border-subtle);
}
.fb-mini-btn {
  flex: none;
  width: 1.5rem;
  height: 1.5rem;
  border: 1px solid var(--border-default);
  border-radius: 0.32rem;
  background: var(--surface-1);
  color: var(--text-primary);
  cursor: pointer;
}
.fb-mini-btn:disabled {
  opacity: 0.4;
  cursor: default;
}
.fb-breadcrumb {
  flex: 1;
  display: flex;
  flex-wrap: wrap;
  gap: 0.12rem;
  min-width: 0;
  overflow: hidden;
}
.fb-crumb {
  border: none;
  background: transparent;
  color: var(--accent);
  cursor: pointer;
  font-size: var(--font-size-caption);
  padding: 0.1rem 0.18rem;
  border-radius: 0.24rem;
}
.fb-crumb:hover {
  background: var(--border-subtle);
}
.fb-crumb::after {
  content: '/';
  color: var(--text-disabled);
  margin-left: 0.14rem;
}
.fb-searchbar {
  display: flex;
  gap: 0.4rem;
  padding: 0.42rem 0.72rem;
  border-bottom: 1px solid var(--border-subtle);
}
.fb-searchbar input {
  flex: 1;
  border: 1px solid var(--border-default);
  border-radius: 0.36rem;
  background: var(--surface-1);
  color: var(--text-strong);
  font-size: var(--font-size-caption);
  padding: 0.3rem 0.44rem;
}
.fb-btn {
  border: 1px solid var(--border-strong);
  border-radius: 0.32rem;
  background: var(--surface-2);
  color: var(--text-primary);
  font-size: var(--font-size-caption);
  padding: 0.28rem 0.6rem;
  cursor: pointer;
}
.fb-btn.primary {
  background: var(--accent-surface);
  color: var(--accent-strong);
}
.fb-btn:disabled {
  opacity: 0.5;
  cursor: default;
}
.fb-body {
  flex: 1;
  min-height: 12rem;
  overflow-y: auto;
  padding: 0.4rem 0.72rem;
}
.fb-state {
  padding: 1.6rem 0;
  text-align: center;
  color: var(--text-disabled);
  font-size: var(--font-size-caption);
}
.fb-state.error {
  color: var(--danger);
}
.fb-list {
  display: flex;
  flex-direction: column;
}
.fb-row {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.3rem 0.36rem;
  border-radius: 0.3rem;
  color: var(--text-muted);
  font-size: var(--font-size-caption);
}
.fb-row.clickable:hover {
  background: var(--surface-hover);
}
.fb-name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.fb-meta {
  color: var(--text-disabled);
  font-size: var(--font-size-caption);
  max-width: 40%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.fb-size {
  flex: none;
  color: var(--text-disabled);
}
.fb-footer {
  display: flex;
  flex-direction: column;
  gap: 0.28rem;
  padding: 0.5rem 0.72rem;
  border-top: 1px solid var(--border-subtle);
}
.fb-add {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  flex-wrap: wrap;
}
.fb-add-label {
  color: var(--text-muted);
  font-size: var(--font-size-caption);
}
.fb-add-input {
  width: 12rem;
  border: 1px solid var(--border-default);
  border-radius: 0.36rem;
  background: var(--surface-1);
  color: var(--text-strong);
  font-size: var(--font-size-caption);
  padding: 0.28rem 0.4rem;
}
.fb-add-msg {
  margin: 0;
  color: var(--accent-warm);
  font-size: var(--font-size-caption);
}
</style>
