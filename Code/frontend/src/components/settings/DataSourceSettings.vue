<script setup lang="ts">
import { computed, ref } from 'vue'
import { storeToRefs } from 'pinia'
import { useSettingsStore } from '../../stores/settings'
import {
  fetchDataCacheOverview,
  evictDataCache,
  updateOpenDataPresets,
  updateRemoteLayerUris,
  type DataCacheOverview,
} from '../../services/settings-api'

const settingsStore = useSettingsStore()
const { dataSourceConfig } = storeToRefs(settingsStore)

const cacheOverview = ref<DataCacheOverview | null>(null)
const cacheBusy = ref(false)
const saveBusy = ref(false)
const statusMsg = ref('')
const presetsText = ref('')
const urisText = ref('')

const storageItems = computed(() => {
  if (!dataSourceConfig.value) return []
  const cfg = dataSourceConfig.value
  return [
    { label: '存储后端类型', value: cfg.storage_backend },
    { label: '数据根目录', value: cfg.data_root || '未配置' },
    { label: '产物输出目录', value: cfg.output_root || '未配置' },
    { label: '下载源根目录', value: cfg.download_source_root || '未配置' },
    { label: '真实抓取', value: cfg.download_real_fetch_enabled ? '启用' : '禁用' },
  ]
})

const tileProxyItems = computed(() => {
  if (!dataSourceConfig.value) return []
  const cfg = dataSourceConfig.value
  return [
    { label: '底图代理', value: cfg.tile_proxy_enabled ? '启用' : '禁用' },
    { label: '代理缓存 TTL', value: `${cfg.tile_proxy_cache_ttl_seconds} 秒` },
  ]
})

const minioItems = computed(() => {
  if (!dataSourceConfig.value?.minio) return []
  const m = dataSourceConfig.value.minio
  return [
    { label: 'MinIO 端点', value: m.endpoint },
    { label: '存储桶', value: m.bucket },
    { label: 'HTTPS', value: m.secure ? '是' : '否' },
  ]
})

const discovered = computed(() => dataSourceConfig.value?.discovered_datasets ?? [])
const staticCache = computed(() => dataSourceConfig.value?.static_cache ?? null)

function syncEditorsFromConfig() {
  const cfg = dataSourceConfig.value
  if (!cfg) return
  presetsText.value = JSON.stringify(cfg.open_data_presets ?? {}, null, 2)
  urisText.value = JSON.stringify(cfg.remote_layer_data_uris ?? {}, null, 2)
}

async function refreshCache() {
  cacheBusy.value = true
  statusMsg.value = ''
  try {
    cacheOverview.value = await fetchDataCacheOverview()
  } catch (e) {
    statusMsg.value = (e as Error).message
  } finally {
    cacheBusy.value = false
  }
}

async function handleEvictAll() {
  if (!confirm('确认清理全部静态 materialize 缓存？')) return
  cacheBusy.value = true
  try {
    const result = await evictDataCache({})
    statusMsg.value = `已清理 ${result.removed_count ?? result.removed?.length ?? 0} 项`
    await refreshCache()
    await settingsStore.loadAll()
    syncEditorsFromConfig()
  } catch (e) {
    statusMsg.value = (e as Error).message
  } finally {
    cacheBusy.value = false
  }
}

async function savePresets() {
  saveBusy.value = true
  statusMsg.value = ''
  try {
    const parsed = JSON.parse(presetsText.value || '{}') as Record<string, string>
    await updateOpenDataPresets(parsed)
    statusMsg.value = '开放数据预设已保存'
    await settingsStore.loadAll()
    syncEditorsFromConfig()
  } catch (e) {
    statusMsg.value = (e as Error).message
  } finally {
    saveBusy.value = false
  }
}

async function saveUris() {
  saveBusy.value = true
  statusMsg.value = ''
  try {
    const parsed = JSON.parse(urisText.value || '{}') as Record<string, Record<string, string | string[]>>
    await updateRemoteLayerUris(parsed)
    statusMsg.value = '图层 URI 覆盖已保存'
    await settingsStore.loadAll()
    syncEditorsFromConfig()
  } catch (e) {
    statusMsg.value = (e as Error).message
  } finally {
    saveBusy.value = false
  }
}

syncEditorsFromConfig()
void refreshCache()
</script>

