<script setup lang="ts">
/**
 * RegisteredRemoteSources — 已注册「可访问远程数据源」表。
 *
 * 数据来自 GET /config/remote-sources（别名条目，供下载节点一键填充）。
 * ref 徽标来自后端附带的引用源能力信息；引用源已删除时标记失效，可删除条目。
 */

import { ref, toRef } from 'vue'
import { useSettingsStore } from '../../../stores/settings'

const settingsStore = useSettingsStore()
const remoteSourceRegistry = toRef(settingsStore, 'remoteSourceRegistry')

const busy = ref(false)
const errMsg = ref('')

const KIND_LABELS: Record<string, string> = {
  storage_profile: '存储源',
  portal: '门户',
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

/** Phase 4：切换访问模式（legacy ↔ site_compatible） */
async function toggleAccessMode(id: string, current: string) {
  const newMode: 'legacy' | 'site_compatible' =
    current === 'site_compatible' ? 'legacy' : 'site_compatible'
  busy.value = true
  errMsg.value = ''
  try {
    await settingsStore.toggleRemoteSourceAccessMode(id, newMode)
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
      别名条目，供工作流下载节点一键填充（remote_fetch 生成带 <code>?cred=</code> 的 URI、
      http_open_data 填 preset）。在上方浏览/检索并「添加」，或对整源直接注册。
    </p>
    <p v-if="errMsg" class="form-error">{{ errMsg }}</p>

    <p v-if="remoteSourceRegistry.length === 0" class="card-hint empty">
      暂无已注册条目。在上方分组中浏览/检索选中目录或数据集后点击「添加为远程数据源」。
    </p>

    <div v-else class="reg-table">
      <div class="row head">
        <span>别名 ID</span>
        <span>类型</span>
        <span>引用源</span>
        <span>远端路径</span>
        <span>访问模式</span>
        <span>缓存策略</span>
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
        <span class="path" :title="r.remote_path">{{ r.remote_path || '（整源）' }}</span>
        <span>
          <button
            type="button"
            class="btn access-mode-toggle"
            :disabled="busy"
            :title="`切换到 ${r.access_mode === 'site_compatible' ? 'legacy' : 'site_compatible'} 模式`"
            @click="toggleAccessMode(r.remote_source_id, r.access_mode)"
          >
            <span
              class="mode-badge"
              :class="r.access_mode === 'site_compatible' ? 'compatible' : 'legacy'"
            >
              {{ r.access_mode === 'site_compatible' ? '兼容' : '标准' }}
            </span>
          </button>
        </span>
        <span>{{ r.cache_policy }}</span>
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
  grid-template-columns: 9rem 3.6rem 1fr 10rem 5rem 4.2rem 3.6rem;
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
.path {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.ref {
  color: var(--text-primary);
}
.path {
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
.access-mode-toggle {
  padding: 0.15rem 0.35rem;
  border: 1px solid var(--border-subtle);
  background: var(--surface-sunken);
  cursor: pointer;
  border-radius: 0.25rem;
  font-size: var(--font-size-caption);
  color: var(--text-primary);
}
.access-mode-toggle:hover:not(:disabled) {
  background: var(--surface-default);
  border-color: var(--accent-strong);
}
.access-mode-toggle:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}
.mode-badge {
  display: inline-block;
  padding: 0.1rem 0.35rem;
  border-radius: 0.2rem;
  font-size: 0.72rem;
  font-weight: 600;
}
.mode-badge.compatible {
  background: var(--success-surface);
  color: var(--success);
}
.mode-badge.legacy {
  background: var(--warning-surface, #fff3cd);
  color: var(--warning, #856404);
}
</style>
