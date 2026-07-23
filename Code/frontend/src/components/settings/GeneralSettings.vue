<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { useSettingsStore } from '../../stores/settings'
import type { RuntimeConfigPatch } from '../../services/settings-api'

const settingsStore = useSettingsStore()
const { generalConfig } = storeToRefs(settingsStore)

// ── 只读系统信息 ──────────────────────────────────────────────────────────
const readonlyItems = computed(() => {
  if (!generalConfig.value) return []
  const cfg = generalConfig.value
  return [
    { label: '服务名称', value: cfg.service_name },
    { label: '运行环境', value: cfg.environment },
    { label: '监听地址', value: `${cfg.host}:${cfg.port}` },
    { label: '数据根目录', value: cfg.data_root || '未配置' },
    { label: '产物输出目录', value: cfg.output_root || '未配置' },
    { label: '缓存目录', value: cfg.cache_dir },
    { label: '日志目录', value: cfg.log_dir },
    { label: 'Redis 地址', value: cfg.redis_url },
    { label: '存储后端', value: cfg.storage_backend },
    { label: '热重载', value: cfg.reload ? '启用' : '禁用' },
  ]
})

// ── 可编辑运行时参数（热更新） ──────────────────────────────────────────────
const LOG_LEVELS = ['DEBUG', 'INFO', 'WARNING', 'ERROR'] as const
const EXECUTORS = ['celery', 'sync'] as const

interface EditableParam {
  key: string
  label: string
  type: 'select' | 'number'
  options?: readonly string[]
  min: number
  max: number
  unit?: string
  description: string
  group: string
}

const editableParams = computed<EditableParam[]>(() => [
  // 工作流与并发
  {
    key: 'task_executor',
    label: '任务执行器',
    type: 'select',
    options: EXECUTORS,
    min: 0,
    max: 0,
    group: '工作流与并发',
    description: 'celery=异步任务队列，sync=同步执行（调试用）',
  },
  {
    key: 'max_active_runs',
    label: '最大并发工作流',
    type: 'number',
    min: 1,
    max: 16,
    group: '工作流与并发',
    description: '同时运行的业务工作流上限',
  },
  {
    key: 'max_active_weather_tile_runs',
    label: '最大并发天气瓦片',
    type: 'number',
    min: 1,
    max: 64,
    group: '工作流与并发',
    description: '同时运行的天气瓦片工作流上限',
  },
  {
    key: 'max_requested_outputs',
    label: '最大请求输出数',
    type: 'number',
    min: 1,
    max: 20,
    group: '工作流与并发',
    description: '单次工作流最大输出结果数',
  },
  {
    key: 'celery_task_soft_time_limit',
    label: 'Celery 软超时',
    type: 'number',
    min: 60,
    max: 7200,
    unit: '秒',
    group: '工作流与并发',
    description: '任务软时间限制，超时后抛 SoftTimeLimitExceeded',
  },
  {
    key: 'celery_task_time_limit',
    label: 'Celery 硬超时',
    type: 'number',
    min: 120,
    max: 7200,
    unit: '秒',
    group: '工作流与并发',
    description: '任务硬时间限制，超时后强制终止',
  },
  // 缓存与性能
  {
    key: 'cache_default_ttl_seconds',
    label: '通用缓存 TTL',
    type: 'number',
    min: 60,
    max: 86400,
    unit: '秒',
    group: '缓存与性能',
    description: '非天气数据的通用缓存有效期',
  },
  {
    key: 'weather_cache_ttl_seconds',
    label: '天气缓存 TTL',
    type: 'number',
    min: 60,
    max: 86400,
    unit: '秒',
    group: '缓存与性能',
    description: '天气数据缓存有效期',
  },
  {
    key: 'weather_refresh_forecast_hours',
    label: '预报刷新小时数',
    type: 'number',
    min: 1,
    max: 48,
    unit: '小时',
    group: '缓存与性能',
    description: '天气预报数据拉取时长',
  },
  {
    key: 'result_inline_max_bytes',
    label: '内联结果上限',
    type: 'number',
    min: 4096,
    max: 1048576,
    unit: 'B',
    group: '缓存与性能',
    description: '工作流结果内联返回的最大字节数',
  },
  // 数据 Provider
  {
    key: 'provider_max_hotspots',
    label: '最大热点数',
    type: 'number',
    min: 10,
    max: 1000,
    group: '数据 Provider',
    description: '单次查询返回的热点上限',
  },
  {
    key: 'provider_max_series_points',
    label: '最大序列点数',
    type: 'number',
    min: 10,
    max: 500,
    group: '数据 Provider',
    description: '时序数据单次返回点数上限',
  },
  {
    key: 'provider_table_chunk_size',
    label: '表格分块大小',
    type: 'number',
    min: 10,
    max: 500,
    group: '数据 Provider',
    description: '表格数据每块行数',
  },
  {
    key: 'provider_series_chunk_size',
    label: '序列分块大小',
    type: 'number',
    min: 10,
    max: 500,
    group: '数据 Provider',
    description: '序列数据每块点数',
  },
  // 日志
  {
    key: 'log_level',
    label: '日志级别',
    type: 'select',
    options: LOG_LEVELS,
    min: 0,
    max: 0,
    group: '日志与诊断',
    description: '后端日志输出级别，立即生效',
  },
])

