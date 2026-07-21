<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { storeToRefs } from 'pinia'

import { useSettingsStore } from '../../stores/settings'
import { useWeatherSyncStatusStore } from '../../stores/weather-sync-status'
import {
  getWeatherCoverage,
  getWeatherSyncStatus,
  type WeatherCoverage,
  type WeatherSyncOverview,
  type WeatherSyncStatus,
} from '../../services/runtime-api'

const settingsStore = useSettingsStore()
const weatherSyncStatusStore = useWeatherSyncStatusStore()
const { weatherConfig } = storeToRefs(settingsStore)

const FALLBACK_MODELS = [
  { id: 'ecmwf_ifs025', label: 'ECMWF IFS 0.25°', region: 'global', update_interval: '6h' },
  { id: 'gfs_global', label: 'GFS 0.25°', region: 'global', update_interval: '6h' },
  { id: 'icon_global', label: 'ICON 0.25°', region: 'global', update_interval: '6h' },
  { id: 'icon_eu', label: 'ICON-EU', region: 'europe', update_interval: '3h' },
  { id: 'jma_seamless', label: 'JMA', region: 'global', update_interval: '6h' },
  { id: 'meteofrance_seamless', label: 'Météo-France', region: 'global', update_interval: '6h' },
  { id: 'gem_seamless', label: 'GEM', region: 'global', update_interval: '6h' },
]

const modelOptions = computed(() => weatherConfig.value?.supported_models?.length
  ? weatherConfig.value.supported_models
  : FALLBACK_MODELS)

const selectedModel = ref('ecmwf_ifs025')
const coverage = ref<WeatherCoverage | null>(null)
const coverageLoading = ref(false)
const coverageError = ref<string | null>(null)
const overview = ref<WeatherSyncOverview | null>(null)

const syncTaskId = ref<string | null>(null)
const syncStatus = ref<WeatherSyncStatus | null>(null)
const syncPolling = ref(false)
let syncPollTimer: ReturnType<typeof setInterval> | null = null

const modelUpdating = ref(false)
const modelUpdateMessage = ref<string | null>(null)

const selectedModelMeta = computed(() =>
  modelOptions.value.find((m) => m.id === selectedModel.value),
)

const syncDomains = computed(() =>
  overview.value?.domains ?? weatherConfig.value?.sync_domains ?? [],
)

const modelInSync = computed(() => syncDomains.value.includes(selectedModel.value))

const engineItems = computed(() => {
  const cfg = weatherConfig.value
  if (!cfg) return []
  return [
    { label: '缓存 TTL', value: `${cfg.cache_ttl_seconds} 秒` },
    { label: '刷新周期', value: `${cfg.refresh_forecast_hours} 小时` },
    { label: '定时刷新', value: cfg.schedule_enabled ? '启用' : '禁用' },
    { label: '默认纬度', value: String(cfg.default_latitude) },
    { label: '默认经度', value: String(cfg.default_longitude) },
    { label: '最大并发瓦片', value: String(cfg.max_active_weather_tile_runs) },
  ]
})

const coverageRangeLabel = computed(() => {
  if (!coverage.value) return '未知'
  const start = coverage.value.data_start_iso.replace('T', ' ').slice(0, 16)
  const end = coverage.value.data_end_iso.replace('T', ' ').slice(0, 16)
  return `${start} → ${end}`
})

const coverageValidLabel = computed(() => {
  if (!coverage.value) return '—'
  const valid = coverage.value.valid_hour_count
  const total = coverage.value.hour_count
  if (typeof valid === 'number') return `${valid} / ${total}`
  return String(total)
})

const dataModeLabel = computed(() =>
  overview.value?.data_mode === 'forecast' ? '预报（非历史）' : (overview.value?.data_mode ?? '预报'),
)

const spatialLabel = computed(() => {
  const s = overview.value?.spatial
  if (!s) return '—'
  const scope = s.scope === 'global' ? '全球' : s.scope
  return `${scope} · 原生网格 ${s.native_resolution}`
})

