<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { storeToRefs } from 'pinia'
import { useSettingsStore } from '../../stores/settings'
import type { WeatherProviderItem, WeatherProviderType } from '../../services/settings-api'

const settingsStore = useSettingsStore()
const { weatherProviders, weatherConfig } = storeToRefs(settingsStore)

// ── 状态 ───────────────────────────────────────────────────────────────────

const testingIds = ref<Set<string>>(new Set())
const testResults = reactive<
  Record<string, { success: boolean; message: string; tested_at?: string }>
>({})
const togglingIds = ref<Set<string>>(new Set())
const savingConfigId = ref<string | null>(null)
const savingPriorityId = ref<string | null>(null)
const expandedId = ref<string | null>(null)
const editingConfig = reactive<Record<string, Record<string, string | number | boolean>>>({})
const confirmResetId = ref<string | null>(null)

// ── 类型显示映射 ───────────────────────────────────────────────────────────

const providerTypeMeta: Record<
  WeatherProviderType,
  { label: string; icon: string; class: string }
> = {
  free_api: { label: '免费 API', icon: '🆓', class: 'type-free' },
  commercial_api: { label: '商业 API', icon: '💰', class: 'type-commercial' },
  local_data: { label: '本地数据', icon: '💾', class: 'type-local' },
}

function typeMeta(t: WeatherProviderType) {
  return providerTypeMeta[t] ?? { label: t, icon: '❓', class: 'type-unknown' }
}

/** Open-Meteo 通道标签（避免三条同名混淆） */
function channelBadge(p: WeatherProviderItem): { text: string; class: string } | null {
  if (p.provider_id === 'open-meteo-local') return { text: '本地', class: 'channel-local' }
  if (p.provider_id === 'open-meteo-online') return { text: 'Online', class: 'channel-online' }
  if (p.provider_id === 'open-meteo') return { text: '遗留', class: 'channel-legacy' }
  return null
}

const sortedProviders = computed(() => {
  const rank = (id: string) => {
    if (id === 'open-meteo-local') return 0
    if (id === 'open-meteo-online') return 1
    if (id === 'open-meteo') return 99
    return 10
  }
  return [...weatherProviders.value]
    .filter((p) => p.provider_id !== 'open-meteo')
    .sort((a, b) => rank(a.provider_id) - rank(b.provider_id) || a.priority - b.priority)
})

// ── 状态徽章 ───────────────────────────────────────────────────────────────

function statusBadge(p: WeatherProviderItem): { text: string; class: string } {
  if (!p.enabled) return { text: '已禁用', class: 'badge-disabled' }
  const status = p.status
  if (!status) return { text: '状态未知', class: 'badge-unknown' }
  if (!status.healthy) return { text: '不健康', class: 'badge-fail' }
  if (status.circuit_state === 'open') return { text: '断路器开', class: 'badge-fail' }
  if (status.circuit_state === 'half_open') return { text: '断路器半开', class: 'badge-warn' }
  if (p.last_test_status === 'ok') return { text: '正常', class: 'badge-ok' }
  if (p.last_test_status === 'failed') return { text: '测试失败', class: 'badge-fail' }
  return { text: '未测试', class: 'badge-unknown' }
}

function circuitBadge(state: string | undefined): { text: string; class: string } | null {
  if (!state || state === 'n/a') return null
  const map: Record<string, { text: string; class: string }> = {
    closed: { text: '闭合', class: 'badge-ok' },
    open: { text: '开启', class: 'badge-fail' },
    half_open: { text: '半开', class: 'badge-warn' },
  }
  return map[state] ?? null
}

// ── 操作 ───────────────────────────────────────────────────────────────────

async function runTest(providerId: string) {
  testingIds.value.add(providerId)
  try {
    const result = await settingsStore.runWeatherProviderTest(providerId)
    testResults[providerId] = {
      success: result.success,
      message: result.message,
      tested_at: result.tested_at,
    }
  } catch (e) {
    testResults[providerId] = { success: false, message: (e as Error).message }
  } finally {
    testingIds.value.delete(providerId)
  }
}