/** 按组分类的参数 */
const groupedParams = computed(() => {
  const groups: { name: string; items: EditableParam[] }[] = []
  for (const param of editableParams.value) {
    let g = groups.find((g) => g.name === param.group)
    if (!g) {
      g = { name: param.group, items: [] }
      groups.push(g)
    }
    g.items.push(param)
  }
  return groups
})

const runtimeValues = ref<Record<string, string | number>>({})
const savingKey = ref<string | null>(null)
const saveError = ref<string | null>(null)
const saveSuccess = ref<string | null>(null)

watch(
  generalConfig,
  (cfg) => {
    if (!cfg) return
    runtimeValues.value = {
      log_level: cfg.log_level,
      task_executor: 'celery',
      max_active_runs: cfg.max_active_runs,
      max_active_weather_tile_runs: cfg.max_active_weather_tile_runs ?? 4,
      max_requested_outputs: cfg.max_requested_outputs,
      celery_task_soft_time_limit: cfg.celery_task_soft_time_limit ?? 300,
      celery_task_time_limit: cfg.celery_task_time_limit ?? 360,
      cache_default_ttl_seconds: cfg.cache_default_ttl_seconds ?? 1800,
      weather_cache_ttl_seconds: cfg.weather_cache_ttl_seconds ?? 3600,
      weather_refresh_forecast_hours: cfg.weather_refresh_forecast_hours ?? 6,
      result_inline_max_bytes: cfg.result_inline_max_bytes ?? 131072,
      provider_max_hotspots: cfg.provider_max_hotspots ?? 200,
      provider_max_series_points: cfg.provider_max_series_points ?? 240,
      provider_table_chunk_size: cfg.provider_table_chunk_size ?? 100,
      provider_series_chunk_size: cfg.provider_series_chunk_size ?? 120,
    }
  },
  { immediate: true },
)

async function refreshRuntimeConfig() {
  try {
    const { fetchRuntimeConfig } = await import('../../services/settings-api')
    const snapshot = await fetchRuntimeConfig()
    const backend = snapshot.backend ?? {}
    for (const param of editableParams.value) {
      const v = backend[param.key]
      if (v !== undefined && v !== null) {
        runtimeValues.value[param.key] = typeof v === 'number' ? v : String(v)
      }
    }
  } catch (err) {
    console.warn('[GeneralSettings] refreshRuntimeConfig failed:', err)
  }
}
refreshRuntimeConfig()

async function saveParam(param: EditableParam) {
  savingKey.value = param.key
  saveError.value = null
  saveSuccess.value = null
  try {
    const value = runtimeValues.value[param.key]
    const patch: RuntimeConfigPatch[] = [
      {
        scope: 'backend',
        key: param.key,
        value: value as string | number,
      },
    ]
    const result = await settingsStore.saveRuntimeConfig(patch)
    saveSuccess.value = `${param.label}已更新（${result.applied_count} 项生效）`
    setTimeout(() => {
      saveSuccess.value = null
    }, 3000)
  } catch (err) {
    saveError.value = err instanceof Error ? err.message : String(err)
  } finally {
    savingKey.value = null
  }
}

function saveAll() {
  for (const param of editableParams.value) {
    void saveParam(param)
  }
}

