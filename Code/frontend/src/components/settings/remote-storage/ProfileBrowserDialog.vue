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
  /**
   * 选择器模式（2026-08-25 数据源管理改版 P1）：嵌入「添加数据源」融合
   * 对话框作目录选择器——隐藏内嵌「添加为远程数据源」区，改为
   * 「选择当前目录」按钮回传 path-chosen。
   */
  picker?: boolean
}>()

const emit = defineEmits<{
  close: []
  added: [remoteSourceId: string]
  pathChosen: [path: string]
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
// 搜索范围：true=当前目录子树（start_path=currentPath），false=全库（start_path=/）
const searchScopeCurrent = ref(true)
const searchTruncated = ref(false)
const searchFailedDirs = ref(0)

type SortKey = 'name' | 'mtime' | 'size'
const sortBy = ref<SortKey>('name')
const sortDesc = ref(false)

function compareEntries(a: RemoteEntryItem, b: RemoteEntryItem): number {
  let cmp: number
  if (sortBy.value === 'name') {
    cmp = (a.name ?? '').localeCompare(b.name ?? '')
  } else if (sortBy.value === 'mtime') {
    cmp = (a.mtime ?? 0) - (b.mtime ?? 0)
  } else {
    cmp = (a.size ?? 0) - (b.size ?? 0)
  }
  if (cmp === 0) cmp = (a.name ?? '').localeCompare(b.name ?? '')
  return sortDesc.value ? -cmp : cmp
}

const sortedItems = computed(() => {
  const dirsFirst = (x: RemoteEntryItem, y: RemoteEntryItem) =>
    (x.is_dir ?? false) === (y.is_dir ?? false) ? 0 : x.is_dir ? -1 : 1
  return [...items.value].sort((a, b) => dirsFirst(a, b) || compareEntries(a, b))
})
const sortedSearchResults = computed(() => [...searchResults.value].sort(compareEntries))

// 竞态防护：导航/新搜索递增序号，晚到的旧响应直接丢弃
let loadSeq = 0
let searchSeq = 0

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
  const seq = ++loadSeq
  loading.value = true
  errorMsg.value = ''
  addMsg.value = ''
  // 导航即退出搜索视图：清掉旧结果，避免冻结显示已失效的搜索列表
  searchResults.value = []
  searchTruncated.value = false
  searchFailedDirs.value = 0
  const target = normalizePath(path)
  try {
    const res = await browseRemoteStorage(props.profile.profile_id, target)
    if (seq !== loadSeq) return
    currentPath.value = normalizePath(res.path || target)
    viaPrimary.value = res.via !== 'alt'
    viaLabel.value = res.via
    items.value = res.items ?? []
  } catch (e) {
    if (seq !== loadSeq) return
    errorMsg.value = (e as Error).message
    items.value = []
  } finally {
    if (seq === loadSeq) loading.value = false
  }
}

async function runSearch() {
  if (!props.profile || !searchQuery.value.trim()) return
  const seq = ++searchSeq
  searching.value = true
  errorMsg.value = ''
  const startPath = searchScopeCurrent.value ? currentPath.value : '/'
  try {
    const res = await searchRemoteStorage(
      props.profile.profile_id,
      searchQuery.value.trim(),
      500,
      startPath,
    )
    if (seq !== searchSeq) return
    searchResults.value = res.items ?? []
    searchTruncated.value = res.truncated ?? false
    searchFailedDirs.value = res.failed_dirs ?? 0
    viaPrimary.value = res.via !== 'alt'
    if (!searchResults.value.length) {
      errorMsg.value =
        startPath === '/'
          ? '无匹配结果（递归深度限制 3 层）'
          : `无匹配结果（${startPath} 子树内，深度限制 3 层）`
    }
  } catch (e) {
    if (seq !== searchSeq) return
    errorMsg.value = (e as Error).message
    searchResults.value = []
  } finally {
    if (seq === searchSeq) searching.value = false
  }
}

