<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, toRef } from 'vue'

import { useSettingsStore } from '../../stores/settings'
import { useLayerViewport } from '../../stores/layers/selectors'
import { useWeatherEngineStore } from '../../stores/weather-engine'
import { normalizeWeatherModel } from '../../utils/weather-model'
import { useWeatherSyncStatusStore } from '../../stores/weather-sync-status'
import {
  getWeatherCoverage,
  getWeatherSyncStatus,
  type WeatherCoverage,
  type WeatherSyncOverview,
  type WeatherSyncStatus,
} from '../../services/runtime-api'
import AppSelect from '../ui/AppSelect.vue'

const settingsStore = useSettingsStore()
const weatherSyncStatusStore = useWeatherSyncStatusStore()
const viewport = useLayerViewport()
const weatherEngine = useWeatherEngineStore()
const weatherConfig = toRef(settingsStore, 'weatherConfig')

const FALLBACK_MODELS = [
  { id: 'ecmwf_ifs025', label: 'ECMWF IFS 0.25°', region: 'global', update_interval: '6h' },
  { id: 'gfs_global', label: 'GFS 0.25°', region: 'global', update_interval: '6h' },
  { id: 'icon_global', label: 'ICON 0.25°', region: 'global', update_interval: '6h' },
  { id: 'icon_eu', label: 'ICON-EU', region: 'europe', update_interval: '3h' },
  { id: 'jma_seamless', label: 'JMA', region: 'global', update_interval: '6h' },
  { id: 'meteofrance_seamless', label: 'Météo-France', region: 'global', update_interval: '6h' },
  { id: 'gem_seamless', label: 'GEM', region: 'global', update_interval: '6h' },
]

const modelOptions = computed(() =>
  weatherConfig.value?.supported_models?.length
    ? weatherConfig.value.supported_models
    : FALLBACK_MODELS,
)

const selectedModel = ref('ecmwf_ifs025')
/** One-shot sync domains override (comma-separated); empty = env default */
const triggerDomainsOverride = ref('')
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