async function toggleProvider(p: WeatherProviderItem) {
  togglingIds.value.add(p.provider_id)
  try {
    await settingsStore.toggleWeatherProviderEnabled(p.provider_id, !p.enabled)
  } catch (e) {
    alert(`切换失败: ${(e as Error).message}`)
  } finally {
    togglingIds.value.delete(p.provider_id)
  }
}

async function savePriority(p: WeatherProviderItem, newPriority: number) {
  // 防止 parseInt NaN 或无效值发往后端导致 422
  if (!Number.isFinite(newPriority) || newPriority < 0 || newPriority > 999) {
    alert('优先级必须是 0-999 之间的整数')
    return
  }
  if (newPriority === p.priority) return
  savingPriorityId.value = p.provider_id
  try {
    await settingsStore.updateWeatherProviderPriority(p.provider_id, newPriority)
  } catch (e) {
    alert(`优先级调整失败: ${(e as Error).message}`)
  } finally {
    savingPriorityId.value = null
  }
}

function startEditConfig(p: WeatherProviderItem) {
  // 若当前有其他 Provider 正在编辑且存在未保存更改，提示用户
  if (expandedId.value && expandedId.value !== p.provider_id && editingConfig[expandedId.value]) {
    const confirmed = window.confirm('当前有未保存的配置更改，切换将丢弃这些更改。是否继续？')
    if (!confirmed) return
    delete editingConfig[expandedId.value]
  }
  expandedId.value = p.provider_id
  // 初始化编辑状态：用 current_config 作为初始值
  editingConfig[p.provider_id] = {
    ...(p.persisted_config ?? p.current_config),
  } as Record<string, string | number | boolean>
}

function cancelEditConfig(providerId: string) {
  expandedId.value = null
  delete editingConfig[providerId]
}

async function saveConfig(p: WeatherProviderItem) {
  const cfg = editingConfig[p.provider_id]
  if (!cfg) return
  savingConfigId.value = p.provider_id
  try {
    await settingsStore.saveWeatherProvider(p.provider_id, { config: { ...cfg } })
    expandedId.value = null
    delete editingConfig[p.provider_id]
  } catch (e) {
    alert(`配置保存失败: ${(e as Error).message}`)
  } finally {
    savingConfigId.value = null
  }
}

async function resetConfig(p: WeatherProviderItem) {
  confirmResetId.value = null
  try {
    await settingsStore.removeWeatherProvider(p.provider_id)
    expandedId.value = null
    delete editingConfig[p.provider_id]
  } catch (e) {
    alert(`重置失败: ${(e as Error).message}`)
  }
}

// ── 工具函数 ───────────────────────────────────────────────────────────────

function formatNumber(v: number | null | undefined): string {
  if (v === null || v === undefined) return '—'
  return v.toLocaleString()
}

function formatPercent(used: number | null, quota: number | null): string {
  if (used === null || quota === null || quota === 0) return '—'
  return `${((used / quota) * 100).toFixed(1)}%`
}

function formatTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  try {
    const d = new Date(iso)
    return d.toLocaleString('zh-CN', { hour12: false })
  } catch {
    return iso
  }
}

const enabledCount = computed(() => weatherProviders.value.filter((p) => p.enabled).length)
const healthyCount = computed(() => weatherProviders.value.filter((p) => p.status?.healthy).length)
</script>

