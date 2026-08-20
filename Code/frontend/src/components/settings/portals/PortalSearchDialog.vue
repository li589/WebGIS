<script setup lang="ts">
/**
 * PortalSearchDialog — 门户在线检索（数据集级，plan 阶段 2 数据集化改造）。
 *
 * 检索结果每行是一个数据集（collection/产品集），点「添加数据集授权」
 * 写入 remote_dataset_grants 白名单——添加后该门户仅授权数据集可在
 * 工作流中访问（未授权数据集将被提交校验拒绝）。
 */

import { ref, watch } from 'vue'
import type { PortalCatalogEntry, PortalSearchDatasetItem } from '../../../types/api-reexports'
import { searchPortal, upsertRemoteDatasetGrant } from '../../../services/settings-api'

const props = defineProps<{
  visible: boolean
  portal: PortalCatalogEntry | null
}>()

const emit = defineEmits<{
  close: []
  added: [grantId: string]
}>()

const query = ref('')
const searching = ref(false)
const errorMsg = ref('')
const items = ref<PortalSearchDatasetItem[]>([])
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
    if (!items.value.length) errorMsg.value = '无结果（检查关键词，如 GLDAS、SMAP L4、Sentinel）'
  } catch (e) {
    errorMsg.value = (e as Error).message
    items.value = []
  } finally {
    searching.value = false
  }
}

async function addGrant(item: PortalSearchDatasetItem) {
  if (!props.portal) return
  const datasetKey = item.dataset_key || item.title
  const grantId = `${props.portal.portal_id}__${datasetKey}`.slice(0, 120)
  adding.value = grantId
  addMsg.value = ''
  try {
    await upsertRemoteDatasetGrant(grantId, {
      portal_id: props.portal.portal_id,
      dataset_key: datasetKey,
      dataset_title: item.title || datasetKey,
      dataset_description: item.description || '',
      provider_kind: item.provider_kind || '',
      time_start: item.time_start || '',
      time_end: item.time_end || '',
      path_prefix: '',
      search_meta: JSON.stringify(item.extra ?? {}),
      enabled: true,
    })
    addMsg.value = `已授权数据集「${datasetKey}」——该门户的未授权数据集将不可在工作流中访问`
    emit('added', grantId)
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
          <span class="ps-title">在线检索（数据集） · {{ portal.name }}</span>
          <button type="button" class="ps-close" aria-label="关闭" @click="emit('close')">×</button>
        </div>

        <div class="ps-searchbar">
          <input
            v-model="query"
            placeholder="数据集关键词（如 GLDAS、SMAP L4、Sentinel-2）"
            @keyup.enter="runSearch"
          />
          <button type="button" class="btn primary" :disabled="searching" @click="runSearch">
            {{ searching ? '检索中…' : '检索' }}
          </button>
        </div>

        <div class="ps-body">
          <div v-if="errorMsg" class="ps-state error">{{ errorMsg }}</div>
          <div v-else-if="!items.length" class="ps-state">输入关键词后检索数据集</div>
          <div v-else class="ps-meta">共 {{ count }} 个数据集，展示前 {{ items.length }} 个</div>
          <div class="ps-list">
            <div v-for="(row, i) in items" :key="i" class="ps-row">
              <div class="ps-row-main">
                <span class="ps-row-title">{{ row.title || row.dataset_key }}</span>
                <code class="ps-row-id">{{ row.dataset_key }}</code>
              </div>
              <p v-if="row.description" class="ps-row-desc">{{ row.description }}</p>
              <div class="ps-row-meta">
                <span v-if="row.time_start"
                  >{{ row.time_start }}{{ row.time_end ? ` ~ ${row.time_end}` : '' }}</span
                >
                <span v-if="row.extra && row.extra.count"> · {{ row.extra.count }} 个产品</span>
                <span v-if="row.extra && row.extra.version"> · v{{ row.extra.version }}</span>
              </div>
              <div class="ps-row-actions">
                <a
                  v-if="row.extra && row.extra.data_link"
                  :href="String(row.extra.data_link)"
                  target="_blank"
                  rel="noopener noreferrer"
                  class="ps-link"
                >
                  数据集主页
                </a>
                <button type="button" class="btn" :disabled="adding !== ''" @click="addGrant(row)">
                  添加数据集授权
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
.ps-row-desc {
  margin: 0;
  color: var(--text-muted);
  font-size: var(--font-size-caption);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
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