// ── 重启生效参数（只读展示） ──────────────────────────────────────────────
const restartParams = computed(() => {
  if (!generalConfig.value) return []
  const cfg = generalConfig.value
  return [
    {
      label: 'CORS 允许源',
      value: cfg.cors_origins?.join(', ') ?? '默认',
      hint: '修改 BACKEND_CORS_ORIGINS 后重启生效',
    },
    {
      label: '对象存储后端',
      value: cfg.object_store_backend ?? 'local',
      hint: '修改 BACKEND_OBJECT_STORE_BACKEND 后重启生效',
    },
    {
      label: '产物公开基路径',
      value: cfg.object_store_public_base ?? '/artifacts',
      hint: '修改 BACKEND_OBJECT_STORE_PUBLIC_BASE 后重启生效',
    },
    {
      label: '工作流状态目录',
      value: cfg.workflow_state_dir ?? '',
      hint: '修改 BACKEND_WORKFLOW_STATE_DIR 后重启生效',
    },
    {
      label: '产物输出目录',
      value: cfg.result_artifact_dir ?? '',
      hint: '修改 BACKEND_RESULT_ARTIFACT_DIR 后重启生效',
    },
    {
      label: 'Python Provider 根目录',
      value: cfg.python_provider_root ?? '',
      hint: '修改 BACKEND_PYTHON_PROVIDER_ROOT 后重启生效',
    },
    {
      label: 'Python Provider 工作区',
      value: cfg.python_provider_workspace ?? '',
      hint: '修改 BACKEND_PYTHON_PROVIDER_WORKSPACE 后重启生效',
    },
    {
      label: 'Celery Eager 模式',
      value: cfg.celery_task_always_eager ? '是' : '否',
      hint: '修改 BACKEND_CELERY_TASK_ALWAYS_EAGER 后重启生效',
    },
  ]
})
</script>

<template>
  <div class="general-settings">
    <!-- 系统信息 -->
    <section class="settings-section">
      <h3 class="section-title">系统信息</h3>
      <div class="info-grid">
        <div v-for="item in readonlyItems" :key="item.label" class="info-row">
          <span class="info-label">{{ item.label }}</span>
          <span class="info-value" :title="item.value">{{ item.value }}</span>
        </div>
      </div>
    </section>

    <!-- 运行时参数（热更新） -->
    <section class="settings-section">
      <div class="section-header">
        <h3 class="section-title">运行时参数</h3>
        <button class="save-all-btn" @click="saveAll">全部保存</button>
      </div>
      <p class="section-hint">
        以下参数支持热修改，修改后立即生效，无需重启后端。点击保存按钮提交更改。
      </p>
      <div v-for="group in groupedParams" :key="group.name" class="param-group">
        <h4 class="group-title">{{ group.name }}</h4>
        <div class="runtime-grid">
          <div v-for="param in group.items" :key="param.key" class="runtime-row">
            <div class="runtime-label-group">
              <span class="info-label">{{ param.label }}</span>
              <span class="param-desc">{{ param.description }}</span>
            </div>
            <div class="runtime-control-group">
              <select
                v-if="param.type === 'select'"
                v-model="runtimeValues[param.key]"
                class="runtime-select"
                :disabled="savingKey === param.key"
              >
                <option v-for="opt in param.options" :key="opt" :value="opt">{{ opt }}</option>
              </select>
              <input
                v-else
                v-model.number="runtimeValues[param.key]"
                type="number"
                class="runtime-input"
                :min="param.min"
                :max="param.max"
                :disabled="savingKey === param.key"
              />
              <span v-if="param.unit" class="param-unit">{{ param.unit }}</span>
              <button
                class="save-btn"
                :disabled="savingKey === param.key"
                @click="saveParam(param)"
              >
                {{ savingKey === param.key ? '…' : '保存' }}
              </button>
            </div>
          </div>
        </div>
      </div>
      <p v-if="saveError" class="error-msg">{{ saveError }}</p>
      <p v-if="saveSuccess" class="success-msg">{{ saveSuccess }}</p>
    </section>

    <!-- 重启生效参数（只读） -->
    <section class="settings-section">
      <h3 class="section-title">重启生效参数</h3>
      <p class="section-hint">
        以下参数通过环境变量配置，修改后需重启后端服务生效。请在
        <code>.env</code> 文件中修改对应变量。
      </p>
      <div class="info-grid">
        <div v-for="item in restartParams" :key="item.label" class="info-row restart-row">
          <div class="restart-label-group">
            <span class="info-label">{{ item.label }}</span>
            <span class="param-hint">{{ item.hint }}</span>
          </div>
          <span class="info-value" :title="item.value">{{ item.value }}</span>
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.general-settings {
  display: flex;
  flex-direction: column;
  gap: 1.2rem;
}
.settings-section {
  display: flex;
  flex-direction: column;
  gap: 0.52rem;
}
.section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.section-title {
  margin: 0 0 0.32rem;
  color: #e8f3fc;
  font-size: 0.7rem;
  font-weight: 600;
  letter-spacing: 0.02em;
}
.info-grid {
  display: flex;
  flex-direction: column;
  gap: 0.22rem;
}
.info-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 0.62rem;
  padding: 0.36rem 0.52rem;
  border-radius: 0.4rem;
  background: rgba(4, 12, 23, 0.5);
  border: 1px solid rgba(136, 192, 255, 0.06);
}
.info-label {
  color: #8aa8bf;
  font-size: 0.6rem;
  flex: none;
  white-space: nowrap;
}
.info-value {
  color: #d8e6f5;
  font-size: 0.6rem;
  font-family: 'SF Mono', 'Consolas', monospace;
  text-align: right;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
  min-width: 0;
}
.section-hint {
  margin: 0;
  color: #5a7080;
  font-size: 0.54rem;
  line-height: 1.5;
}
.section-hint code {
  background: rgba(136, 192, 255, 0.1);
  padding: 0 0.2rem;
  border-radius: 0.2rem;
  font-size: 0.5rem;
}
.param-group {
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
  margin-top: 0.4rem;
}
.group-title {
  margin: 0 0 0.2rem;
  color: #6a8aa0;
  font-size: 0.54rem;
  font-weight: 500;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}