<template>
  <div class="weather-provider-settings">
    <!-- 天气引擎概览 -->
    <section v-if="weatherConfig" class="settings-section">
      <h3 class="section-title">天气引擎概览</h3>
      <div class="engine-info">
        <div class="info-row">
          <span class="info-label">默认模型</span>
          <span class="info-value">{{ weatherConfig.default_model }}</span>
        </div>
        <div class="info-row">
          <span class="info-label">缓存 TTL</span>
          <span class="info-value">{{ weatherConfig.cache_ttl_seconds }}s</span>
        </div>
        <div class="info-row">
          <span class="info-label">最大并发瓦片任务</span>
          <span class="info-value">{{ weatherConfig.max_active_weather_tile_runs }}</span>
        </div>
      </div>
    </section>

    <!-- Provider 列表 -->
    <section class="settings-section">
      <div class="section-header">
        <h3 class="section-title">
          天气源 Provider
          <span class="count-badge"
            >{{ enabledCount }}/{{ weatherProviders.length }} 启用 · {{ healthyCount }} 健康</span
          >
        </h3>
        <div class="section-actions">
          <button class="action-btn reload" @click="settingsStore.loadWeatherProviders()">
            刷新
          </button>
        </div>
      </div>

      <p class="section-hint">
        系统按 Provider 优先级（数字越小越优先）路由天气请求。 Open-Meteo
        仅应出现两条：<strong>本地</strong>（open-meteo-local）与
        <strong>Online</strong>（open-meteo-online）。模型与 Docker 同步请到「Open-Meteo」页。
        保存配置后立即作用于后端 registry（可点「测试连通性」验证）。
      </p>

      <!-- 空状态 -->
      <div v-if="sortedProviders.length === 0" class="empty-state">
        <span class="empty-icon">🌦</span>
        <span>暂无天气源 Provider，请检查后端是否正确注册</span>
      </div>

      <!-- Provider 卡片列表 -->
      <div class="provider-list">
        <div
          v-for="p in sortedProviders"
          :key="p.provider_id"
          class="provider-card"
          :class="{ disabled: !p.enabled, expanded: expandedId === p.provider_id }"
        >
          <!-- 卡片头部 -->
          <div class="provider-header">
            <div class="provider-info">
              <div class="provider-title-row">
                <span class="provider-name">{{ p.display_name }}</span>
                <span v-if="channelBadge(p)" class="channel-badge" :class="channelBadge(p)?.class">
                  {{ channelBadge(p)?.text }}
                </span>
                <span class="type-badge" :class="typeMeta(p.provider_type).class">
                  {{ typeMeta(p.provider_type).icon }} {{ typeMeta(p.provider_type).label }}
                </span>
                <span class="key-badge" :class="statusBadge(p).class">
                  {{ statusBadge(p).text }}
                </span>
              </div>
              <div class="provider-id-row">
                <span class="provider-id">{{ p.provider_id }}</span>
                <span class="provider-version">v{{ p.version }}</span>
                <a
                  v-if="p.homepage_url"
                  :href="p.homepage_url"
                  target="_blank"
                  rel="noopener noreferrer"
                  class="provider-link"
                >
                  主页 ↗
                </a>
              </div>
              <p v-if="p.description" class="provider-desc">{{ p.description }}</p>
            </div>

            <div class="provider-controls">
              <button
                class="toggle-switch"
                :class="{ on: p.enabled }"
                @click="toggleProvider(p)"
                :disabled="togglingIds.has(p.provider_id)"
                :title="p.enabled ? '点击禁用' : '点击启用'"
              >
                <span class="toggle-knob"></span>
              </button>
            </div>
          </div>

          <!-- 卡片元数据 -->
          <div class="provider-meta">
            <div class="meta-item">
              <span class="meta-label">优先级</span>
              <span class="meta-value">#{{ p.priority }}</span>
            </div>
            <div class="meta-item">
              <span class="meta-label">能力</span>
              <span class="meta-value">{{ p.supported_capabilities.join(', ') }}</span>
            </div>
            <div class="meta-item">
              <span class="meta-label">需要 API Key</span>
              <span class="meta-value" :class="{ warn: p.requires_api_key }">
                {{ p.requires_api_key ? '是' : '否' }}
              </span>
            </div>
            <div
              v-if="p.status?.circuit_state && p.status.circuit_state !== 'n/a'"
              class="meta-item"
            >
              <span class="meta-label">断路器</span>
              <span class="key-badge" :class="circuitBadge(p.status.circuit_state)?.class">
                {{ circuitBadge(p.status.circuit_state)?.text }}
              </span>
            </div>
          </div>

          <!-- 运行时状态 -->
          <div
            v-if="p.status?.daily_quota !== null && p.status?.daily_quota !== undefined"
            class="provider-runtime"
          >
            <div class="runtime-row">
              <span class="runtime-label">API 预算</span>
              <div class="runtime-bar-wrapper">
                <div class="runtime-bar">
                  <div
                    class="runtime-bar-fill"
                    :class="{
                      warn:
                        p.status.daily_used !== null &&
                        p.status.daily_quota !== null &&
                        p.status.daily_used / p.status.daily_quota > 0.8,
                    }"
                    :style="{ width: formatPercent(p.status.daily_used, p.status.daily_quota) }"
                  ></div>
                </div>
                <span class="runtime-text">
                  {{ formatNumber(p.status.daily_used) }} /
                  {{ formatNumber(p.status.daily_quota) }} (剩
                  {{ formatNumber(p.status.daily_remaining) }})
                </span>
              </div>
            </div>
          </div>

          <!-- 操作按钮 -->
          <div class="provider-actions">
            <button
              class="action-btn test"
              @click="runTest(p.provider_id)"
              :disabled="testingIds.has(p.provider_id)"
            >
              {{ testingIds.has(p.provider_id) ? '测试中...' : '测试连通性' }}
            </button>
            <button
              v-if="expandedId !== p.provider_id"
              class="action-btn config"
              @click="startEditConfig(p)"
            >
              ⚙ 配置
            </button>
            <button v-else class="action-btn cancel" @click="cancelEditConfig(p.provider_id)">
              收起
            </button>
          </div>

          <!-- 测试结果 -->
          <div
            v-if="testResults[p.provider_id]"
            class="test-result"
            :class="{
              success: testResults[p.provider_id].success,
              fail: !testResults[p.provider_id].success,
            }"
          >
            <div>{{ testResults[p.provider_id].message }}</div>
            <div v-if="testResults[p.provider_id].tested_at" class="test-time">
              {{ formatTime(testResults[p.provider_id].tested_at) }}
            </div>
          </div>

          <!-- 上次测试状态 -->
          <div v-if="p.last_tested_at && !testResults[p.provider_id]" class="last-test">
            上次测试: {{ formatTime(p.last_tested_at) }} —
            <span :class="p.last_test_status === 'ok' ? 'text-ok' : 'text-fail'">
              {{ p.last_test_status === 'ok' ? '成功' : '失败' }}
            </span>
          </div>

          <!-- 展开配置区 -->
          <div v-if="expandedId === p.provider_id" class="config-section">
            <h4 class="config-title">配置字段</h4>

            <!-- 优先级编辑 -->
            <div class="form-row">
              <label class="form-label">优先级（数字越小越优先）</label>
              <div class="priority-row">
                <input
                  :value="p.priority"
                  class="form-input priority-input"
                  type="number"
                  min="0"
                  max="999"
                  @change="
                    (e) => savePriority(p, parseInt((e.target as HTMLInputElement).value, 10))
                  "
                  :disabled="savingPriorityId === p.provider_id"
                />
                <span v-if="savingPriorityId === p.provider_id" class="saving-hint">保存中...</span>
              </div>
            </div>

            <!-- 配置字段 -->
            <div v-if="p.config_schema.length > 0">
              <div v-for="field in p.config_schema" :key="field.key" class="form-row">
                <label class="form-label">
                  {{ field.label }}
                  <span v-if="field.required" class="required-mark">*</span>
                </label>
                <input
                  v-if="field.field_type === 'string' || field.field_type === 'password'"
                  v-model="editingConfig[p.provider_id][field.key]"
                  :type="field.field_type === 'password' ? 'password' : 'text'"
                  class="form-input"
                  :placeholder="field.placeholder ?? ''"
                />
                <input
                  v-else-if="field.field_type === 'number'"
                  v-model.number="editingConfig[p.provider_id][field.key]"
                  type="number"
                  class="form-input"
                  :placeholder="field.placeholder ?? ''"
                />
                <input
                  v-else-if="field.field_type === 'boolean'"
                  v-model="editingConfig[p.provider_id][field.key]"
                  type="checkbox"
                  class="form-checkbox"
                />
                <select
                  v-else-if="field.field_type === 'select' && field.options.length > 0"
                  v-model="editingConfig[p.provider_id][field.key]"
                  class="form-input"
                >
                  <option v-for="opt in field.options" :key="opt" :value="opt">{{ opt }}</option>
                </select>
                <textarea
                  v-else
                  v-model="editingConfig[p.provider_id][field.key] as string"
                  class="form-textarea"
                  rows="2"
                ></textarea>
                <p v-if="field.description" class="form-hint">{{ field.description }}</p>
              </div>
            </div>
            <div v-else class="no-config">此 Provider 无可配置项</div>

            <!-- 配置操作 -->
            <div class="config-actions">
              <button
                class="action-btn save"
                @click="saveConfig(p)"
                :disabled="savingConfigId === p.provider_id"
              >
                {{ savingConfigId === p.provider_id ? '保存中...' : '保存配置' }}
              </button>
              <button
                v-if="p.persisted_config"
                class="action-btn delete"
                @click="confirmResetId = confirmResetId === p.provider_id ? null : p.provider_id"
              >
                重置为默认
              </button>
              <button class="action-btn cancel" @click="cancelEditConfig(p.provider_id)">
                取消
              </button>
            </div>

            <!-- 重置确认 -->
            <div v-if="confirmResetId === p.provider_id" class="confirm-reset">
              <span>确认删除 DB 中的自定义配置？将回退到代码默认值。</span>
              <button class="action-btn confirm-delete" @click="resetConfig(p)">确认重置</button>
              <button class="action-btn cancel" @click="confirmResetId = null">取消</button>
            </div>
          </div>

          <!-- 错误信息 -->
          <div v-if="p.status?.last_error" class="provider-error">⚠ {{ p.status.last_error }}</div>
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.weather-provider-settings {
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
  gap: 0.52rem;
  flex-wrap: wrap;
}

