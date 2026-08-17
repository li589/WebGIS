<script setup lang="ts">
/**
 * AvailableDatasetsPanel — 可用数据集注册表。
 *
 * 数据来自 GET /config/data-source/datasets（运行时可编辑注册表）。
 * 顶栏：搜索 / 来源筛选 / 重新扫描 / 新增；行操作：编辑 / 启停 / 删除（内置条目禁删）。
 */

import { computed, ref } from 'vue'
import { storeToRefs } from 'pinia'
import { useSettingsStore } from '../../../stores/settings'
import type { AvailableDatasetEntry } from '../../../types/api-reexports'
import DatasetFormDialog from './DatasetFormDialog.vue'

const settingsStore = useSettingsStore()
const { availableDatasets } = storeToRefs(settingsStore)

const search = ref('')
const sourceFilter = ref('all')
const busy = ref(false)
const statusMsg = ref('')
const errMsg = ref('')

const dialogVisible = ref(false)
const editing = ref<AvailableDatasetEntry | null>(null)

const SOURCE_LABELS: Record<string, string> = {
  manual: '手动',
  scan: '扫描',
  algorithm_registry: '内置',
}

const filtered = computed(() => {
  const q = search.value.trim().toLowerCase()
  return [...availableDatasets.value]
    .filter((d) => sourceFilter.value === 'all' || d.source === sourceFilter.value)
    .filter(
      (d) =>
        !q ||
        d.logical_name.toLowerCase().includes(q) ||
        d.path.toLowerCase().includes(q) ||
        (d.tags ?? []).some((t) => t.toLowerCase().includes(q)),
    )
    .sort((a, b) => a.logical_name.localeCompare(b.logical_name))
})

const countBySource = computed(() => {
  const m: Record<string, number> = { all: availableDatasets.value.length }
  for (const d of availableDatasets.value) m[d.source] = (m[d.source] ?? 0) + 1
  return m
})

function pathDisplay(d: AvailableDatasetEntry): string {
  const root = settingsStore.dataSourceConfig?.data_root || ''
  if (root && d.path.startsWith(root)) {
    return `{数据根}${d.path.slice(root.length)}`
  }
  return d.path
}

async function rescan() {
  busy.value = true
  statusMsg.value = ''
  errMsg.value = ''
  try {
    const res = await settingsStore.runDatasetRescan()
    statusMsg.value = `扫描完成：新增 ${res.created}、刷新 ${res.refreshed}`
  } catch (e) {
    errMsg.value = (e as Error).message
  } finally {
    busy.value = false
  }
}

async function toggleEnabled(d: AvailableDatasetEntry) {
  busy.value = true
  errMsg.value = ''
  try {
    await settingsStore.saveAvailableDataset(d.dataset_id, {
      logical_name: d.logical_name,
      path: d.path,
      file_format: d.file_format || null,
      variables: d.variables ?? [],
      time_range: d.time_range || null,
      resolution: d.resolution || null,
      tags: d.tags ?? [],
      description: d.description || null,
      enabled: !(d.enabled !== false),
    })
  } catch (e) {
    errMsg.value = (e as Error).message
  } finally {
    busy.value = false
  }
}

async function remove(d: AvailableDatasetEntry) {
  if (d.source === 'algorithm_registry') return
  if (!confirm(`确认删除数据集「${d.logical_name}」？（不影响磁盘文件）`)) return
  busy.value = true
  errMsg.value = ''
  try {
    await settingsStore.removeAvailableDataset(d.dataset_id)
  } catch (e) {
    errMsg.value = (e as Error).message
  } finally {
    busy.value = false
  }
}

function openCreate() {
  editing.value = null
  dialogVisible.value = true
}

function openEdit(d: AvailableDatasetEntry) {
  editing.value = d
  dialogVisible.value = true
}

function onSaved() {
  statusMsg.value = '数据集已保存'
}
</script>

