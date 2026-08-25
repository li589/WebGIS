<script setup lang="ts">
/**
 * RegisteredRemoteSources — 已注册「可访问远程数据源」表（2026-08-25 改版）。
 *
 * 数据来自 GET /config/remote-sources（别名条目，供下载节点一键填充）。
 * 列：别名 / 站点 / 已选数据集（来自 remote_dataset_grants，按门户聚合）/
 * 操作。不再展示「访问模式」「远端路径」「缓存策略」——术语不友好且
 * 语义已收敛为整源注册（site_compatible 唯一形态，用户无需感知）。
 */

import { computed, onMounted, ref, toRef, watch } from 'vue'
import { useSettingsStore } from '../../../stores/settings'
import {
  fetchRemoteDatasetGrants,
  type RemoteDatasetGrant,
} from '../../../services/settings-api'

const settingsStore = useSettingsStore()
const remoteSourceRegistry = toRef(settingsStore, 'remoteSourceRegistry')

const busy = ref(false)
const errMsg = ref('')

const KIND_LABELS: Record<string, string> = {
  storage_profile: '存储源',
  portal: '门户',
}

// ── 已选数据集（按 portal_id 聚合展示） ──────────────────────────────────

const grants = ref<RemoteDatasetGrant[]>([])

async function loadGrants() {
  try {
    grants.value = await fetchRemoteDatasetGrants()
  } catch {
    grants.value = []
  }
}

onMounted(loadGrants)

// 注册/删除后注册表条目数变化 → 重新拉取 grants（否则新注册的数据集
// 记录不显示在「已选数据集」列——2026-08-25 浏览器实测发现）
watch(
  () => remoteSourceRegistry.value.length,
  () => {
    void loadGrants()
  },
)

const grantsByPortal = computed(() => {
  const map = new Map<string, string[]>()
  for (const g of grants.value) {
    const key = g.portal_id || ''
    if (!map.has(key)) map.set(key, [])
    map.get(key)!.push(g.dataset_key || g.dataset_title || '')
  }
  return map
})

function datasetKeysOf(refId: string): string[] {
  return grantsByPortal.value.get(refId) ?? []
}

async function remove(id: string) {
  if (!confirm(`确认删除可访问数据源「${id}」？`)) return
  busy.value = true
  errMsg.value = ''
  try {
    await settingsStore.removeRemoteSource(id)
  } catch (e) {
    errMsg.value = (e as Error).message
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <section class="form-card">
    <h4 class="card-title">已添加的可访问远程数据源</h4>
    <p class="card-hint">
      注册后数据可经工作流下载节点自动访问（remote_fetch / http_open_data 一键引用）。
      在上方点「添加为可访问远程数据源」，可检索选取数据集或注册整源。
    </p>
    <p v-if="errMsg" class="form-error">{{ errMsg }}</p>

    <p v-if="remoteSourceRegistry.length === 0" class="card-hint empty">
      暂无已注册条目。在上方分组中点击「添加为可访问远程数据源」。
    </p>

    <div v-else class="reg-table">
      <div class="row head">
        <span>别名 ID</span>
        <span>类型</span>
        <span>站点</span>
        <span>已选数据集</span>
        <span>操作</span>
      </div>
      <div v-for="r in remoteSourceRegistry" :key="r.remote_source_id" class="row">
        <span class="alias" :title="r.remote_source_id">{{ r.remote_source_id }}</span>
        <span>{{ KIND_LABELS[r.kind] || r.kind }}</span>
        <span class="ref">
          <template v-if="r.ref_exists && r.ref">
            {{ r.ref.display_name || r.ref.name || r.ref_id }}
            <em v-if="r.ref.protocol" class="proto">{{ r.ref.protocol }}</em>
            <em
              v-if="r.ref.last_test_status"
              class="proto"
              :class="r.ref.last_test_status === 'ok' ? 'ok' : 'fail'"
            >
              {{ r.ref.last_test_status === 'ok' ? '已验证' : '测试失败' }}
            </em>
          </template>
          <template v-else>
            <em class="proto fail">源已删除</em>
          </template>
        </span>
        <span class="datasets" :title="datasetKeysOf(r.ref_id).join('、')">
          <template v-if="datasetKeysOf(r.ref_id).length">
            {{ datasetKeysOf(r.ref_id).slice(0, 2).join('、')
            }}<em v-if="datasetKeysOf(r.ref_id).length > 2" class="more">
              +{{ datasetKeysOf(r.ref_id).length - 2 }}</em
            >
          </template>
          <em v-else class="whole-source">整源</em>
        </span>
        <span class="ops">
          <button
            type="button"
            class="btn danger"
            :disabled="busy"
            @click="remove(r.remote_source_id)"
          >
            删除
          </button>
        </span>
      </div>
    </div>
  </section>
</template>

<style scoped src="../settings-form.css"></style>
<style scoped>
.card-title {
  margin: 0;
  color: var(--text-strong);
  font-size: var(--font-size-caption);
  font-weight: 600;
}
.card-hint {
  margin: 0;
  color: var(--text-muted);
  font-size: var(--font-size-caption);
  line-height: 1.45;
}
.card-hint.empty {
  padding: 0.4rem 0;
}
.reg-table {
  display: flex;
  flex-direction: column;
  border: 1px solid var(--border-subtle);
  border-radius: 0.4rem;
  overflow: hidden;
}
.row {
  display: grid;
  grid-template-columns: 9rem 3.6rem 1fr 11rem 3.6rem;
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
.alias {
  font-weight: 600;
  color: var(--text-strong);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.ref,
.datasets {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.ref {
  color: var(--text-primary);
}
.datasets {
  color: var(--text-muted);
}
.more {
  font-style: normal;
  color: var(--accent-strong);
  margin-left: 0.2rem;
}
.whole-source {
  font-style: normal;
  padding: 0.04rem 0.26rem;
  border-radius: 0.2rem;
  background: var(--border-default);
  color: var(--text-muted);
}
.proto {
  font-style: normal;
  margin-left: 0.3rem;
  padding: 0.04rem 0.26rem;
  border-radius: 0.2rem;
  background: var(--border-default);
  color: var(--accent-strong);
  font-size: var(--font-size-micro, 0.68rem);
}
.proto.ok {
  background: var(--success-surface);
  color: var(--success);
}
.proto.fail {
  background: var(--danger-surface);
  color: var(--danger);
}
.ops {
  display: flex;
  justify-content: flex-end;
}
.btn.danger {
  border-color: var(--danger-border);
  background: var(--danger-surface);
  color: var(--danger);
}
</style>