const temporalWindowLabel = computed(() => {
  const t = overview.value?.temporal
  if (!t) return '—'
  return [
    `探针窗口 ${t.probe_forecast_days} 天`,
    `瓦片 hour 上限 ${t.tile_hour_cap}`,
    `运行时请求 ${t.runtime_forecast_days} 天`,
  ].join(' · ')
})

const overviewCoverageRangeLabel = computed(() => {
  const cov = overview.value?.coverage
  if (!cov?.data_start_iso || !cov?.data_end_iso) return '—'
  const start = cov.data_start_iso.replace('T', ' ').slice(0, 16)
  const end = cov.data_end_iso.replace('T', ' ').slice(0, 16)
  return `${start} → ${end}`
})

const variablesExpanded = ref(false)
const variablesPreview = computed(() => {
  const vars = overview.value?.variables ?? []
  if (!vars.length) return '—'
  if (variablesExpanded.value || vars.length <= 8) return vars.join(', ')
  return `${vars.slice(0, 8).join(', ')} …共 ${vars.length} 项`
})

const syncStateLabel = computed(() => {
  const state = syncStatus.value?.state
  if (!state) {
    if (overview.value?.sync_in_progress) return '同步中'
    return '—'
  }
  const map: Record<string, string> = {
    PENDING: '排队中',
    STARTED: '同步中',
    SUCCESS: '已完成',
    FAILURE: '失败',
    RETRY: '重试中',
  }
  return map[state] ?? state
})

const isSyncRunning = computed(() => {
  const state = syncStatus.value?.state
  if (state === 'PENDING' || state === 'STARTED' || state === 'RETRY') return true
  return !!overview.value?.sync_in_progress
})

async function refreshOverview() {
  try {
    await weatherSyncStatusStore.refreshOverview()
    overview.value = weatherSyncStatusStore.overview
  } catch {
    overview.value = null
  }
}

async function refreshCoverage() {
  coverageLoading.value = true
  coverageError.value = null
  try {
    const model =
      !selectedModel.value || selectedModel.value === 'best_match' || selectedModel.value === 'auto'
        ? 'ecmwf_ifs025'
        : selectedModel.value
    coverage.value = await getWeatherCoverage(model)
  } catch (err) {
    coverageError.value = (err as Error).message || '探针失败'
    coverage.value = null
  } finally {
    coverageLoading.value = false
  }
}

async function onModelChange() {
  modelUpdating.value = true
  modelUpdateMessage.value = null
  try {
    const updated = await settingsStore.saveWeatherDefaultModel(selectedModel.value)
    if (updated.warning === 'not_in_sync_domains') {
      modelUpdateMessage.value =
        '已保存为全局默认模型，但当前不在本地 sync 域内：本地瓦片可能无数据，请先加入 OPEN_METEO_SYNC_DOMAINS 并同步，或改用 Online Provider。'
    } else {
      modelUpdateMessage.value = '已保存：时间轴 / 瓦片 / 点预报将使用此模型。'
    }
    await refreshCoverage()
    await refreshOverview()
  } catch (err) {
    modelUpdateMessage.value = (err as Error).message || '保存失败'
  } finally {
    modelUpdating.value = false
  }
}

async function triggerSync() {
  if (isSyncRunning.value) return
  syncStatus.value = null
  try {
    const resp = await weatherSyncStatusStore.triggerSync()
    syncTaskId.value = resp.task_id
    syncStatus.value = {
      task_id: resp.task_id,
      state: 'STARTED',
      info: resp.mode === 'local_thread'
        ? '已在本进程后台启动（Celery 不可用或超时降级）'
        : '已派发 Celery 任务',
      mode: resp.mode,
    }
    overview.value = weatherSyncStatusStore.overview
    startPolling()
  } catch (err) {
    const msg = (err as Error).message || '触发同步失败'
    syncStatus.value = {
      task_id: '',
      state: 'FAILURE',
      info: /超时|timeout|aborted|网络|Failed to fetch/i.test(msg)
        ? `${msg}。请确认后端可达、Docker/Celery 未卡死；稍后重试。`
        : msg,
    }
  }
}

