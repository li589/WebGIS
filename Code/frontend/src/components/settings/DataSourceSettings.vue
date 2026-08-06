<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { storeToRefs } from 'pinia'
import { useSettingsStore } from '../../stores/settings'
import { useWeatherTileManager } from '../../stores/weather-tile-manager'
import {
  fetchDataCacheOverview,
  evictDataCache,
  updateOpenDataPresets,
  updateRemoteLayerUris,
  upsertPortalCredential,
  deletePortalCredential,
  updateDataSourcePaths,
  restartBackendService,
  waitForBackendHealthy,
  type DataCacheOverview,
  type PortalCredentialPublic,
} from '../../services/settings-api'

const settingsStore = useSettingsStore()
const weatherTileManager = useWeatherTileManager()
const { dataSourceConfig } = storeToRefs(settingsStore)

const cacheOverview = ref<DataCacheOverview | null>(null)
const cacheBusy = ref(false)
const saveBusy = ref(false)
const restartBusy = ref(false)
const statusMsg = ref('')
const presetsText = ref('')
const urisText = ref('')
const dataRootDraft = ref('')
const outputRootDraft = ref('')

const portalForms = reactive<
  Record<
    string,
    {
      enabled: boolean
      auth_type: string
      username: string
      token: string
      password: string
      client_id: string
      use_for_nsidc: boolean
      use_earthdata: boolean
    }
  >
>({
  earthdata: {
    enabled: false,
    auth_type: 'bearer',
    username: '',
    token: '',
    password: '',
    client_id: '',
    use_for_nsidc: true,
    use_earthdata: true,
  },
  nsidc: {
    enabled: false,
    auth_type: 'bearer',
    username: '',
    token: '',
    password: '',
    client_id: '',
    use_for_nsidc: true,
    use_earthdata: true,
  },
  copernicus: {
    enabled: false,
    auth_type: 'bearer',
    username: '',
    token: '',
    password: '',
    client_id: '',
    use_for_nsidc: true,
    use_earthdata: true,
  },
})

const portalMeta = computed(() => dataSourceConfig.value?.portal_credentials ?? {})
const presetLabels = computed(() => dataSourceConfig.value?.open_data_preset_labels ?? {})

const storageItems = computed(() => {
  if (!dataSourceConfig.value) return []
  const cfg = dataSourceConfig.value
  return [
    { label: '存储后端类型', value: cfg.storage_backend },
    { label: '下载源根目录', value: cfg.download_source_root || '未配置' },
    { label: '真实抓取', value: cfg.download_real_fetch_enabled ? '启用' : '禁用' },
  ]
})

const pendingRestart = computed(() => Boolean(dataSourceConfig.value?.pending_restart))
const uiRestartEnabled = computed(() => dataSourceConfig.value?.ui_restart_enabled !== false)

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
  dataRootDraft.value = cfg.env_data_root || cfg.data_root || ''
  outputRootDraft.value = cfg.env_output_root || cfg.output_root || ''
  const portals = cfg.portal_credentials ?? {}
  for (const id of ['earthdata', 'nsidc', 'copernicus'] as const) {
    const p = portals[id] as PortalCredentialPublic | undefined
    if (!p) continue
    portalForms[id].enabled = Boolean(p.enabled)
    portalForms[id].auth_type = p.auth_type || 'bearer'
    portalForms[id].username = p.username || ''
    portalForms[id].client_id = p.client_id || ''
    portalForms[id].use_for_nsidc = p.use_for_nsidc !== false
    portalForms[id].use_earthdata = p.use_earthdata !== false
    portalForms[id].token = ''
    portalForms[id].password = ''
  }
}

