<script setup lang="ts">
/**
 * LocalDataSourcePanel — 本地数据源页。
 *
 * 组成：路径细分配置（PathConfigSection）+ 可用数据集注册表（AvailableDatasetsPanel）
 * + 保留只读区（存储配置 / 静态 materialize 缓存 / 底图代理 / MinIO / 图层 URI 覆盖）。
 *
 * 原「已发现的逻辑数据集」目录平铺与「开放数据预设 / 开放门户凭证」已分别由
 * 可用数据集注册表与「远程与存储 → 开放门户」替代。
 */

import { computed, onMounted, ref } from 'vue'
import { storeToRefs } from 'pinia'
import { useSettingsStore } from '../../../stores/settings'
import { useWeatherTileManager } from '../../../stores/weather-tile-manager'
import {
  evictDataCache,
  fetchDataCacheOverview,
  updateRemoteLayerUris,
  type DataCacheOverview,
} from '../../../services/settings-api'
import PathConfigSection from './PathConfigSection.vue'
import AvailableDatasetsPanel from './AvailableDatasetsPanel.vue'

const settingsStore = useSettingsStore()
const weatherTileManager = useWeatherTileManager()
const { dataSourceConfig } = storeToRefs(settingsStore)

const cacheOverview = ref<DataCacheOverview | null>(null)
const cacheBusy = ref(false)
const cacheMsg = ref('')
const urisText = ref('')
const urisBusy = ref(false)
const urisMsg = ref('')

const staticCache = computed(() => dataSourceConfig.value?.static_cache ?? null)

const storageItems = computed(() => {
  if (!dataSourceConfig.value) return []
  const cfg = dataSourceConfig.value
  return [
    { label: '存储后端类型', value: cfg.storage_backend },
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

function syncUris() {
  urisText.value = JSON.stringify(dataSourceConfig.value?.remote_layer_data_uris ?? {}, null, 2)
}

async function refreshCache() {
  cacheBusy.value = true
  cacheMsg.value = ''
  try {
    cacheOverview.value = await fetchDataCacheOverview()
  } catch (e) {
    cacheMsg.value = (e as Error).message
  } finally {
    cacheBusy.value = false
  }
}

async function handleEvictAll() {
  if (!confirm('确认清理全部静态 materialize 缓存？')) return
  cacheBusy.value = true
  try {
    const result = await evictDataCache({})
    cacheMsg.value = `已清理 ${result.removed_count ?? result.removed?.length ?? 0} 项`
    weatherTileManager.invalidateAllTileCaches()
    await refreshCache()
    await settingsStore.loadAll()
  } catch (e) {
    cacheMsg.value = (e as Error).message
  } finally {
    cacheBusy.value = false
  }
}

async function saveUris() {
  urisBusy.value = true
  urisMsg.value = ''
  try {
    const parsed = JSON.parse(urisText.value || '{}') as Record<
      string,
      Record<string, string | string[]>
    >
    await updateRemoteLayerUris(parsed)
    urisMsg.value = '图层 URI 覆盖已保存'
    await settingsStore.loadAll()
    syncUris()
  } catch (e) {
    urisMsg.value = (e as Error).message
  } finally {
    urisBusy.value = false
  }
}

onMounted(() => {
  syncUris()
  void refreshCache()
})
</script>

<template>
  <div class="local-panel">
    <PathConfigSection />

    <AvailableDatasetsPanel />

    <section class="form-card">
      <h4 class="card-title">静态 materialize 缓存</h4>
      <div class="info-grid">
        <div class="info-row">
          <span class="info-label">缓存目录</span>
          <span class="info-value">{{
            staticCache?.cache_root || cacheOverview?.cache_root || '—'
          }}</span>
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
            {{
              (
                (cacheOverview?.total_bytes ?? staticCache?.total_bytes ?? 0) /
                (1024 * 1024)
              ).toFixed(2)
            }}
            MiB
          </span>
        </div>
      </div>
      <p v-if="cacheMsg" class="form-status">{{ cacheMsg }}</p>
      <div class="form-actions">
        <button type="button" class="btn" :disabled="cacheBusy" @click="refreshCache">刷新</button>
        <button type="button" class="btn danger" :disabled="cacheBusy" @click="handleEvictAll">
          清理缓存
        </button>
      </div>
    </section>

    <section class="form-card">
      <h4 class="card-title">存储配置（只读）</h4>
      <div class="info-grid">
        <div v-for="item in storageItems" :key="item.label" class="info-row">
          <span class="info-label">{{ item.label }}</span>
          <span class="info-value" :title="item.value">{{ item.value }}</span>
        </div>
      </div>
    </section>

    <section class="form-card">
      <h4 class="card-title">底图代理（只读）</h4>
      <div class="info-grid">
        <div v-for="item in tileProxyItems" :key="item.label" class="info-row">
          <span class="info-label">{{ item.label }}</span>
          <span class="info-value">{{ item.value }}</span>
        </div>
      </div>
    </section>

    <section v-if="minioItems.length > 0" class="form-card">
      <h4 class="card-title">MinIO 对象存储（只读）</h4>
      <div class="info-grid">
        <div v-for="item in minioItems" :key="item.label" class="info-row">
          <span class="info-label">{{ item.label }}</span>
          <span class="info-value">{{ item.value }}</span>
        </div>
      </div>
    </section>

    <section class="form-card">
      <h4 class="card-title">图层 URI 覆盖</h4>
      <p class="card-hint">
        嵌套 JSON，等价 <code>BACKEND_REMOTE_LAYER_DATA_URIS</code>；DB 配置优先于环境变量。
      </p>
      <textarea v-model="urisText" class="code-area" rows="6" spellcheck="false" />
      <p v-if="urisMsg" class="form-status">{{ urisMsg }}</p>
      <div class="form-actions">
        <button type="button" class="btn" :disabled="urisBusy" @click="saveUris">保存 URI</button>
      </div>
    </section>

    <p class="card-hint">
      {{
        dataSourceConfig?.workflow_hint ||
        '远程存储 / 开放门户源在「远程与存储」页配置；本页注册的可访问远程数据源在「远程数据源」页管理。'
      }}
    </p>
  </div>
</template>

<style scoped src="../settings-form.css"></style>
<style scoped>
.local-panel {
  display: flex;
  flex-direction: column;
  gap: 0.8rem;
}
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
.info-grid {
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
}
.info-row {
  display: grid;
  grid-template-columns: 8.5rem 1fr;
  gap: 0.5rem;
  font-size: var(--font-size-caption);
  align-items: center;
}
.info-label {
  color: var(--text-muted);
}
.info-value {
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.form-status {
  margin: 0;
  color: var(--success);
  font-size: var(--font-size-caption);
}
.code-area {
  width: 100%;
  box-sizing: border-box;
  border: 1px solid var(--border-default);
  border-radius: 0.4rem;
  background: var(--surface-1);
  color: var(--text-primary);
  font-family: var(--font-mono);
  font-size: var(--font-size-caption);
  padding: 0.5rem;
}
.btn.danger {
  border-color: var(--danger-border);
  background: var(--danger-surface);
  color: var(--danger);
}
</style>