<template>
  <section class="form-card">
    <div class="panel-head">
      <h4 class="card-title">可用数据集</h4>
      <div class="tools">
        <input v-model="search" class="search" placeholder="按名称 / 路径 / 标签过滤" />
        <select v-model="sourceFilter" class="src-select">
          <option value="all">全部来源 ({{ countBySource.all ?? 0 }})</option>
          <option value="manual">手动 ({{ countBySource.manual ?? 0 }})</option>
          <option value="scan">扫描 ({{ countBySource.scan ?? 0 }})</option>
          <option value="algorithm_registry">
            内置 ({{ countBySource.algorithm_registry ?? 0 }})
          </option>
        </select>
        <button type="button" class="btn" :disabled="busy" @click="rescan">
          {{ busy ? '处理中…' : '重新扫描' }}
        </button>
        <button type="button" class="btn btn-primary" @click="openCreate">新增数据集</button>
      </div>
    </div>
    <p class="card-hint">
      注册表驱动图层就绪与工作流数据集解析；路径可为绝对路径或相对数据根。「内置」条目来自算法包
      DATASET_REGISTRY，仅可覆盖路径与元数据。
    </p>

    <p v-if="statusMsg" class="form-status">{{ statusMsg }}</p>
    <p v-if="errMsg" class="form-error">{{ errMsg }}</p>

    <p v-if="filtered.length === 0" class="card-hint empty">
      {{
        availableDatasets.length === 0
          ? '暂无数据集：点击「重新扫描」从数据根发现，或「新增数据集」手动登记。'
          : '没有匹配筛选条件的数据集。'
      }}
    </p>

    <div v-else class="dataset-table">
      <div class="row head">
        <span>名称</span>
        <span>路径</span>
        <span>格式 / 分辨率</span>
        <span>文件数</span>
        <span>来源</span>
        <span>操作</span>
      </div>
      <div
        v-for="d in filtered"
        :key="d.dataset_id"
        class="row"
        :class="{ disabled: d.enabled === false }"
      >
        <span class="name" :title="d.logical_name">
          {{ d.logical_name }}
          <em v-if="d.enabled === false" class="off-tag">已停用</em>
        </span>
        <span class="path" :title="d.path">{{ pathDisplay(d) }}</span>
        <span class="meta">
          {{ [d.file_format, d.resolution].filter(Boolean).join(' · ') || '—' }}
          <template v-if="(d.variables ?? []).length">
            · {{ (d.variables ?? []).slice(0, 3).join('/')
            }}<template v-if="(d.variables ?? []).length > 3">…</template>
          </template>
        </span>
        <span class="count">
          {{ d.file_count == null ? '—' : `${d.file_count}` }}
        </span>
        <span>
          <span class="src-badge" :class="`src-${d.source}`">
            {{ SOURCE_LABELS[d.source] || d.source }}
          </span>
        </span>
        <span class="ops">
          <button type="button" class="btn" :disabled="busy" @click="openEdit(d)">编辑</button>
          <button type="button" class="btn" :disabled="busy" @click="toggleEnabled(d)">
            {{ d.enabled === false ? '启用' : '停用' }}
          </button>
          <button
            v-if="d.source !== 'algorithm_registry'"
            type="button"
            class="btn danger"
            :disabled="busy"
            @click="remove(d)"
          >
            删除
          </button>
        </span>
      </div>
    </div>

    <DatasetFormDialog
      :visible="dialogVisible"
      :editing="editing"
      @close="dialogVisible = false"
      @saved="onSaved"
    />
  </section>
</template>

<style scoped src="../settings-form.css"></style>
<style scoped>
.panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
  flex-wrap: wrap;
}
.card-title {
  margin: 0;
  color: var(--text-strong);
  font-size: var(--font-size-caption);
  font-weight: 600;
}
.tools {
  display: flex;
  gap: 0.4rem;
  flex-wrap: wrap;
  align-items: center;
}
.search,
.src-select {
  border: 1px solid var(--border-default);
  border-radius: 0.36rem;
  background: var(--surface-1);
  color: var(--text-strong);
  font-size: var(--font-size-caption);
  padding: 0.28rem 0.42rem;
}
.search {
  width: 12rem;
}
.card-hint {
  margin: 0;
  color: var(--text-muted);
  font-size: var(--font-size-caption);
  line-height: 1.45;
}
.card-hint.empty {
  padding: 0.6rem 0;
}
.form-status {
  margin: 0;
  color: var(--success);
  font-size: var(--font-size-caption);
}
.dataset-table {
  display: flex;
  flex-direction: column;
  border: 1px solid var(--border-subtle);
  border-radius: 0.4rem;
  overflow: hidden;
}
.row {
  display: grid;
  grid-template-columns: 9rem 1fr 12rem 3.6rem 3.6rem 12.5rem;
  gap: 0.4rem;
  align-items: center;
  padding: 0.3rem 0.5rem;
  font-size: var(--font-size-caption);
  color: var(--text-primary);
  border-bottom: 1px solid var(--border-subtle);
}
.row:last-child {
  border-bottom: none;
}
.row.head {
  background: var(--surface-sunken);
  color: var(--text-muted);
  font-weight: 600;
}
.row.disabled {
  opacity: 0.55;
}
.name {
  font-weight: 600;
  color: var(--text-strong);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.off-tag {
  margin-left: 0.3rem;
  font-style: normal;
  color: var(--accent-warm);
  font-size: var(--font-size-micro, 0.68rem);
}
.path,
.meta,
.count {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--text-muted);
}
.count {
  text-align: right;
}
.src-badge {
  padding: 0.06rem 0.3rem;
  border-radius: 0.24rem;
  background: var(--border-default);
  color: var(--accent-strong);
  white-space: nowrap;
}
.src-manual {
  background: var(--accent-surface);
}
.src-scan {
  background: var(--warning-surface);
  color: var(--accent-warm);
}
.src-algorithm_registry {
  background: var(--surface-3);
  color: var(--text-strong);
}
.ops {
  display: flex;
  gap: 0.3rem;
  justify-content: flex-end;
}
.btn.danger {
  border-color: var(--danger-border);
  background: var(--danger-surface);
  color: var(--danger);
}
</style>
