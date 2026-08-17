<script setup lang="ts">
/**
 * PortalSearchDialog — 门户在线检索（当前 CMR 能力）。
 *
 * 结果条目可「添加为远程数据源」（kind=portal），remote_path 存 granule 相对路径或 collection 目录。
 */

import { ref, watch } from 'vue'
import type { PortalCatalogEntry, PortalSearchResultItem } from '../../../types/api-reexports'
import { searchPortal, upsertRemoteSource } from '../../../services/settings-api'

const props = defineProps<{
  visible: boolean
  portal: PortalCatalogEntry | null
}>()

const emit = defineEmits<{
  close: []
  added: [remoteSourceId: string]
}>()

const query = ref('')
const searching = ref(false)
const errorMsg = ref('')
const items = ref<PortalSearchResultItem[]>([])
const count = ref(0)
const adding = ref('')
const addMsg = ref('')

async function runSearch() {
  if (!props.portal || !query.value.trim()) return
  searching.value = true
  errorMsg.value = ''
  addMsg.value = ''
  try {
    const res = await searchPortal(props.portal.portal_id, query.value.trim())
    items.value = res.items ?? []
    count.value = res.count ?? 0
    if (!items.value.length) errorMsg.value = '无结果（检查关键词，如短名 MOD09GQ 或关键词）'
  } catch (e) {
    errorMsg.value = (e as Error).message
    items.value = []
  } finally {
    searching.value = false
  }
}

async function addAsSource(item: PortalSearchResultItem) {
  if (!props.portal) return
  const granule = item.producer_granule_id || item.granule_id || item.title
  const alias = `${props.portal.portal_id}-${granule}`.replace(/[^\w.-]+/g, '-').slice(0, 80)
  adding.value = alias
  addMsg.value = ''
  try {
    await upsertRemoteSource(alias, {
      kind: 'portal',
      ref_id: props.portal.portal_id,
      remote_path: granule,
      display_name: item.title || granule,
      cache_policy: 'standard',
    })
    addMsg.value = `已添加远程数据源「${alias}」`
    emit('added', alias)
  } catch (e) {
    addMsg.value = (e as Error).message
  } finally {
    adding.value = ''
  }
}

watch(
  () => props.visible,
  (v) => {
    if (v) {
      query.value = ''
      items.value = []
      errorMsg.value = ''
      addMsg.value = ''
    }
  },
)
</script>

<template>
  <Teleport to="body">
    <div v-if="visible && portal" class="ps-overlay" @click.self="emit('close')">
      <div class="ps-dialog" role="dialog" aria-modal="true">
        <div class="ps-header">
          <span class="ps-title">在线检索 · {{ portal.name }}</span>
          <button type="button" class="ps-close" aria-label="关闭" @click="emit('close')">×</button>
        </div>

        <div class="ps-searchbar">
          <input
            v-model="query"
            placeholder="granule 关键词或短名（如 MOD09GQ、SMAP L4）"
            @keyup.enter="runSearch"
          />
          <button type="button" class="btn primary" :disabled="searching" @click="runSearch">
            {{ searching ? '检索中…' : '检索' }}
          </button>
        </div>

        <div class="ps-body">
          <div v-if="errorMsg" class="ps-state error">{{ errorMsg }}</div>
          <div v-else-if="!items.length" class="ps-state">输入关键词后检索</div>
          <div v-else class="ps-meta">共 {{ count }} 条，展示前 {{ items.length }} 条</div>
          <div class="ps-list">
            <div v-for="(row, i) in items" :key="i" class="ps-row">
              <div class="ps-row-main">
                <span class="ps-row-title">{{ row.title || row.granule_id }}</span>
                <code class="ps-row-id">{{ row.producer_granule_id || row.granule_id }}</code>
              </div>
              <div class="ps-row-meta">
                <span v-if="row.time_start"
                  >{{ row.time_start }}{{ row.time_end ? ` ~ ${row.time_end}` : '' }}</span
                >
                <span v-if="row.size_bytes"
                  >· {{ (row.size_bytes / 1024 / 1024).toFixed(1) }} MB</span
                >
              </div>
              <div class="ps-row-actions">
                <a
                  v-if="row.data_link"
                  :href="row.data_link"
                  target="_blank"
                  rel="noopener noreferrer"
                  class="ps-link"
                >
                  数据链接
                </a>
                <button
                  type="button"
                  class="btn"
                  :disabled="adding !== ''"
                  @click="addAsSource(row)"
                >
                  添加为远程数据源
                </button>
              </div>
            </div>
          </div>
        </div>

        <p v-if="addMsg" class="ps-addmsg">{{ addMsg }}</p>
      </div>
    </div>
  </Teleport>