.runtime-grid {
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
}
.runtime-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 0.62rem;
  padding: 0.36rem 0.52rem;
  border-radius: 0.4rem;
  background: rgba(4, 12, 23, 0.5);
  border: 1px solid rgba(136, 192, 255, 0.06);
}
.runtime-label-group {
  display: flex;
  flex-direction: column;
  gap: 0.1rem;
  flex: 1;
  min-width: 0;
}
.param-desc {
  color: #5a7080;
  font-size: 0.5rem;
  line-height: 1.3;
}
.runtime-control-group {
  display: flex;
  align-items: center;
  gap: 0.32rem;
  flex: none;
}
.runtime-select,
.runtime-input {
  background: rgba(0, 0, 0, 0.4);
  border: 1px solid rgba(136, 192, 255, 0.15);
  border-radius: 0.3rem;
  color: #d8e6f5;
  font-size: 0.58rem;
  font-family: 'SF Mono', 'Consolas', monospace;
  padding: 0.22rem 0.36rem;
  width: 5.5rem;
  outline: none;
  transition: border-color 0.15s;
}
.runtime-select:focus,
.runtime-input:focus {
  border-color: rgba(100, 180, 255, 0.5);
}
.runtime-select:disabled,
.runtime-input:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.param-unit {
  color: #5a7080;
  font-size: 0.52rem;
  flex: none;
}
.save-btn {
  background: rgba(40, 80, 130, 0.6);
  border: 1px solid rgba(136, 192, 255, 0.2);
  border-radius: 0.3rem;
  color: #c8e0f5;
  font-size: 0.54rem;
  padding: 0.22rem 0.48rem;
  cursor: pointer;
  transition: background 0.15s;
  flex: none;
}
.save-btn:hover:not(:disabled) {
  background: rgba(50, 100, 160, 0.7);
}
.save-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
.save-all-btn {
  background: rgba(40, 100, 60, 0.6);
  border: 1px solid rgba(100, 200, 120, 0.2);
  border-radius: 0.3rem;
  color: #c8f0d5;
  font-size: 0.54rem;
  padding: 0.22rem 0.6rem;
  cursor: pointer;
  transition: background 0.15s;
}
.save-all-btn:hover {
  background: rgba(50, 120, 70, 0.7);
}
.restart-row {
  flex-direction: row;
  align-items: center;
}
.restart-label-group {
  display: flex;
  flex-direction: column;
  gap: 0.08rem;
  flex: 1;
  min-width: 0;
}
.param-hint {
  color: #4a6070;
  font-size: 0.46rem;
  line-height: 1.3;
}
.error-msg {
  margin: 0;
  color: #ff7a6a;
  font-size: 0.52rem;
}
.success-msg {
  margin: 0;
  color: #5acf8a;
  font-size: 0.52rem;
}
</style>