const syncDomains = computed(
  () => overview.value?.domains ?? weatherConfig.value?.sync_domains ?? [],
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
  overview.value?.data_mode === 'forecast'
    ? '预报（非历史）'
    : (overview.value?.data_mode ?? '预报'),
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
const VARIABLES_PREVIEW_LIMIT = 8
const syncVariables = computed(() => overview.value?.variables ?? [])
const visibleSyncVariables = computed(() => {
  const vars = syncVariables.value
  if (!vars.length) return [] as string[]
  if (variablesExpanded.value || vars.length <= VARIABLES_PREVIEW_LIMIT) return vars
  return vars.slice(0, VARIABLES_PREVIEW_LIMIT)
})
const hiddenSyncVariableCount = computed(() => {
  const n = syncVariables.value.length - VARIABLES_PREVIEW_LIMIT
  return n > 0 && !variablesExpanded.value ? n : 0
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

const syncServiceAvailable = computed(() => {
  if (!overview.value) return true
  if (typeof overview.value.sync_service_available === 'boolean') {
    return overview.value.sync_service_available
  }
  return Boolean(overview.value.docker_cli_available && overview.value.compose_file_exists)
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
    coverage.value = await getWeatherCoverage(normalizeWeatherModel(selectedModel.value))
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
    selectedModel.value = normalizeWeatherModel(selectedModel.value)
    const updated = await weatherEngine.setDefaultModel(selectedModel.value)
    if (updated.warning === 'not_in_sync_domains') {
      modelUpdateMessage.value =
        '已保存为全局默认模型，但当前不在本地 sync 域内：本地瓦片可能无数据，请先加入 OPEN_METEO_SYNC_DOMAINS 并同步，或改用 Online Provider。'
    } else {
      modelUpdateMessage.value = '已保存：时间轴 / 瓦片 / 点预报将使用此模型。'
    }
    await refreshCoverage()
    await refreshOverview()
    viewport.flushWeatherTileViewports()
  } catch (err) {
    modelUpdateMessage.value = (err as Error).message || '保存失败'
  } finally {
    modelUpdating.value = false
  }
}

async function triggerSync() {
  if (isSyncRunning.value || !syncServiceAvailable.value) return
  syncStatus.value = null
  try {
    const domains = triggerDomainsOverride.value.trim()
    const resp = await weatherSyncStatusStore.triggerSync(domains ? { domains } : undefined)
    syncTaskId.value = resp.task_id
    syncStatus.value = {
      task_id: resp.task_id,
      state: 'STARTED',
      info:
        resp.mode === 'local_thread'
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
            syncStatus.value.error ||
            (typeof syncStatus.value.info === 'string' ? syncStatus.value.info : null) ||
            '同步失败'
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
    } catch {
      /* ignore */
    }
  }
  await weatherEngine.ensureLoaded()
  selectedModel.value = normalizeWeatherModel(weatherConfig.value?.default_model)
  await Promise.all([refreshCoverage(), refreshOverview()])
})

onBeforeUnmount(() => {
  stopPolling()
  // 同时清理 store 层的轮询定时器，防止组件卸载后 store 继续每 3s 轮询
  weatherSyncStatusStore.stopPolling()
})
</script>

<template>
  <section class="open-meteo-sync-settings">
    <header class="section-header">
      <h2>Open-Meteo</h2>
      <p class="section-desc">
        管理<strong>默认天气模型</strong>、本机气象数据<strong>同步</strong>与覆盖情况，以及公网 API
        说明。要开关天气数据源，请到「天气源」。
      </p>
    </header>

    <!-- 全局默认模型 -->
    <div class="channel-card">
      <div class="channel-head">
        <span class="channel-badge badge-global">全局</span>
        <h3>默认天气模型</h3>
      </div>
      <p class="channel-desc">
        全站共用一套默认模型：改完立刻影响时间轴可用时段、天气瓦片与点预报。
      </p>
      <div class="setting-row">
        <label class="row-label">模型</label>
        <AppSelect
          v-model="selectedModel"
          :disabled="modelUpdating"
          :options="
            modelOptions.map((m) => ({
              label: `${m.label}${syncDomains.includes(m.id) ? ' · 本机可同步' : ''}`,
              value: m.id,
            }))
          "
          @change="onModelChange"
        />
      </div>
      <div v-if="selectedModelMeta" class="model-meta">
        <span class="meta-chip">区域: {{ selectedModelMeta.region }}</span>
        <span class="meta-chip">更新间隔: {{ selectedModelMeta.update_interval }}</span>
        <span class="meta-chip" :class="modelInSync ? 'ok' : 'warn'">
          {{ modelInSync ? '本机已配置同步此模型' : '本机同步列表不含此模型' }}
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
        <h3>本机 Open-Meteo</h3>
      </div>
      <p class="channel-desc">
        优先使用本机容器里的气象库（服务名 <code>open-meteo-local</code>）。需先启动
        <code>cgda-open-meteo</code> 容器；拉数任务在
        <code>Code/infra/data-sync</code>（本页「立即同步」或脚本 <code>.\sync.ps1</code>）。要同步哪些模型，由环境变量
        <code>OPEN_METEO_SYNC_DOMAINS</code> 决定（本页只读）。
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
            <span class="coverage-label">Sync 域（只读）</span>
            <span class="coverage-value">{{ (overview.domains || []).join(', ') || '—' }}</span>
          </div>
          <p class="sync-domains-hint">
            长期生效的同步模型列表来自环境变量
            <code>OPEN_METEO_SYNC_DOMAINS</code>（本页改不了）。改完后需重启后端与定时任务，或用下方「本次覆盖域」临时指定一次。
          </p>
          <div class="coverage-row">
            <span class="coverage-label">Docker CLI</span>
            <span class="coverage-value">{{
              overview.docker_cli_available ? '可用' : '不可用'
            }}</span>
          </div>
          <div class="coverage-row">
            <span class="coverage-label">Compose 文件</span>
            <span class="coverage-value">{{ overview.compose_file_exists ? '存在' : '缺失' }}</span>
          </div>
          <div class="coverage-row">
            <span class="coverage-label">同步服务</span>
            <span class="coverage-value" :class="syncServiceAvailable ? 'ok' : 'warn'">
              {{ syncServiceAvailable ? '可用' : '不可用' }}
            </span>
          </div>
          <div class="coverage-row">
            <span class="coverage-label">定时</span>
            <span class="coverage-value">
              {{
                overview.enabled ? `${overview.cron.hour} ${overview.cron.minute} UTC` : '已关闭'
              }}
            </span>
          </div>
          <div class="coverage-row">
            <span class="coverage-label">上次成功</span>
            <span class="coverage-value">{{ overview.last_success_at || '—' }}</span>
          </div>
          <div v-if="overview.last_failure_at" class="coverage-row">
            <span class="coverage-label">上次失败</span>
            <span class="coverage-value">{{
              overview.last_message || overview.last_failure_at
            }}</span>
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
              <template v-if="overview.coverage_error"
                >无数据（{{ overview.coverage_error }}）</template
              >
              <template v-else>{{ overviewCoverageRangeLabel }}</template>
            </span>
          </div>
          <div class="coverage-row coverage-row-wrap">
            <span class="coverage-label">
              同步变量
              <span class="coverage-label-hint">本机 Open-Meteo 已配置拉取的气象量（只读）</span>
            </span>
            <span class="coverage-value var-chip-cloud">
              <template v-if="!syncVariables.length">—</template>
              <template v-else>
                <span v-for="v in visibleSyncVariables" :key="v" class="meta-chip var-chip">{{
                  v
                }}</span>
                <button
                  v-if="hiddenSyncVariableCount > 0"
                  type="button"
                  class="meta-chip var-chip var-chip-more"
                  @click="variablesExpanded = true"
                >
                  +{{ hiddenSyncVariableCount }}
                </button>
                <button
                  v-if="variablesExpanded && syncVariables.length > VARIABLES_PREVIEW_LIMIT"
                  type="button"
                  class="refresh-btn"
                  @click="variablesExpanded = false"
                >
                  收起
                </button>
              </template>
            </span>
          </div>
          <p class="coverage-hint meta-hint">
            同步会尽量拉满该模型能提供的预报时长；地图时间轴上实际能用的时段，以本机探测结果为准（绿/紫色段）。
          </p>
        </div>
        <div v-else class="coverage-loading">刷新状态后显示</div>
      </div>

      <div class="setting-block">
        <div class="block-title">
          <span>本机数据覆盖</span>
          <button
            type="button"
            class="refresh-btn"
            :disabled="coverageLoading"
            @click="refreshCoverage"
          >
            {{ coverageLoading ? '刷新中...' : '刷新' }}
          </button>
        </div>
        <div v-if="coverageError" class="coverage-error">
          {{ coverageError }}
          <span class="coverage-hint">常见原因：本机容器未启动、尚未同步，或当前模型不在同步列表里。</span>
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

      <div v-if="overview && !syncServiceAvailable" class="sync-unavailable-callout">
        同步服务不可用：需要本机已安装并可调用 Docker，且存在
        <code>Code/infra/data-sync/docker-compose.yml</code>。后台任务只负责排队；没有 Docker
        就拉不到本机气象数据。
      </div>

      <div class="setting-block">
        <div class="block-title"><span>手动同步</span></div>
        <div class="setting-row sync-domains-override">
          <label class="row-label">本次覆盖域</label>
          <input
            v-model="triggerDomainsOverride"
            class="model-select"
            type="text"
            placeholder="留空=用环境默认；例 ecmwf_ifs025,gfs_global"
            :disabled="isSyncRunning || !syncServiceAvailable"
          />
        </div>
        <div class="sync-control">
          <button
            type="button"
            class="sync-btn"
            :disabled="isSyncRunning || !syncServiceAvailable"
            @click="triggerSync"
          >
            {{
              !syncServiceAvailable ? '同步服务不可用' : isSyncRunning ? '同步中...' : '立即同步'
            }}
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
          一般走后台任务队列；队列卡住时会改在本进程里跑。需要本机 Docker。整次同步大约 10–30
          分钟，期间仍可看已有旧数据。断网或 Docker 不可用时会写出失败原因。
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
        直连官方公网接口（<code>open-meteo-online</code> / api.open-meteo.com），
        <strong>无需 API Key</strong>。启停、优先级与连通性测试请到「天气源」。公网支持
        <code>best_match</code>；本机源不支持时会自动改用默认模型。
      </p>
      <ul class="online-list">
        <li>免费额度约每日 1 万次请求（以 open-meteo.com 官方限额为准）</li>
        <li>不依赖本机 Docker 同步</li>
        <li>适合本机容器未就绪时的临时回退</li>
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
  color: var(--text-strong);
}

.section-desc {
  margin: 0;
  font-size: var(--font-size-caption);
  line-height: 1.5;
  color: var(--text-muted);
}

.channel-card {
  padding: 0.7rem 0.75rem;
  border: 1px solid var(--border-default);
  border-radius: 0.7rem;
  background: var(--surface-sunken);
}

.channel-head {
  display: flex;
  align-items: center;
  gap: 0.45rem;
  margin-bottom: 0.35rem;
}

.channel-head h3 {
  margin: 0;
  font-size: var(--font-size-caption);
  color: var(--text-strong);
}

.channel-badge {
  padding: 0.12rem 0.4rem;
  border-radius: 999px;
  font-size: var(--font-size-caption);
  font-weight: 700;
  letter-spacing: 0.04em;
}

.badge-global {
  background: var(--success-surface);
  color: var(--success);
}

.badge-local {
  background: var(--accent-surface);
  color: var(--accent);
}

.badge-online {
  background: var(--surface-violet-tint);
  color: var(--accent-strong);
}

.channel-desc {
  margin: 0 0 0.55rem;
  font-size: var(--font-size-caption);
  line-height: 1.5;
  color: var(--text-muted);
}

.channel-desc code,
.sync-hint code,
.section-desc code {
  font-size: var(--font-size-caption);
  color: var(--text-muted);
}

.setting-row {
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
}

.row-label {
  font-size: var(--font-size-caption);
  color: var(--text-secondary);
}

.model-select {
  padding: 0.42rem 0.55rem;
  border: 1px solid var(--border-strong);
  border-radius: 0.42rem;
  background: var(--surface-1);
  color: var(--text-strong);
  font: inherit;
  font-size: var(--font-size-caption);
}

.model-select:focus {
  outline: none;
  border-color: var(--border-strong);
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
  background: var(--accent-surface);
  color: var(--accent);
  font-size: var(--font-size-caption);
}

.meta-chip.ok {
  background: var(--success-surface);
  color: var(--success);
}

.meta-chip.warn {
  background: var(--warning-surface);
  color: var(--accent-warm);
}

.coverage-label-hint {
  display: block;
  margin-top: 0.15rem;
  font-size: 0.7rem;
  font-weight: 400;
  color: var(--text-faint);
  line-height: 1.35;
}

.var-chip-cloud {
  display: flex;
  flex-wrap: wrap;
  gap: 0.3rem;
  align-items: center;
}

.var-chip {
  font-family: var(--font-mono, ui-monospace, monospace);
  font-size: 0.72rem;
  background: var(--surface-2, var(--accent-surface));
  color: var(--text-secondary);
  border: 1px solid var(--border-subtle);
}

.var-chip-more {
  cursor: pointer;
  color: var(--accent);
  background: var(--accent-surface);
  border-color: var(--accent-border);
}

.model-update-hint {
  margin-top: 0.45rem;
  padding: 0.42rem 0.55rem;
  border: 1px solid var(--warning-border);
  border-radius: 0.42rem;
  background: var(--warning-surface);
  color: var(--accent-warm);
  font-size: var(--font-size-caption);
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
  font-size: var(--font-size-caption);
}

.info-label {
  color: var(--text-muted);
}
.info-value {
  color: var(--text-strong);
  font-variant-numeric: tabular-nums;
}

.setting-block {
  padding: 0.55rem 0 0;
  border-top: 1px solid var(--border-subtle);
  margin-top: 0.45rem;
}

.block-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 0.42rem;
  font-size: var(--font-size-caption);
  color: var(--text-secondary);
  font-weight: 600;
}

