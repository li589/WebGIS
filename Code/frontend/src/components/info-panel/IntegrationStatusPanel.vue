<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import {
  listEnabledBasemapProviders,
  listEnabledExternalApis,
  listEnabledGeeAccounts,
  loadUnifiedIntegrationConfig,
  type BasemapProviderConfig,
  type ExternalApiConfig,
  type UnifiedIntegrationConfig,
} from '../../services/api-config'

const config = ref<UnifiedIntegrationConfig | null>(null)
const loading = ref(false)
const lastError = ref<string | null>(null)

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' ? (value as Record<string, unknown>) : {}
}

function readBoolean(value: unknown, fallback = false) {
  return typeof value === 'boolean' ? value : fallback
}

function readString(value: unknown, fallback = '—') {
  return typeof value === 'string' && value.trim().length > 0 ? value : fallback
}

function readNumber(value: unknown, fallback = 0) {
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback
}

function readArray(value: unknown) {
  return Array.isArray(value) ? value : []
}

function hasRuntimeSnapshotForProvider(provider: { metadata?: Record<string, unknown> }) {
  const metadata = asRecord(provider.metadata)
  return (
    typeof metadata.runtimeProviderId === 'string' || typeof metadata.runtimeEnabled === 'boolean'
  )
}

const basemapProviders = computed(() => config.value?.basemaps ?? [])
const externalApis = computed(() => config.value?.externalApis ?? [])
const geeConfig = computed(() => config.value?.gee ?? null)

const enabledBasemapProviders = computed(() =>
  config.value ? listEnabledBasemapProviders(config.value) : [],
)
const enabledExternalApis = computed(() =>
  config.value ? listEnabledExternalApis(config.value) : [],
)
const enabledGeeAccounts = computed(() =>
  config.value ? listEnabledGeeAccounts(config.value) : [],
)

const hasRuntimeSnapshot = computed(() => {
  if (!config.value) return false
  if (basemapProviders.value.some((provider) => hasRuntimeSnapshotForProvider(provider)))
    return true
  if (externalApis.value.some((api) => hasRuntimeSnapshotForProvider(api))) return true
  const geeMetadata = asRecord(geeConfig.value?.metadata)
  return (
    typeof geeMetadata.geeAvailable === 'boolean' || typeof geeMetadata.storageBackend === 'string'
  )
})

const geeStatusSummary = computed(() => {
  const gee = geeConfig.value
  if (!gee) return null

  const metadata = asRecord(gee.metadata)
  const concurrencyStats = asRecord(metadata.concurrencyStats)

  return {
    enabled: gee.enabled,
    moduleRoot: gee.moduleRoot ?? '—',
    storageBackend: readString(metadata.storageBackend),
    geeAvailable: readBoolean(metadata.geeAvailable),
    encryptionEnabled:
      readBoolean(metadata.credentialsEncryptionEnabled) ||
      readBoolean(metadata.credentialsEncryptionKeySet),
    activeExports: readNumber(concurrencyStats.active_exports),
    activeUploads: readNumber(concurrencyStats.active_uploads),
    activeDownloads: readNumber(concurrencyStats.active_downloads),
    queuedTasks: readNumber(concurrencyStats.queued_tasks),
    runtimeResolvedCredentialsDbPath: readString(metadata.runtimeResolvedCredentialsDbPath),
  }
})

function describeProviderRuntimeState(provider: BasemapProviderConfig | ExternalApiConfig) {
  const metadata = asRecord(provider.metadata)
  const enabled = readBoolean(
    metadata.runtimeEnabled,
    provider.endpoints.some((endpoint) => endpoint.enabled),
  )
  const authConfigured = readBoolean(metadata.runtimeAuthConfigured)
  const runtimeCapabilities = readArray(metadata.runtimeCapabilities)
  const providerDisplayName = 'provider' in provider ? provider.provider : provider.label

  return {
    enabled,
    authConfigured,
    runtimeEndpointUrl: readString(metadata.runtimeEndpointUrl),
    runtimeProviderName: readString(metadata.runtimeProviderName, providerDisplayName),
    runtimePriority:
      typeof metadata.runtimePriority === 'number' && Number.isFinite(metadata.runtimePriority)
        ? metadata.runtimePriority
        : null,
    runtimeCapabilities: runtimeCapabilities.map((item) => String(item)),
  }
}