</template>

<style scoped src="../settings-form.css"></style>
<style scoped>
.ps-overlay {
  position: fixed;
  inset: 0;
  z-index: 1100;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--surface-raised);
}
.ps-dialog {
  width: min(44rem, 92vw);
  max-height: 86vh;
  display: flex;
  flex-direction: column;
  border-radius: 0.6rem;
  border: 1px solid var(--border-default);
  background: var(--surface-2);
  box-shadow: 0 18px 48px rgba(1, 8, 16, 0.4);
  overflow: hidden;
}
.ps-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
  padding: 0.55rem 0.72rem;
  border-bottom: 1px solid var(--border-subtle);
}
.ps-title {
  color: var(--text-strong);
  font-size: var(--font-size-caption);
  font-weight: 600;
}
.ps-close {
  width: 1.5rem;
  height: 1.5rem;
  border: none;
  border-radius: 0.4rem;
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
  font-size: 1rem;
}
.ps-close:hover {
  background: var(--border-subtle);
}
.ps-searchbar {
  display: flex;
  gap: 0.4rem;
  padding: 0.5rem 0.72rem;
  border-bottom: 1px solid var(--border-subtle);
}
.ps-searchbar input {
  flex: 1;
  border: 1px solid var(--border-default);
  border-radius: 0.36rem;
  background: var(--surface-1);
  color: var(--text-strong);
  font-size: var(--font-size-caption);
  padding: 0.32rem 0.44rem;
}
.ps-body {
  flex: 1;
  min-height: 10rem;
  overflow-y: auto;
  padding: 0.4rem 0.72rem;
}
.ps-state {
  padding: 1.4rem 0;
  text-align: center;
  color: var(--text-disabled);
  font-size: var(--font-size-caption);
}
.ps-state.error {
  color: var(--danger);
}
.ps-meta {
  color: var(--text-disabled);
  font-size: var(--font-size-caption);
  margin-bottom: 0.35rem;
}
.ps-list {
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
}
.ps-row {
  display: flex;
  flex-direction: column;
  gap: 0.24rem;
  padding: 0.42rem 0.5rem;
  border-radius: 0.4rem;
  border: 1px solid var(--border-subtle);
  background: var(--surface-sunken);
}
.ps-row-main {
  display: flex;
  align-items: baseline;
  gap: 0.45rem;
  flex-wrap: wrap;
}
.ps-row-title {
  color: var(--text-strong);
  font-size: var(--font-size-caption);
  font-weight: 600;
}
.ps-row-id {
  color: var(--accent-strong);
  font-size: var(--font-size-caption);
}
.ps-row-meta {
  color: var(--text-disabled);
  font-size: var(--font-size-caption);
}
.ps-row-actions {
  display: flex;
  gap: 0.4rem;
  align-items: center;
}
.ps-link {
  color: var(--accent);
  font-size: var(--font-size-caption);
}
.ps-addmsg {
  margin: 0;
  padding: 0.4rem 0.72rem;
  border-top: 1px solid var(--border-subtle);
  color: var(--accent-warm);
  font-size: var(--font-size-caption);
}
</style>