.refresh-btn {
  padding: 0.2rem 0.55rem;
  border: 1px solid var(--accent-border);
  border-radius: 0.32rem;
  background: var(--accent-surface);
  color: var(--accent);
  cursor: pointer;
  font: inherit;
  font-size: var(--font-size-caption);
}

.refresh-btn:hover:not(:disabled) {
  background: var(--surface-hover);
}
.refresh-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.coverage-error {
  padding: 0.42rem 0.55rem;
  border: 1px solid var(--danger-border);
  border-radius: 0.42rem;
  background: var(--danger-surface);
  color: var(--danger);
  font-size: var(--font-size-caption);
}

.coverage-hint {
  display: block;
  margin-top: 0.25rem;
  color: var(--text-muted);
  font-size: var(--font-size-caption);
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
  font-size: var(--font-size-caption);
}

.coverage-label {
  color: var(--text-muted);
}
.coverage-value {
  color: var(--text-strong);
  font-family: var(--font-mono);
}
.coverage-loading {
  font-size: var(--font-size-caption);
  color: var(--text-faint);
}

.sync-control {
  display: flex;
  align-items: center;
  gap: 0.62rem;
}

.sync-btn {
  padding: 0.36rem 0.75rem;
  border: 1px solid var(--success-border);
  border-radius: 0.42rem;
  background: var(--success-surface);
  color: var(--success);
  cursor: pointer;
  font: inherit;
  font-size: var(--font-size-caption);
}