async function refreshConfig() {
  loading.value = true
  lastError.value = null
  try {
    config.value = await loadUnifiedIntegrationConfig()
  } catch (error) {
    lastError.value = error instanceof Error ? error.message : '统一配置状态读取失败'
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  void refreshConfig()
})
</script>

<template>
  <section class="integration-card">
    <div class="integration-head">
      <div>
        <span class="info-kicker">统一配置</span>
        <h3>接入状态面板</h3>
      </div>
      <div class="integration-actions">
        <span class="integration-source" :class="{ runtime: hasRuntimeSnapshot }">
          {{ hasRuntimeSnapshot ? '运行时快照' : '模板配置' }}
        </span>
        <button class="refresh-btn" :disabled="loading" @click="refreshConfig">
          {{ loading ? '刷新中...' : '刷新' }}
        </button>
      </div>
    </div>

    <p class="integration-summary">
      底图 Provider {{ enabledBasemapProviders.length }} 个，外部 API
      {{ enabledExternalApis.length }} 个， GEE 账户 {{ enabledGeeAccounts.length }} 个。
    </p>

    <div v-if="lastError" class="integration-error">{{ lastError }}</div>

    <div v-if="config" class="integration-grid">
      <article class="integration-block">
        <div class="block-head">
          <strong>底图 Provider</strong>
          <span>{{ basemapProviders.length }} 个</span>
        </div>
        <ul class="status-list">
          <li v-for="provider in basemapProviders" :key="provider.id">
            <div class="status-main">
              <strong>{{ provider.label }}</strong>
              <span
                class="status-pill"
                :class="{ ok: describeProviderRuntimeState(provider).enabled }"
              >
                {{ describeProviderRuntimeState(provider).enabled ? '启用' : '停用' }}
              </span>
            </div>
            <div class="status-meta">
              <span>{{ provider.coordinateSystem ?? '未声明坐标系' }}</span>
              <span>{{ provider.endpoints.length }} 个端点</span>
              <span>{{
                describeProviderRuntimeState(provider).authConfigured ? '认证已配置' : '认证待配置'
              }}</span>
            </div>
          </li>
        </ul>
      </article>

      <article class="integration-block">
        <div class="block-head">
          <strong>外部 API</strong>
          <span>{{ externalApis.length }} 个</span>
        </div>
        <ul class="status-list">
          <li v-for="api in externalApis" :key="api.id">
            <div class="status-main">
              <strong>{{ api.label }}</strong>
              <span class="status-pill" :class="{ ok: describeProviderRuntimeState(api).enabled }">
                {{ describeProviderRuntimeState(api).enabled ? '启用' : '停用' }}
              </span>
            </div>
            <div class="status-meta">
              <span>{{ api.domain }}</span>
              <span>{{ api.capabilities.join(' / ') }}</span>
              <span>优先级 {{ describeProviderRuntimeState(api).runtimePriority ?? '—' }}</span>
            </div>
          </li>
        </ul>
      </article>

      <article v-if="geeStatusSummary" class="integration-block gee-block">
        <div class="block-head">
          <strong>GEE</strong>
          <span class="status-pill" :class="{ ok: geeStatusSummary.enabled }">
            {{ geeStatusSummary.enabled ? '已启用' : '未启用' }}
          </span>
        </div>
        <div class="gee-grid">
          <div>
            <span>运行状态</span>
            <strong>{{ geeStatusSummary.geeAvailable ? '可用' : '不可用' }}</strong>
          </div>
          <div>
            <span>模块根目录</span>
            <strong>{{ geeStatusSummary.moduleRoot }}</strong>
          </div>
          <div>
            <span>存储后端</span>
            <strong>{{ geeStatusSummary.storageBackend }}</strong>
          </div>
          <div>
            <span>凭据加密</span>
            <strong>{{ geeStatusSummary.encryptionEnabled ? '已开启' : '未开启' }}</strong>
          </div>
          <div>
            <span>活跃导出</span>
            <strong>{{ geeStatusSummary.activeExports }}</strong>
          </div>
          <div>
            <span>活跃下载</span>
            <strong>{{ geeStatusSummary.activeDownloads }}</strong>
          </div>
          <div>
            <span>活跃上传</span>
            <strong>{{ geeStatusSummary.activeUploads }}</strong>
          </div>
          <div>
            <span>排队任务</span>
            <strong>{{ geeStatusSummary.queuedTasks }}</strong>
          </div>
        </div>
        <p class="gee-note">凭据库路径：{{ geeStatusSummary.runtimeResolvedCredentialsDbPath }}</p>
      </article>
    </div>
  </section>