.section-title {
  margin: 0;
  color: #e8f3fc;
  font-size: 0.7rem;
  font-weight: 600;
  display: flex;
  align-items: center;
  gap: 0.32rem;
}

.count-badge {
  padding: 0.08rem 0.36rem;
  border-radius: 999px;
  background: rgba(10, 132, 255, 0.2);
  color: #5ad5ff;
  font-size: 0.52rem;
  font-weight: 600;
}

.section-actions {
  display: flex;
  gap: 0.32rem;
}

.section-hint {
  margin: 0;
  color: #5a7080;
  font-size: 0.56rem;
  line-height: 1.5;
}

/* 引擎信息 */
.engine-info {
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
}

.info-value {
  color: #d8e6f5;
  font-size: 0.6rem;
  text-align: right;
}

/* 空状态 */
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.52rem;
  padding: 2rem 1rem;
  color: #5a7080;
  font-size: 0.6rem;
}

.empty-icon {
  font-size: 1.6rem;
  opacity: 0.5;
}

/* Provider 卡片 */
.provider-list {
  display: flex;
  flex-direction: column;
  gap: 0.52rem;
}

.provider-card {
  padding: 0.72rem 0.82rem;
  border-radius: 0.52rem;
  background: rgba(4, 12, 23, 0.5);
  border: 1px solid rgba(136, 192, 255, 0.1);
  transition:
    opacity 0.2s ease,
    border-color 0.2s ease;
}