function startPolling() {
  stopPolling()
  if (!syncTaskId.value) return
  syncPolling.value = true
  const poll = async () => {
    if (!syncTaskId.value) return
    try {
      syncStatus.value = await getWeatherSyncStatus(syncTaskId.value)
      if (!isSyncRunning.value) {
        stopPolling()
        if (syncStatus.value?.state === 'SUCCESS') {
          await refreshCoverage()
          await refreshOverview()
        } else if (syncStatus.value?.state === 'FAILURE') {
          const errText =
            syncStatus.value.error
            || (typeof syncStatus.value.info === 'string' ? syncStatus.value.info : null)
            || '同步失败'
          syncStatus.value = { ...syncStatus.value, info: errText }
        }
      }
    } catch (err) {
      const msg = (err as Error)?.message || ''
      if (/网络|超时|Failed to fetch/i.test(msg) && syncStatus.value) {
        syncStatus.value = {
          ...syncStatus.value,
          info: `状态查询异常：${msg}`,
        }
      }
    }
  }
  void poll()
  syncPollTimer = setInterval(poll, 5000)
}

function stopPolling() {
  syncPolling.value = false
  if (syncPollTimer) {
    clearInterval(syncPollTimer)
    syncPollTimer = null
  }
}

onMounted(async () => {
  if (!weatherConfig.value) {
    try {
      await settingsStore.loadAll()
    } catch { /* ignore */ }
  }
  const fromConfig = (weatherConfig.value?.default_model || '').trim()
  // 本地 coverage 不接受 best_match/auto；映射为具体域
  const normalized =
    !fromConfig || fromConfig === 'best_match' || fromConfig === 'auto'
      ? 'ecmwf_ifs025'
      : fromConfig
  selectedModel.value = normalized
  await Promise.all([refreshCoverage(), refreshOverview()])
})

onBeforeUnmount(() => {
  stopPolling()
})
</script>