</template>

<style scoped>
.integration-card {
  display: grid;
  gap: 0.38rem;
  padding: 0.46rem 0.5rem;
  border-radius: 0.82rem;
  background: linear-gradient(180deg, rgba(10, 24, 42, 0.72), rgba(8, 18, 33, 0.58));
  border: 1px solid rgba(103, 212, 255, 0.14);
}

.integration-head {
  display: flex;
  justify-content: space-between;
  gap: 0.48rem;
  align-items: flex-start;
}

.integration-head h3 {
  margin: 0.08rem 0 0;
  font-size: 0.68rem;
  color: #f0f7ff;
}

.integration-actions {
  display: flex;
  align-items: center;
  gap: 0.26rem;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.integration-source,
.status-pill {
  padding: 0.12rem 0.34rem;
  border-radius: 999px;
  background: rgba(148, 163, 184, 0.12);
  color: #bfd3e6;
  font-size: 0.52rem;
}

.integration-source.runtime,
.status-pill.ok {
  background: rgba(114, 255, 207, 0.12);
  color: #9ff8cf;
}

.refresh-btn {
  border: 1px solid rgba(103, 212, 255, 0.2);
  border-radius: 999px;
  background: rgba(29, 78, 216, 0.16);
  color: #d8f3ff;
  font-size: 0.56rem;
  padding: 0.22rem 0.56rem;
  cursor: pointer;
}

.refresh-btn:disabled {
  opacity: 0.6;
  cursor: wait;
}

.integration-summary,
.gee-note {
  margin: 0;
  color: #9eb3c8;
  font-size: 0.56rem;
  line-height: 1.45;
}

.integration-error {
  padding: 0.34rem 0.42rem;
  border-radius: 0.62rem;
  background: rgba(255, 80, 80, 0.1);
  border: 1px solid rgba(255, 80, 80, 0.16);
  color: #ffb3b3;
  font-size: 0.56rem;
}

.integration-grid {
  display: grid;
  gap: 0.32rem;
}

.integration-block {
  display: grid;
  gap: 0.24rem;
  padding: 0.38rem 0.42rem;
  border-radius: 0.72rem;
  background: rgba(8, 18, 33, 0.5);
  border: 1px solid rgba(136, 192, 255, 0.08);
}

.block-head {
  display: flex;
  justify-content: space-between;
  gap: 0.4rem;
  align-items: center;
}

.block-head strong {
  color: #edf6ff;
  font-size: 0.6rem;
}

.block-head span {
  color: #7f93a9;
  font-size: 0.52rem;
}

.status-list {
  display: grid;
  gap: 0.18rem;
  margin: 0;
  padding: 0;
  list-style: none;
}

.status-list li {
  display: grid;
  gap: 0.12rem;
  padding: 0.26rem 0.3rem;
  border-radius: 0.56rem;
  background: rgba(148, 163, 184, 0.05);
  border: 1px solid rgba(148, 163, 184, 0.08);
}

.status-main {
  display: flex;
  justify-content: space-between;
  gap: 0.34rem;
  align-items: center;
}

.status-main strong {
  color: #eaf3fb;
  font-size: 0.58rem;
}

.status-meta {
  display: flex;
  gap: 0.32rem;
  flex-wrap: wrap;
  color: #8ea3b8;
  font-size: 0.52rem;
}

.gee-block {
  border-color: rgba(114, 255, 207, 0.12);
}

.gee-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0.22rem 0.42rem;
}

.gee-grid div {
  display: grid;
  gap: 0.04rem;
}

.gee-grid span {
  color: #7f93a9;
  font-size: 0.52rem;
}

.gee-grid strong {
  color: #edf6ff;
  font-size: 0.6rem;
  word-break: break-word;
}
</style>