.provider-card.disabled {
  opacity: 0.55;
}

.provider-card.expanded {
  border-color: rgba(90, 213, 255, 0.3);
}

.provider-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 0.52rem;
  margin-bottom: 0.42rem;
}

.provider-info {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 0.16rem;
}

.provider-title-row {
  display: flex;
  align-items: center;
  gap: 0.42rem;
  flex-wrap: wrap;
}

.provider-name {
  color: #e8f3fc;
  font-size: 0.7rem;
  font-weight: 600;
}

.provider-id-row {
  display: flex;
  align-items: center;
  gap: 0.42rem;
  flex-wrap: wrap;
}

.provider-id {
  color: #5a7080;
  font-size: 0.54rem;
  font-family: 'SF Mono', 'Consolas', monospace;
}

.provider-version {
  color: #5a7080;
  font-size: 0.52rem;
  padding: 0.04rem 0.26rem;
  border-radius: 0.2rem;
  background: rgba(136, 192, 255, 0.08);
}

.provider-link {
  color: #5ad5ff;
  font-size: 0.54rem;
  text-decoration: none;
}

.provider-link:hover {
  text-decoration: underline;
}

.provider-desc {
  margin: 0.18rem 0 0 0;
  color: #8aa8bf;
  font-size: 0.56rem;
  line-height: 1.5;
}