<template>
  <section class="open-meteo-sync-settings">
    <header class="section-header">
      <h2>Open-Meteo</h2>
      <p class="section-desc">
        在此统一管理<strong>全局默认模型</strong>、
        <strong>本地（Docker）</strong>同步与覆盖探针，以及
        <strong>Online 公网 API</strong>说明。Provider 启停请到「天气源」。
      </p>
    </header>

    <!-- 全局默认模型 -->
    <div class="channel-card">
      <div class="channel-head">
        <span class="channel-badge badge-global">全局</span>
        <h3>默认天气模型</h3>
      </div>
      <p class="channel-desc">写入后端 DB，立即影响时间轴覆盖、瓦片与点预报（全局单模型）。</p>
      <div class="setting-row">
        <label class="row-label">模型</label>
        <select
          v-model="selectedModel"
          class="model-select"
          :disabled="modelUpdating"
          @change="onModelChange"
        >
          <option v-for="m in modelOptions" :key="m.id" :value="m.id">
            {{ m.label }}
            {{ syncDomains.includes(m.id) ? ' · 已在 sync 域' : '' }}
          </option>
        </select>
      </div>
      <div v-if="selectedModelMeta" class="model-meta">
        <span class="meta-chip">区域: {{ selectedModelMeta.region }}</span>
        <span class="meta-chip">更新间隔: {{ selectedModelMeta.update_interval }}</span>
        <span class="meta-chip" :class="modelInSync ? 'ok' : 'warn'">
          {{ modelInSync ? '本地 sync 域含此模型' : '不在本地 sync 域' }}
        </span>
      </div>
      <div v-if="modelUpdateMessage" class="model-update-hint">{{ modelUpdateMessage }}</div>
      <div class="info-grid">
        <div v-for="row in engineItems" :key="row.label" class="info-row">
          <span class="info-label">{{ row.label }}</span>
          <span class="info-value">{{ row.value }}</span>
        </div>
      </div>
    </div>

    <!-- 本地 -->
    <div class="channel-card">
      <div class="channel-head">
        <span class="channel-badge badge-local">本地 Local</span>
        <h3>Docker Open-Meteo</h3>
      </div>
      <p class="channel-desc">
        Provider：<code>open-meteo-local</code>（默认优先）。
        需 backend 已启动 <code>cgda-open-meteo</code>（<code>docker compose -p backend up -d</code>）；
        同步任务在 <code>Code/infra/data-sync</code>（设置页或 <code>.\sync.ps1</code>）。
        同步域由环境变量 <code>OPEN_METEO_SYNC_DOMAINS</code> 决定。
      </p>

      <div class="setting-block">
        <div class="block-title">
          <span>服务状态</span>
          <button type="button" class="refresh-btn" @click="refreshOverview">刷新</button>
        </div>
        <div v-if="overview" class="coverage-info">
          <div class="coverage-row">
            <span class="coverage-label">本地可达</span>
            <span class="coverage-value">{{ overview.local_reachable ? '是' : '否' }}</span>
          </div>
          <div class="coverage-row">
            <span class="coverage-label">Sync 域</span>
            <span class="coverage-value">{{ (overview.domains || []).join(', ') || '—' }}</span>
          </div>
          <div class="coverage-row">
            <span class="coverage-label">定时</span>
            <span class="coverage-value">
              {{ overview.enabled ? `${overview.cron.hour} ${overview.cron.minute} UTC` : '已关闭' }}
            </span>
          </div>
          <div class="coverage-row">
            <span class="coverage-label">上次成功</span>
            <span class="coverage-value">{{ overview.last_success_at || '—' }}</span>
          </div>
          <div v-if="overview.last_failure_at" class="coverage-row">
            <span class="coverage-label">上次失败</span>
            <span class="coverage-value">{{ overview.last_message || overview.last_failure_at }}</span>
          </div>
        </div>
        <div v-else class="coverage-loading">状态未知（overview 不可用）</div>
      </div>

      <div class="setting-block">
        <div class="block-title">
          <span>时空与变量（只读）</span>
        </div>
        <div v-if="overview" class="coverage-info">
          <div class="coverage-row">
            <span class="coverage-label">数据模式</span>
            <span class="coverage-value">{{ dataModeLabel }}</span>
          </div>
          <div class="coverage-row">
            <span class="coverage-label">空间</span>
            <span class="coverage-value">{{ spatialLabel }}</span>
          </div>
          <div class="coverage-row">
            <span class="coverage-label">时间窗口</span>
            <span class="coverage-value">{{ temporalWindowLabel }}</span>
          </div>
          <div class="coverage-row">
            <span class="coverage-label">覆盖范围</span>
            <span class="coverage-value">
              <template v-if="overview.coverage_error">无数据（{{ overview.coverage_error }}）</template>
              <template v-else>{{ overviewCoverageRangeLabel }}</template>
            </span>
          </div>
          <div class="coverage-row coverage-row-wrap">
            <span class="coverage-label">同步变量</span>
            <span class="coverage-value">
              {{ variablesPreview }}
              <button
                v-if="(overview.variables?.length ?? 0) > 8"
                type="button"
                class="refresh-btn"
                @click="variablesExpanded = !variablesExpanded"
              >
                {{ variablesExpanded ? '收起' : '展开' }}
              </button>
            </span>
          </div>
          <p class="coverage-hint meta-hint">
            同步可拉取模型原生预报时效，但前端瓦片 hour 上限与运行时请求窗口更短；时间轴绿/紫以本地探针有效时次为准。
          </p>
        </div>
        <div v-else class="coverage-loading">刷新 overview 后显示</div>
      </div>

      <div class="setting-block">
        <div class="block-title">
          <span>数据覆盖（本地探针）</span>
          <button type="button" class="refresh-btn" :disabled="coverageLoading" @click="refreshCoverage">
            {{ coverageLoading ? '刷新中...' : '刷新' }}
          </button>
        </div>
        <div v-if="coverageError" class="coverage-error">
          {{ coverageError }}
          <span class="coverage-hint">容器未启动、模型未 sync，或选了不在 sync 域的模型。</span>
        </div>
        <div v-else-if="coverage" class="coverage-info">
          <div class="coverage-row">
            <span class="coverage-label">模型</span>
            <span class="coverage-value">{{ coverage.model }}</span>
          </div>
          <div class="coverage-row">
            <span class="coverage-label">有效时间范围</span>
            <span class="coverage-value">{{ coverageRangeLabel }}</span>
          </div>
          <div class="coverage-row">
            <span class="coverage-label">有效/总时次</span>
            <span class="coverage-value">{{ coverageValidLabel }}</span>
          </div>
        </div>
        <div v-else class="coverage-loading">加载中...</div>
      </div>

      <div class="setting-block">
        <div class="block-title"><span>手动同步</span></div>
        <div class="sync-control">
          <button type="button" class="sync-btn" :disabled="isSyncRunning" @click="triggerSync">
            {{ isSyncRunning ? '同步中...' : '立即同步' }}
          </button>
          <div v-if="syncStatus" class="sync-status">
            <span class="sync-state" :class="`state-${syncStatus.state?.toLowerCase()}`">
              {{ syncStateLabel }}
            </span>
            <span v-if="syncStatus.info && syncStatus.state === 'FAILURE'" class="sync-error">
              {{ syncStatus.info }}
            </span>
          </div>
        </div>
        <p class="sync-hint">
          优先 Celery；broker 卡住时自动降级为本进程后台线程。需本机 Docker。
          同步约 10–30 分钟，期间旧数据仍可用。断网或 Docker 不可用时会显示失败原因。
        </p>
      </div>
    </div>

    <!-- Online -->
    <div class="channel-card">
      <div class="channel-head">
        <span class="channel-badge badge-online">Online</span>
        <h3>公网 Open-Meteo API</h3>
      </div>
      <p class="channel-desc">
        Provider：<code>open-meteo-online</code>（api.open-meteo.com）。
        <strong>无需 API Key</strong>。启停 / 优先级 / 连通性测试请到「天气源」页。
        Online 支持 <code>best_match</code>；本地不支持，会自动映射为默认模型。
      </p>
      <ul class="online-list">
        <li>免费额度约每日 1 万次请求（官方限额，以 open-meteo.com 为准）</li>
        <li>不依赖 Docker / Celery sync</li>
        <li>适合本地容器未就绪时的回退</li>
      </ul>
    </div>
  </section>