/** 点击搜索结果：目录进入该目录；文件定位到其父目录（路径回带到浏览上下文）。 */
function pickSearchResult(row: RemoteEntryItem) {
  const p = normalizePath(row.path || row.name)
  const target = row.is_dir ? p : p.replace(/\/[^/]*$/, '') || '/'
  void loadDir(target)
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
      access_mode: 'legacy',
      archived: false,
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

function formatMtime(mtime: number | null | undefined): string {
  if (mtime == null || mtime <= 0) return ''
  const d = new Date(mtime * 1000)
  if (Number.isNaN(d.getTime())) return ''
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

watch(
  () => props.visible,
  (v) => {
    if (v && props.profile) {
      searchQuery.value = ''
      searchResults.value = []
      searchTruncated.value = false
      searchFailedDirs.value = 0
      searchScopeCurrent.value = true
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
          <label class="fb-scope" title="勾选后在当前目录子树内搜索，取消则从根目录全库搜索">
            <input v-model="searchScopeCurrent" type="checkbox" />
            当前目录内
          </label>
          <input
            v-model="searchQuery"
            :placeholder="
              searchScopeCurrent
                ? `在 ${currentPath} 子树内搜索（递归 3 层）`
                : '全库搜索（递归 3 层 / 500 条）'
            "
            @keyup.enter="runSearch"
          />
          <button type="button" class="fb-btn" :disabled="searching" @click="runSearch">
            {{ searching ? '搜索中…' : '搜索' }}
          </button>
        </div>

        <div class="fb-toolbar">
          <span class="fb-toolbar-label">排序</span>
          <select v-model="sortBy" class="fb-select" title="排序字段（目录浏览固定目录优先）">
            <option value="name">名称</option>
            <option value="mtime">修改时间</option>
            <option value="size">大小</option>
          </select>
          <button
            type="button"
            class="fb-mini-btn"
            :title="sortDesc ? '当前：降序，点击切换升序' : '当前：升序，点击切换降序'"
            @click="sortDesc = !sortDesc"
          >
            {{ sortDesc ? '↓' : '↑' }}
          </button>
        </div>

        <div class="fb-body">
          <div v-if="loading" class="fb-state">加载中…</div>
          <div v-else-if="errorMsg" class="fb-state error">{{ errorMsg }}</div>
          <template v-else>
            <div v-if="searchResults.length" class="fb-list fb-search-list">
              <div class="fb-search-head">
                <span>
                  搜索结果 {{ searchResults.length }} 条（点击行定位到所在目录）
                  <em v-if="searchTruncated" class="fb-hint warn">已达 500 条上限，结果被截断</em>
                  <em v-if="searchFailedDirs > 0" class="fb-hint warn">
                    {{ searchFailedDirs }} 个子目录列举失败，结果不完整
                  </em>
                </span>
                <button
                  type="button"
                  class="fb-mini-btn"
                  title="返回目录浏览"
                  @click="loadDir(currentPath)"
                >
                  ✕
                </button>
              </div>
              <div
                v-for="(row, i) in sortedSearchResults"
                :key="`s${i}`"
                class="fb-row clickable"
                :title="row.is_dir ? '进入该目录' : '定位到所在目录'"
                @click="pickSearchResult(row)"
              >
                <span class="fb-name" :title="row.path || row.name">
                  {{ row.is_dir ? '📁' : '📄' }} {{ row.name }}
                </span>
                <code class="fb-meta">{{ row.path }}</code>
                <span class="fb-mtime">{{ formatMtime(row.mtime) }}</span>
                <span class="fb-size">{{ formatSize(row.size) }}</span>
              </div>
            </div>
            <div v-else-if="!items.length" class="fb-state">空目录</div>
            <div v-else class="fb-list">
              <div
                v-for="row in sortedItems"
                :key="row.name"
                class="fb-row"
                :class="{ dir: row.is_dir, clickable: row.is_dir }"
                :title="row.is_dir ? '双击进入' : ''"
                @dblclick="enterDir(row)"
              >
                <span class="fb-name">{{ row.is_dir ? '📁' : '📄' }} {{ row.name }}</span>
                <span class="fb-mtime">{{ formatMtime(row.mtime) }}</span>
                <span class="fb-size">{{ formatSize(row.size) }}</span>
              </div>
            </div>
          </template>
        </div>

        <div class="fb-footer">
          <!-- picker 模式（融合对话框内嵌选择器）：选择当前目录回传 -->
          <div v-if="picker" class="fb-add">
            <span class="fb-add-label">当前目录：{{ currentPath }}</span>
            <button
              type="button"
              class="fb-btn primary"
              @click="emit('pathChosen', currentPath)"
            >
              选择此目录
            </button>
          </div>
          <div v-else class="fb-add">
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
  align-items: center;
  gap: 0.4rem;
  padding: 0.42rem 0.72rem;
  border-bottom: 1px solid var(--border-subtle);
}
.fb-scope {
  flex: none;
  display: inline-flex;
  align-items: center;
  gap: 0.24rem;
  color: var(--text-muted);
  font-size: var(--font-size-caption);
  cursor: pointer;
  user-select: none;
}
.fb-toolbar {
  display: flex;
  align-items: center;
  gap: 0.32rem;
  padding: 0.32rem 0.72rem;
  border-bottom: 1px solid var(--border-subtle);
}
.fb-toolbar-label,
.fb-hint {
  color: var(--text-disabled);
  font-size: var(--font-size-caption);
  font-style: normal;
}
.fb-hint.warn {
  color: var(--accent-warm);
  margin-left: 0.4rem;
}
.fb-select {
  border: 1px solid var(--border-default);
  border-radius: 0.32rem;
  background: var(--surface-1);
  color: var(--text-primary);
  font-size: var(--font-size-caption);
  padding: 0.14rem 0.3rem;
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
.fb-search-list {
  gap: 0.12rem;
}
.fb-search-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.4rem;
  padding: 0.1rem 0.36rem;
  color: var(--text-disabled);
  font-size: var(--font-size-caption);
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
.fb-mtime {
  flex: none;
  min-width: 7.2rem;
  color: var(--text-disabled);
  font-variant-numeric: tabular-nums;
}
.fb-size {
  flex: none;
  min-width: 4.6rem;
  text-align: right;
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