.provider-controls {
  flex: none;
}

/* 元数据 */
.provider-meta {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(6rem, 1fr));
  gap: 0.42rem;
  padding: 0.42rem 0.52rem;
  margin-bottom: 0.42rem;
  border-radius: 0.36rem;
  background: rgba(4, 12, 23, 0.4);
  border: 1px solid rgba(136, 192, 255, 0.06);
}

.meta-item {
  display: flex;
  flex-direction: column;
  gap: 0.1rem;
}

.meta-label {
  color: #5a7080;
  font-size: 0.52rem;
}

.meta-value {
  color: #d8e6f5;
  font-size: 0.58rem;
  font-family: 'SF Mono', 'Consolas', monospace;
}

.meta-value.warn {
  color: #ffcc66;
}

/* 运行时状态 */
.provider-runtime {
  margin-bottom: 0.42rem;
}

.runtime-row {
  display: flex;
  align-items: center;
  gap: 0.52rem;
}

.runtime-label {
  color: #8aa8bf;
  font-size: 0.56rem;
  flex: none;
}

.runtime-bar-wrapper {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 0.42rem;
}

.runtime-bar {
  flex: 1;
  height: 0.36rem;
  border-radius: 999px;
  background: rgba(4, 12, 23, 0.8);
  border: 1px solid rgba(136, 192, 255, 0.1);
  overflow: hidden;
}

.runtime-bar-fill {
  height: 100%;
  background: linear-gradient(90deg, rgba(90, 213, 255, 0.6), rgba(10, 132, 255, 0.8));
  transition: width 0.3s ease;
}

.runtime-bar-fill.warn {
  background: linear-gradient(90deg, rgba(255, 204, 102, 0.6), rgba(255, 100, 100, 0.8));
}

.runtime-text {
  color: #d8e6f5;
  font-size: 0.54rem;
  font-family: 'SF Mono', 'Consolas', monospace;
  flex: none;
}

/* 操作 */
.provider-actions {
  display: flex;
  gap: 0.32rem;
  flex-wrap: wrap;
}

/* 配置区 */
.config-section {
  margin-top: 0.62rem;
  padding: 0.62rem;
  border-radius: 0.4rem;
  background: rgba(4, 12, 23, 0.6);
  border: 1px solid rgba(90, 213, 255, 0.16);
}

.config-title {
  margin: 0 0 0.52rem 0;
  color: #5ad5ff;
  font-size: 0.62rem;
  font-weight: 600;
}

.form-row {
  display: flex;
  flex-direction: column;
  gap: 0.22rem;
  margin-bottom: 0.42rem;
}

.form-label {
  color: #8aa8bf;
  font-size: 0.58rem;
  display: flex;
  align-items: center;
  gap: 0.16rem;
}