</template>

<style scoped>
.open-meteo-sync-settings {
  display: flex;
  flex-direction: column;
  gap: 1rem;
  padding: 0.5rem 0;
}

.section-header h2 {
  margin: 0 0 0.4rem;
  font-size: 0.82rem;
  color: #e8f3fc;
}

.section-desc {
  margin: 0;
  font-size: 0.6rem;
  line-height: 1.5;
  color: #8aa8bf;
}

.channel-card {
  padding: 0.7rem 0.75rem;
  border: 1px solid rgba(136, 192, 255, 0.12);
  border-radius: 0.7rem;
  background: rgba(4, 12, 23, 0.35);
}

.channel-head {
  display: flex;
  align-items: center;
  gap: 0.45rem;
  margin-bottom: 0.35rem;
}

.channel-head h3 {
  margin: 0;
  font-size: 0.72rem;
  color: #e8f3fc;
}

.channel-badge {
  padding: 0.12rem 0.4rem;
  border-radius: 999px;
  font-size: 0.5rem;
  font-weight: 700;
  letter-spacing: 0.04em;
}

.badge-global {
  background: rgba(159, 248, 207, 0.14);
  color: #9ff8cf;
}

.badge-local {
  background: rgba(90, 213, 255, 0.14);
  color: #5ad5ff;
}

.badge-online {
  background: rgba(201, 163, 255, 0.14);
  color: #c9a3ff;
}

.channel-desc {
  margin: 0 0 0.55rem;
  font-size: 0.58rem;
  line-height: 1.5;
  color: #8aa8bf;
}

.channel-desc code,
.sync-hint code,
.section-desc code {
  font-size: 0.54rem;
  color: #b7d4ea;
}

.setting-row {
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
}

.row-label {
  font-size: 0.64rem;
  color: #b8cce0;
}

.model-select {
  padding: 0.42rem 0.55rem;
  border: 1px solid rgba(136, 192, 255, 0.2);
  border-radius: 0.42rem;
  background: rgba(8, 17, 31, 0.6);
  color: #e8f3fc;
  font: inherit;
  font-size: 0.66rem;
}

.model-select:focus {
  outline: none;
  border-color: rgba(90, 213, 255, 0.5);
}