async function savePaths(andRestart: boolean) {
  const root = dataRootDraft.value.trim()
  if (!root) {
    statusMsg.value = '请填写数据根目录（绝对路径）'
    return
  }
  if (andRestart) {
    if (!uiRestartEnabled.value) {
      statusMsg.value = '当前环境禁止从前端重启后端（BACKEND_UI_RESTART_ENABLED）'
      return
    }
    if (
      !confirm(
        '将保存路径并重启 FastAPI + Celery Worker + Beat（Docker/前端不动）。期间 API 短暂不可用，确认继续？',
      )
    ) {
      return
    }
  }
  saveBusy.value = true
  restartBusy.value = andRestart
  statusMsg.value = ''
  try {
    const out = outputRootDraft.value.trim()
    const result = await updateDataSourcePaths({
      data_root: root,
      output_root: out || null,
    })
    statusMsg.value = result.message
    dataRootDraft.value = result.data_root
    outputRootDraft.value = result.output_root
    await settingsStore.loadAll()
    syncEditorsFromConfig()
    if (andRestart) {
      statusMsg.value = '已调度后端重启，等待健康检查…'
      await restartBackendService({})
      const ok = await waitForBackendHealthy({ timeoutMs: 120_000 })
      if (!ok) {
        statusMsg.value = '重启已调度，但在超时内未恢复 /health；请检查 launch 日志'
      } else {
        statusMsg.value = '后端已恢复；正在刷新配置与图层就绪状态…'
        await settingsStore.loadAll()
        syncEditorsFromConfig()
        try {
          const { useLayersStore } = await import('../../stores/layers')
          await useLayersStore().ensureRuntimeLayerCatalog(true)
        } catch {
          // catalog refresh is best-effort
        }
        statusMsg.value = '路径已生效，后端已重启完成'
      }
    }
  } catch (e) {
    statusMsg.value = (e as Error).message
  } finally {
    saveBusy.value = false
    restartBusy.value = false
  }
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
    weatherTileManager.invalidateAllTileCaches()
    await refreshCache()
    await settingsStore.loadAll()
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
    const parsed = JSON.parse(urisText.value || '{}') as Record<
      string,
      Record<string, string | string[]>
    >
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

async function savePortal(portalId: string) {
  saveBusy.value = true
  statusMsg.value = ''
  try {
    const form = portalForms[portalId]
    const payload: Record<string, unknown> = {
      enabled: form.enabled,
      auth_type: form.auth_type,
      username: form.username,
    }
    if (form.token.trim()) payload.token = form.token.trim()
    if (form.password.trim()) payload.password = form.password.trim()
    if (portalId === 'earthdata') payload.use_for_nsidc = form.use_for_nsidc
    if (portalId === 'nsidc') payload.use_earthdata = form.use_earthdata
    if (portalId === 'copernicus') payload.client_id = form.client_id
    await upsertPortalCredential(portalId, payload)
    statusMsg.value = `门户凭证 ${portalId} 已保存`
    await settingsStore.loadAll()
    syncEditorsFromConfig()
  } catch (e) {
    statusMsg.value = (e as Error).message
  } finally {
    saveBusy.value = false
  }
}

async function clearPortal(portalId: string) {
  if (!confirm(`确认删除门户凭证 ${portalId}？`)) return
  saveBusy.value = true
  try {
    await deletePortalCredential(portalId)
    statusMsg.value = `已删除 ${portalId}`
    await settingsStore.loadAll()
    syncEditorsFromConfig()
  } catch (e) {
    statusMsg.value = (e as Error).message
  } finally {
    saveBusy.value = false
  }
}

const portalTitles: Record<string, string> = {
  earthdata: 'NASA Earthdata Login',
  nsidc: 'NSIDC（可复用 Earthdata）',
  copernicus: '欧空局 Copernicus',
}

syncEditorsFromConfig()
void refreshCache()
</script>

<template>
  <div class="data-source-settings">
    <section class="settings-section">
      <h3 class="section-title">地理数据根目录</h3>
      <p class="section-hint">
        写入 <code>Code/backend/.env</code>（<code>BACKEND_DATA_ROOT</code> /
        <code>BACKEND_OUTPUT_ROOT</code>）。当前进程生效值需重启 FastAPI + Worker + Beat。
        <span v-if="pendingRestart" class="warn"> · 已保存但尚未重启</span>
      </p>
      <div class="info-grid">
        <div class="info-row">
          <span class="info-label">数据根目录</span>
          <input
            v-model="dataRootDraft"
            class="field"
            type="text"
            placeholder="例如 I:\Geograph_DataSet"
            autocomplete="off"
          />
        </div>
        <div class="info-row">
          <span class="info-label">产物输出目录</span>
          <input
            v-model="outputRootDraft"
            class="field"
            type="text"
            placeholder="留空则使用 {数据根}/ProjectOutput"
            autocomplete="off"
          />
        </div>
        <div class="info-row">
          <span class="info-label">进程生效值</span>
          <span class="info-value" :title="dataSourceConfig?.data_root || ''">
            {{ dataSourceConfig?.data_root || '未配置' }}
            <template v-if="dataSourceConfig?.output_root">
              · 产物 {{ dataSourceConfig.output_root }}
            </template>
          </span>
        </div>
      </div>
      <div class="btn-row">
        <button
          type="button"
          class="btn"
          :disabled="saveBusy || restartBusy"
          @click="savePaths(false)"
        >
          保存路径
        </button>
        <button
          type="button"
          class="btn btn-primary"
          :disabled="saveBusy || restartBusy || !uiRestartEnabled"
          :title="uiRestartEnabled ? '' : 'BACKEND_UI_RESTART_ENABLED 未开启'"
          @click="savePaths(true)"
        >
          {{ restartBusy ? '重启中…' : '保存并重启后端' }}
        </button>
      </div>
    </section>

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
      <p v-if="discovered.length === 0" class="section-hint">
        未配置 BACKEND_DATA_ROOT 或目录为空。
      </p>
      <ul v-else class="dataset-list">
        <li v-for="ds in discovered" :key="ds.name">
          <strong>{{ ds.name }}</strong>
          <span class="muted"
            >{{
              ds.file_count == null
                ? '未统计文件数'
                : `${ds.file_count}${ds.file_count_truncated ? '+' : ''} 文件`
            }}
            · {{ ds.path }}</span
          >
        </li>
      </ul>
    </section>

    <section class="settings-section">
      <h3 class="section-title">开放数据预设（NOAA / NASA / NSIDC / ESA）</h3>
      <p class="section-hint">
        供工作流「门户数据下载」节点使用；可覆盖默认 base URL。
        <span v-if="Object.keys(presetLabels).length"
          >已知键：{{ Object.keys(presetLabels).join(', ') }}</span
        >
      </p>
      <textarea v-model="presetsText" class="code-area" rows="10" spellcheck="false" />
      <button type="button" class="btn" :disabled="saveBusy" @click="savePresets">保存预设</button>
    </section>

    <section class="settings-section">
      <h3 class="section-title">开放门户凭证</h3>
      <p class="section-hint">
        工作流节点填写 <code>cred_profile=earthdata|nsidc|copernicus</code>。 也可设环境变量
        <code>BACKEND_EARTHDATA_TOKEN</code> / <code>BACKEND_NSIDC_TOKEN</code> /
        <code>BACKEND_COPERNICUS_TOKEN</code>（DB 优先）。
      </p>
      <div v-for="id in ['earthdata', 'nsidc', 'copernicus']" :key="id" class="portal-card">
        <div class="portal-head">
          <strong>{{ portalTitles[id] }}</strong>
          <span class="muted">
            {{ portalMeta[id]?.has_token ? '已配置 token' : '无 token' }}
            · 来源 {{ portalMeta[id]?.source || 'none' }}
          </span>
        </div>
        <label class="check-row">
          <input v-model="portalForms[id].enabled" type="checkbox" />
          启用
        </label>
        <div class="info-grid">
          <div class="info-row">
            <span class="info-label">鉴权类型</span>
            <select v-model="portalForms[id].auth_type" class="field">
              <option value="bearer">Bearer token</option>
              <option value="basic">Basic 用户名密码</option>
              <option value="header">自定义 Header</option>
            </select>
          </div>
          <div class="info-row">
            <span class="info-label">用户名</span>
            <input
              v-model="portalForms[id].username"
              class="field"
              type="text"
              autocomplete="off"
            />
          </div>
          <div class="info-row">
            <span class="info-label">Token</span>
            <input
              v-model="portalForms[id].token"
              class="field"
              type="password"
              placeholder="留空则保留原值"
              autocomplete="new-password"
            />
          </div>
          <div class="info-row">
            <span class="info-label">密码</span>
            <input
              v-model="portalForms[id].password"
              class="field"
              type="password"
              placeholder="Basic 时填写"
              autocomplete="new-password"
            />
          </div>
          <div v-if="id === 'copernicus'" class="info-row">
            <span class="info-label">client_id</span>
            <input v-model="portalForms[id].client_id" class="field" type="text" />
          </div>
        </div>
        <label v-if="id === 'earthdata'" class="check-row">
          <input v-model="portalForms[id].use_for_nsidc" type="checkbox" />
          同时用于 NSIDC
        </label>
        <label v-if="id === 'nsidc'" class="check-row">
          <input v-model="portalForms[id].use_earthdata" type="checkbox" />
          无独立凭证时回退 Earthdata
        </label>
        <div class="btn-row">
          <button type="button" class="btn" :disabled="saveBusy" @click="savePortal(id)">
            保存
          </button>
          <button type="button" class="btn danger" :disabled="saveBusy" @click="clearPortal(id)">
            删除
          </button>
        </div>
      </div>
    </section>

    <section class="settings-section">
      <h3 class="section-title">图层 URI 覆盖</h3>
      <p class="section-hint">
        嵌套 JSON，等价 <code>BACKEND_REMOTE_LAYER_DATA_URIS</code>；DB 配置优先于环境变量。
      </p>
      <textarea v-model="urisText" class="code-area" rows="6" spellcheck="false" />
      <button type="button" class="btn" :disabled="saveBusy" @click="saveUris">保存 URI</button>
    </section>

    <section class="settings-section">
      <h3 class="section-title">静态 materialize 缓存</h3>
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
      <div class="btn-row">
        <button type="button" class="btn" :disabled="cacheBusy" @click="refreshCache">刷新</button>
        <button type="button" class="btn danger" :disabled="cacheBusy" @click="handleEvictAll">
          清理缓存
        </button>
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
      {{
        dataSourceConfig?.workflow_hint ||
        '远程存储凭证在「远程存储」页配置；工作流 download 节点可通过 ?cred=profile 引用。'
      }}
    </p>
    <p v-if="statusMsg" class="status-msg">
      {{ statusMsg }}
    </p>
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
  align-items: center;
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

.portal-card {
  border: 1px solid #2a3d52;
  border-radius: 8px;
  padding: 0.65rem 0.75rem;
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
  background: #0d1620;
}

.portal-head {
  display: flex;
  justify-content: space-between;
  gap: 0.5rem;
  color: #e8f3fc;
  font-size: 0.72rem;
}

.check-row {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  color: #c5d6e8;
  font-size: 0.7rem;
}

.field {
  width: 100%;
  box-sizing: border-box;
  border: 1px solid #2a3d52;
  border-radius: 4px;
  background: #0a121a;
  color: #d7e6f5;
  font-size: 0.7rem;
  padding: 0.28rem 0.4rem;
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
}

.btn-row {
  display: flex;
  gap: 0.5rem;
}

.btn {
  border: 1px solid #3a5470;
  background: #1a2a3c;
  color: #e8f3fc;
  border-radius: 6px;
  padding: 0.35rem 0.7rem;
  font-size: 0.7rem;
  cursor: pointer;
}

.btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.btn-primary {
  border-color: #4a7ab0;
  background: #1e3a55;
}

.warn {
  color: #e8b86d;
}

.btn.danger {
  border-color: #7a3a3a;
  background: #3a1a1a;
}

.status-msg {
  margin: 0;
  color: #9fd0a8;
  font-size: 0.7rem;
}
</style>