.required-mark {
  color: #ff9999;
}

.form-input {
  padding: 0.36rem 0.52rem;
  border-radius: 0.36rem;
  background: rgba(4, 12, 23, 0.8);
  border: 1px solid rgba(136, 192, 255, 0.14);
  color: #d8e6f5;
  font-size: 0.6rem;
  font-family: 'SF Mono', 'Consolas', monospace;
  outline: none;
}

.form-input:focus {
  border-color: rgba(90, 213, 255, 0.4);
}

.priority-input {
  width: 5rem;
}

.priority-row {
  display: flex;
  align-items: center;
  gap: 0.42rem;
}

.saving-hint {
  color: #5ad5ff;
  font-size: 0.54rem;
}

.form-textarea {
  padding: 0.36rem 0.52rem;
  border-radius: 0.36rem;
  background: rgba(4, 12, 23, 0.8);
  border: 1px solid rgba(136, 192, 255, 0.14);
  color: #d8e6f5;
  font-size: 0.56rem;
  font-family: 'SF Mono', 'Consolas', monospace;
  outline: none;
  resize: vertical;
  min-height: 3rem;
}

.form-checkbox {
  width: 1rem;
  height: 1rem;
  accent-color: #5ad5ff;
}

.form-hint {
  margin: 0;
  color: #5a7080;
  font-size: 0.52rem;
  line-height: 1.4;
}

.no-config {
  padding: 0.52rem;
  color: #5a7080;
  font-size: 0.56rem;
  text-align: center;
}

.config-actions {
  display: flex;
  gap: 0.32rem;
  margin-top: 0.42rem;
  flex-wrap: wrap;
}

.confirm-reset {
  display: flex;
  align-items: center;
  gap: 0.42rem;
  margin-top: 0.42rem;
  padding: 0.42rem 0.52rem;
  border-radius: 0.36rem;
  background: rgba(255, 100, 100, 0.08);
  border: 1px solid rgba(255, 100, 100, 0.2);
  color: #ffcccc;
  font-size: 0.56rem;
  flex-wrap: wrap;
}

/* 类型徽章 */
.type-badge {
  padding: 0.08rem 0.32rem;
  border-radius: 0.2rem;
  font-size: 0.52rem;
  font-weight: 600;
}

.type-free {
  background: rgba(114, 255, 207, 0.12);
  color: #9ff8cf;
}

.type-commercial {
  background: rgba(255, 204, 102, 0.12);
  color: #ffcc66;
}

.type-local {
  background: rgba(201, 163, 255, 0.12);
  color: #c9a3ff;
}

.type-unknown {
  background: rgba(136, 192, 255, 0.12);
  color: #8aa8bf;
}

.channel-badge {
  padding: 0.1rem 0.36rem;
  border-radius: 0.26rem;
  font-size: 0.5rem;
  font-weight: 700;
  letter-spacing: 0.03em;
  white-space: nowrap;
}

.channel-local {
  background: rgba(90, 213, 255, 0.14);
  color: #5ad5ff;
}

.channel-online {
  background: rgba(201, 163, 255, 0.14);
  color: #c9a3ff;
}

.channel-legacy {
  background: rgba(255, 138, 138, 0.14);
  color: #ff8a8a;
}

/* 状态徽章 */
.key-badge {
  padding: 0.1rem 0.36rem;
  border-radius: 0.26rem;
  font-size: 0.52rem;
  font-weight: 600;
  white-space: nowrap;
}

.badge-ok {
  background: rgba(114, 255, 207, 0.14);
  color: #9ff8cf;
}

.badge-fail {
  background: rgba(255, 100, 100, 0.14);
  color: #ff9999;
}

.badge-warn {
  background: rgba(255, 204, 102, 0.14);
  color: #ffcc66;
}

.badge-disabled {
  background: rgba(90, 106, 128, 0.2);
  color: #8aa8bf;
}

.badge-unknown {
  background: rgba(201, 163, 255, 0.14);
  color: #c9a3ff;
}