.sync-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.sync-status {
  display: flex;
  flex-direction: column;
  gap: 0.15rem;
  font-size: var(--font-size-caption);
}
.sync-state {
  color: var(--text-secondary);
}
.state-success {
  color: var(--success);
}
.state-failure {
  color: var(--danger);
}
.state-started,
.state-pending,
.state-retry {
  color: var(--accent);
}
.sync-error {
  color: var(--danger);
}
.sync-hint {
  margin: 0.45rem 0 0;
  font-size: var(--font-size-caption);
  color: var(--text-faint);
  line-height: 1.45;
}

.online-list {
  margin: 0;
  padding-left: 1.1rem;
  color: var(--text-muted);
  font-size: var(--font-size-caption);
  line-height: 1.55;
}

.sync-domains-hint {
  margin: 4px 0 10px;
  font-size: var(--font-size-caption);
  line-height: 1.4;
  color: var(--text-muted);
}
.sync-domains-override {
  margin-bottom: 10px;
}
.sync-unavailable-callout {
  margin: 0 0 12px;
  padding: 8px 10px;
  border-radius: 6px;
  border: 1px solid var(--danger-border);
  background: var(--danger-surface);
  color: var(--text-secondary);
  font-size: 12px;
  line-height: 1.45;
}
.coverage-value.ok {
  color: var(--success);
}
.coverage-value.warn {
  color: var(--warning);
}
</style>