.model-meta {
  display: flex;
  gap: 0.4rem;
  flex-wrap: wrap;
  margin-top: 0.4rem;
}

.meta-chip {
  padding: 0.18rem 0.5rem;
  border-radius: 0.32rem;
  background: rgba(10, 132, 255, 0.1);
  color: #5ad5ff;
  font-size: 0.56rem;
}

.meta-chip.ok {
  background: rgba(114, 255, 207, 0.12);
  color: #9ff8cf;
}

.meta-chip.warn {
  background: rgba(255, 196, 120, 0.12);
  color: #ffd38a;
}

.model-update-hint {
  margin-top: 0.45rem;
  padding: 0.42rem 0.55rem;
  border: 1px solid rgba(255, 180, 90, 0.28);
  border-radius: 0.42rem;
  background: rgba(90, 60, 20, 0.2);
  color: #ffd9a8;
  font-size: 0.58rem;
  line-height: 1.5;
}

.info-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0.35rem 0.7rem;
  margin-top: 0.55rem;
}

.info-row {
  display: flex;
  justify-content: space-between;
  gap: 0.4rem;
  font-size: 0.58rem;
}

.info-label { color: #8aa8bf; }
.info-value { color: #e8f3fc; font-variant-numeric: tabular-nums; }

.setting-block {
  padding: 0.55rem 0 0;
  border-top: 1px solid rgba(136, 192, 255, 0.08);
  margin-top: 0.45rem;
}

.block-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 0.42rem;
  font-size: 0.68rem;
  color: #b8cce0;
  font-weight: 600;
}

.refresh-btn {
  padding: 0.2rem 0.55rem;
  border: 1px solid rgba(90, 213, 255, 0.3);
  border-radius: 0.32rem;
  background: rgba(10, 132, 255, 0.1);
  color: #5ad5ff;
  cursor: pointer;
  font: inherit;
  font-size: 0.56rem;
}

.refresh-btn:hover:not(:disabled) { background: rgba(10, 132, 255, 0.2); }
.refresh-btn:disabled { opacity: 0.5; cursor: not-allowed; }

.coverage-error {
  padding: 0.42rem 0.55rem;
  border: 1px solid rgba(255, 100, 100, 0.28);
  border-radius: 0.42rem;
  background: rgba(90, 20, 20, 0.2);
  color: #ffb0b0;
  font-size: 0.6rem;
}

.coverage-hint {
  display: block;
  margin-top: 0.25rem;
  color: #7f96ab;
  font-size: 0.58rem;
}

.meta-hint {
  margin: 0.35rem 0 0;
  line-height: 1.4;
}

.coverage-row-wrap .coverage-value {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.35rem;
}

.coverage-info {
  display: flex;
  flex-direction: column;
  gap: 0.32rem;
}

.coverage-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 0.62rem;
}

.coverage-label { color: #8aa8bf; }
.coverage-value { color: #e8f3fc; font-family: monospace; }
.coverage-loading { font-size: 0.6rem; color: #6e8ba0; }

.sync-control {
  display: flex;
  align-items: center;
  gap: 0.62rem;
}

.sync-btn {
  padding: 0.36rem 0.75rem;
  border: 1px solid rgba(114, 255, 207, 0.3);
  border-radius: 0.42rem;
  background: rgba(114, 255, 207, 0.1);
  color: #9ff8cf;
  cursor: pointer;
  font: inherit;
  font-size: 0.62rem;
}

.sync-btn:disabled { opacity: 0.5; cursor: not-allowed; }

.sync-status { display: flex; flex-direction: column; gap: 0.15rem; font-size: 0.58rem; }
.sync-state { color: #b8cce0; }
.state-success { color: #9ff8cf; }
.state-failure { color: #ff8a8a; }
.state-started, .state-pending, .state-retry { color: #5ad5ff; }
.sync-error { color: #ffb0b0; }
.sync-hint { margin: 0.45rem 0 0; font-size: 0.54rem; color: #6e8ba0; line-height: 1.45; }

.online-list {
  margin: 0;
  padding-left: 1.1rem;
  color: #8aa8bf;
  font-size: 0.58rem;
  line-height: 1.55;
}
</style>