/* 按钮 */
.action-btn {
  padding: 0.26rem 0.62rem;
  border: 1px solid rgba(136, 192, 255, 0.16);
  border-radius: 0.36rem;
  background: transparent;
  color: #8aa8bf;
  cursor: pointer;
  font: inherit;
  font-size: 0.56rem;
  transition: all 0.16s ease;
  white-space: nowrap;
}

.action-btn:hover:not(:disabled) {
  border-color: rgba(90, 213, 255, 0.3);
  color: #5ad5ff;
  background: rgba(10, 132, 255, 0.1);
}

.action-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.action-btn.test {
  border-color: rgba(90, 213, 255, 0.24);
  color: #5ad5ff;
}

.action-btn.config {
  border-color: rgba(201, 163, 255, 0.2);
  color: #c9a3ff;
}

.action-btn.save {
  border-color: rgba(114, 255, 207, 0.24);
  color: #9ff8cf;
}

.action-btn.save:hover:not(:disabled) {
  background: rgba(114, 255, 207, 0.1);
}

.action-btn.cancel {
  border-color: rgba(255, 100, 100, 0.16);
  color: #ff9999;
}

.action-btn.delete {
  border-color: rgba(255, 100, 100, 0.16);
  color: #ff9999;
}

.action-btn.confirm-delete {
  border-color: rgba(255, 77, 77, 0.4);
  color: #ffcccc;
  background: rgba(255, 77, 77, 0.12);
}

.action-btn.reload {
  border-color: rgba(201, 163, 255, 0.2);
  color: #c9a3ff;
}

/* 切换开关 */
.toggle-switch {
  position: relative;
  width: 2rem;
  height: 1.06rem;
  border: 1px solid rgba(136, 192, 255, 0.16);
  border-radius: 999px;
  background: rgba(4, 12, 23, 0.8);
  cursor: pointer;
  padding: 0;
  transition:
    background 0.2s ease,
    border-color 0.2s ease;
  flex: none;
}

.toggle-switch.on {
  background: rgba(10, 132, 255, 0.4);
  border-color: rgba(90, 213, 255, 0.4);
}

.toggle-switch:disabled {
  cursor: not-allowed;
  opacity: 0.5;
}

.toggle-knob {
  position: absolute;
  top: 50%;
  left: 0.16rem;
  width: 0.72rem;
  height: 0.72rem;
  border-radius: 50%;
  background: #8aa8bf;
  transform: translateY(-50%);
  transition:
    left 0.2s ease,
    background 0.2s ease;
}

.toggle-switch.on .toggle-knob {
  left: calc(100% - 0.88rem);
  background: #5ad5ff;
}

/* 测试结果 */
.test-result {
  margin-top: 0.42rem;
  padding: 0.42rem 0.52rem;
  border-radius: 0.36rem;
  font-size: 0.56rem;
  line-height: 1.4;
}

.test-result.success {
  background: rgba(114, 255, 207, 0.08);
  border: 1px solid rgba(114, 255, 207, 0.16);
  color: #9ff8cf;
}

.test-result.fail {
  background: rgba(255, 100, 100, 0.08);
  border: 1px solid rgba(255, 100, 100, 0.16);
  color: #ff9999;
}

.test-time {
  margin-top: 0.16rem;
  font-size: 0.52rem;
  opacity: 0.7;
}

.last-test {
  margin-top: 0.32rem;
  color: #5a7080;
  font-size: 0.52rem;
}

.text-ok {
  color: #9ff8cf;
}

.text-fail {
  color: #ff9999;
}

.provider-error {
  margin-top: 0.42rem;
  padding: 0.32rem 0.52rem;
  border-radius: 0.36rem;
  background: rgba(255, 100, 100, 0.08);
  border: 1px solid rgba(255, 100, 100, 0.16);
  color: #ff9999;
  font-size: 0.54rem;
  line-height: 1.4;
}
</style>