<template>
  <div class="data-source-settings">
    <section class="settings-section">
      <h3 class="section-title">存储配置</h3>
      <div class="info-grid">
        <div v-for="item in storageItems" :key="item.label" class="info-row">
          <span class="info-label">{{ item.label }}</span>
          <span class="info-value" :title="item.value">{{ item.value }}</span>
        </div>
      </div>
    </section>

    <section class="settings-section">
      <h3 class="section-title">已发现逻辑数据集</h3>
      <p v-if="discovered.length === 0" class="section-hint">未配置 BACKEND_DATA_ROOT 或目录为空。</p>
      <ul v-else class="dataset-list">
        <li v-for="ds in discovered" :key="ds.name">
          <strong>{{ ds.name }}</strong>
          <span class="muted">{{ ds.file_count }} 文件 · {{ ds.path }}</span>
        </li>
      </ul>
    </section>

    <section class="settings-section">
      <h3 class="section-title">开放数据预设（NOAA / NASA / ESA）</h3>
      <p class="section-hint">供工作流「开放数据 HTTP」节点使用；可覆盖默认 base URL。</p>
      <textarea v-model="presetsText" class="code-area" rows="8" spellcheck="false" />
      <button type="button" class="btn" :disabled="saveBusy" @click="savePresets">保存预设</button>
    </section>

    <section class="settings-section">
      <h3 class="section-title">图层 URI 覆盖</h3>
      <p class="section-hint">
        嵌套 JSON，等价 <code>BACKEND_REMOTE_LAYER_DATA_URIS</code>；DB 配置优先于环境变量。
        示例：
        <code>{"smap-soil":{"SMAP_SPL3SMP_E":["smb://nas/share/x.h5?cred=nas-lab"]}}</code>
      </p>
      <textarea v-model="urisText" class="code-area" rows="6" spellcheck="false" />
      <button type="button" class="btn" :disabled="saveBusy" @click="saveUris">保存 URI</button>
    </section>

    <section class="settings-section">
      <h3 class="section-title">静态 materialize 缓存</h3>
      <div class="info-grid">
        <div class="info-row">
          <span class="info-label">缓存目录</span>
          <span class="info-value">{{ staticCache?.cache_root || cacheOverview?.cache_root || '—' }}</span>
        </div>
        <div class="info-row">
          <span class="info-label">TTL</span>
          <span class="info-value">
            {{
              (staticCache?.ttl_unlimited ?? cacheOverview?.ttl_unlimited)
                ? '不过期 (0)'
                : `${staticCache?.ttl_seconds ?? cacheOverview?.ttl_seconds ?? 0} 秒`
            }}
          </span>
        </div>
        <div class="info-row">
          <span class="info-label">条目 / 体积</span>
          <span class="info-value">
            {{ cacheOverview?.entry_count ?? staticCache?.entry_count ?? 0 }} /
            {{ (((cacheOverview?.total_bytes ?? staticCache?.total_bytes ?? 0) / (1024 * 1024)).toFixed(2)) }} MiB
          </span>
        </div>
      </div>
      <div class="btn-row">
        <button type="button" class="btn" :disabled="cacheBusy" @click="refreshCache">刷新</button>
        <button type="button" class="btn danger" :disabled="cacheBusy" @click="handleEvictAll">清理缓存</button>
      </div>
    </section>

    <section class="settings-section">
      <h3 class="section-title">底图代理</h3>
      <div class="info-grid">
        <div v-for="item in tileProxyItems" :key="item.label" class="info-row">
          <span class="info-label">{{ item.label }}</span>
          <span class="info-value">{{ item.value }}</span>
        </div>
      </div>
    </section>

    <section v-if="minioItems.length > 0" class="settings-section">
      <h3 class="section-title">MinIO 对象存储</h3>
      <div class="info-grid">
        <div v-for="item in minioItems" :key="item.label" class="info-row">
          <span class="info-label">{{ item.label }}</span>
          <span class="info-value">{{ item.value }}</span>
        </div>
      </div>
    </section>

    <p class="section-hint">
      {{ dataSourceConfig?.workflow_hint || '远程存储凭证在「远程存储」页配置；工作流 download 节点可通过 ?cred=profile 引用。' }}
    </p>
    <p v-if="statusMsg" class="status-msg">{{ statusMsg }}</p>
  </div>
</template>

<style scoped>
.data-source-settings {
  display: flex;
  flex-direction: column;
  gap: 1.2rem;
}

.settings-section {
  display: flex;
  flex-direction: column;
  gap: 0.52rem;
}

.section-title {
  margin: 0 0 0.32rem;
  color: #e8f3fc;
  font-size: 0.7rem;
  font-weight: 600;
}

.info-grid {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
}

.info-row {
  display: grid;
  grid-template-columns: 8.5rem 1fr;
  gap: 0.5rem;
  font-size: 0.72rem;
}

.info-label {
  color: #8aa0b5;
}

.info-value {
  color: #d7e6f5;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.section-hint {
  margin: 0;
  color: #8aa0b5;
  font-size: 0.68rem;
  line-height: 1.45;
}

.dataset-list {
  margin: 0;
  padding-left: 1.1rem;
  color: #d7e6f5;
  font-size: 0.72rem;
}

.muted {
  display: block;
  color: #8aa0b5;
  font-size: 0.65rem;
}

.code-area {
  width: 100%;
  box-sizing: border-box;
  border: 1px solid #2a3d52;
  border-radius: 6px;
  background: #0d1620;
  color: #d7e6f5;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 0.68rem;
  padding: 0.5rem;
  resize: vertical;
}

.btn-row {
  display: flex;
  gap: 0.5rem;
}

.btn {
  align-self: flex-start;
  border: 1px solid #3a5570;
  border-radius: 6px;
  background: #1a2a3a;
  color: #e8f3fc;
  font-size: 0.68rem;
  padding: 0.35rem 0.7rem;
  cursor: pointer;
}

.btn:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.btn.danger {
  border-color: #7a3a3a;
  background: #3a1a1a;
}

.status-msg {
  margin: 0;
  color: #9fd0a8;
  font-size: 0.68rem;
}
</style>
