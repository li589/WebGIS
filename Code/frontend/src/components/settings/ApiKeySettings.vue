<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { storeToRefs } from 'pinia'
import { useSettingsStore } from '../../stores/settings'
import type { ApiKeyHistoryItem, ApiKeyItem } from '../../services/settings-api'
import {
  clearBackendWriteApiKey,
  hasBackendWriteApiKey,
  setBackendWriteApiKey,
} from '../../services/backend-auth'
import {
  clearAllSettingsLocalPrefs,
  getApiKeyPref,
  patchApiKeyPref,
} from '../../services/settings-local'

const settingsStore = useSettingsStore()
const { apiKeys, weatherConfig, apiKeyHistory } = storeToRefs(settingsStore)

const writeKeyDraft = ref('')
const writeKeyLocalSet = ref(hasBackendWriteApiKey())
const writeKeyFromEnv = computed(() => Boolean((import.meta.env.VITE_BACKEND_API_KEY as string | undefined)?.trim()))
const writeKeyStatus = computed(() => {
  if (writeKeyLocalSet.value) return '已保存到本机 localStorage'
  if (writeKeyFromEnv.value) return '可用环境变量 VITE_BACKEND_API_KEY'
  return '未配置'
})

function saveWriteKey() {
  const value = writeKeyDraft.value.trim()
  if (!value) return
  setBackendWriteApiKey(value)
  writeKeyDraft.value = ''
  writeKeyLocalSet.value = true
}

function clearWriteKey() {
  clearBackendWriteApiKey()
  writeKeyLocalSet.value = false
  writeKeyDraft.value = ''
}

function clearLocalPrefsOnly() {
  clearAllSettingsLocalPrefs()
  for (const k of Object.keys(historyOpen)) historyOpen[k] = false
  alert('已清除本机设置偏好（未删除服务端密钥历史，也未清除写请求密钥）')
}

interface EditState {
  editing: boolean
  value: string
  label: string
  saving: boolean
}

const editStates = reactive<Record<string, EditState>>({})
const testingKeys = ref<Set<string>>(new Set())
const testResults = reactive<Record<string, { success: boolean; message: string }>>({})
const historyOpen = reactive<Record<string, boolean>>({})
const historyLoading = reactive<Record<string, boolean>>({})
const historyBusy = reactive<Record<string, boolean>>({})

function getEditState(keyName: string): EditState {
  if (!editStates[keyName]) {
    const pref = getApiKeyPref(keyName)
    editStates[keyName] = { editing: false, value: '', label: pref.lastLabel || '', saving: false }
  }
  return editStates[keyName]
}

function startEdit(item: ApiKeyItem) {
  const state = getEditState(item.key_name)
  state.editing = true
  state.value = ''
  state.label = getApiKeyPref(item.key_name).lastLabel || ''
}

function cancelEdit(keyName: string) {
  const state = getEditState(keyName)
  state.editing = false
  state.value = ''
}

async function saveKey(item: ApiKeyItem) {
  const state = getEditState(item.key_name)
  if (!state.value.trim()) return
  state.saving = true
  try {
    const label = state.label.trim() || null
    await settingsStore.saveApiKey(item.key_name, {
      key_value: state.value.trim(),
      display_name: item.display_name,
      description: item.description,
      enabled: true,
      history_label: label,
    })
    if (label) patchApiKeyPref(item.key_name, { lastLabel: label })
    state.editing = false
    state.value = ''
    if (historyOpen[item.key_name]) {
      await settingsStore.loadApiKeyHistory(item.key_name)
    }
  } catch (e) {
    alert(formatWriteError('保存失败', e))
  } finally {
    state.saving = false
  }
}

async function runTest(item: ApiKeyItem) {
  if (!canToggle(item)) {
    alert('请先保存 API Key 后再测试')
    return
  }
  testingKeys.value.add(item.key_name)
  try {
    const result = await settingsStore.runApiKeyTest(item.key_name)
    testResults[item.key_name] = { success: result.success, message: result.message }
  } catch (e) {
    testResults[item.key_name] = { success: false, message: formatWriteError('测试失败', e) }
  } finally {
    testingKeys.value.delete(item.key_name)
  }
}

function canToggle(item: ApiKeyItem): boolean {
  return Boolean(item.has_value ?? item.masked_value)
}

function sourceBadge(item: ApiKeyItem): string | null {
  if (item.source === 'env') return '环境变量'
  if (item.source === 'db') return '已保存'
  return null
}

function formatWriteError(prefix: string, e: unknown): string {
  const msg = e instanceof Error ? e.message : String(e)
  if (/401|Invalid API key|未授权|Unauthorized/i.test(msg)) {
    return `${prefix}: 写接口需要 X-Api-Key。请在下方「浏览器写请求密钥」粘贴与 BACKEND_API_KEY / backend_auth 一致的密钥。`
  }
  return `${prefix}: ${msg}`
}

async function toggleKey(item: ApiKeyItem) {
  if (!canToggle(item)) {
    alert('请先点击「编辑」保存 API Key，再启用')
    return
  }
  try {
    await settingsStore.toggleApiKeyEnabled(item.key_name, !item.enabled)
  } catch (e) {
    alert(formatWriteError('切换失败', e))
  }
}

async function toggleHistory(item: ApiKeyItem) {
  const open = !historyOpen[item.key_name]
  historyOpen[item.key_name] = open
  patchApiKeyPref(item.key_name, { collapsedHistory: !open })
  if (open) {
    historyLoading[item.key_name] = true
    try {
      await settingsStore.loadApiKeyHistory(item.key_name)
    } catch (e) {
      alert(formatWriteError('加载历史失败', e))
    } finally {
      historyLoading[item.key_name] = false
    }
  }
}

function historyRows(keyName: string): ApiKeyHistoryItem[] {
  return apiKeyHistory.value[keyName] ?? []
}

async function restoreHistory(item: ApiKeyItem, historyId: number) {
  historyBusy[item.key_name] = true
  try {
    await settingsStore.restoreApiKeyFromHistory(item.key_name, historyId)
    patchApiKeyPref(item.key_name, { lastRestoredHistoryId: historyId })
  } catch (e) {
    alert(formatWriteError('恢复失败', e))
  } finally {
    historyBusy[item.key_name] = false
  }
}

async function deleteHistory(item: ApiKeyItem, historyId: number) {
  if (!confirm(`删除历史记录 #${historyId}？`)) return
  historyBusy[item.key_name] = true
  try {
    await settingsStore.removeApiKeyHistoryEntry(item.key_name, historyId)
  } catch (e) {
    alert(formatWriteError('删除失败', e))
  } finally {
    historyBusy[item.key_name] = false
  }
}

async function clearHistory(item: ApiKeyItem) {
  if (!confirm(`清空「${item.display_name}」的全部密钥历史？`)) return
  historyBusy[item.key_name] = true
  try {
    await settingsStore.clearApiKeyHistoryFor(item.key_name)
  } catch (e) {
    alert(formatWriteError('清空失败', e))
  } finally {
    historyBusy[item.key_name] = false
  }
}

function sourceLabel(source: string): string {
  if (source === 'restore') return '恢复'
  if (source === 'env_materialize') return '环境变量物化'
  return '用户保存'
}

const apiKeyItems = computed(() => apiKeys.value.filter((k) => k.key_name !== 'backend_auth'))
const backendAuthItem = computed(() => apiKeys.value.find((k) => k.key_name === 'backend_auth'))

const weatherItems = computed(() => {
  if (!weatherConfig.value) return []
  const cfg = weatherConfig.value
  return [
    { label: '天气模型', value: cfg.default_model },
    { label: '缓存 TTL', value: `${cfg.cache_ttl_seconds} 秒` },
    { label: '刷新周期', value: `${cfg.refresh_forecast_hours} 小时` },
    { label: '定时刷新', value: cfg.schedule_enabled ? '启用' : '禁用' },
    { label: '默认纬度', value: cfg.default_latitude.toString() },
    { label: '默认经度', value: cfg.default_longitude.toString() },
    { label: '默认地名', value: cfg.default_place_name },
    { label: '最大并发瓦片', value: cfg.max_active_weather_tile_runs.toString() },
  ]
})

function statusBadge(item: ApiKeyItem): { text: string; class: string } | null {
  if (!item.last_tested_at) return null
  if (item.last_test_status === 'ok') return { text: '已验证', class: 'badge-ok' }
  if (item.last_test_status === 'failed') return { text: '验证失败', class: 'badge-fail' }
  return null
}
</script>

<template>
  <div class="api-key-settings">
    <section class="settings-section">
      <h3 class="section-title">底图服务 API Key</h3>
      <p class="section-hint">
        天地图 / 百度需配置并<strong>启用</strong>后，工具栏对应底图才会可切换。
        轮换 Key 时旧值会进入服务端加密历史，可一键恢复。本机偏好（折叠状态、最近备注）保存在浏览器 localStorage。
      </p>
      <div class="key-card-list">
        <div
          v-for="item in apiKeyItems"
          :key="item.key_name"
          class="key-card"
          :class="{ disabled: !item.enabled }"
        >
          <div class="key-card-header">
            <span class="key-name">{{ item.display_name }}</span>
            <div class="key-badges">
              <span v-if="sourceBadge(item)" class="key-badge badge-source">{{ sourceBadge(item) }}</span>
              <span v-if="statusBadge(item)" class="key-badge" :class="statusBadge(item)?.class">
                {{ statusBadge(item)?.text }}
              </span>
              <button
                class="toggle-switch"
                :class="{ on: item.enabled, locked: !canToggle(item) }"
                :disabled="!canToggle(item)"
                :title="!canToggle(item) ? '请先保存 API Key' : (item.enabled ? '点击禁用' : '点击启用')"
                @click="toggleKey(item)"
              >
                <span class="toggle-knob"></span>
              </button>
            </div>
          </div>
          <p class="key-desc">{{ item.description }}</p>

          <div class="key-input-area">
            <template v-if="getEditState(item.key_name).editing">
              <input
                v-model="getEditState(item.key_name).value"
                class="key-input"
                type="text"
                placeholder="输入新的 API Key..."
                :disabled="getEditState(item.key_name).saving"
              />
              <input
                v-model="getEditState(item.key_name).label"
                class="key-input label-input"
                type="text"
                placeholder="历史备注（可选）"
                :disabled="getEditState(item.key_name).saving"
              />
              <button
                class="action-btn save"
                :disabled="getEditState(item.key_name).saving || !getEditState(item.key_name).value.trim()"
                @click="saveKey(item)"
              >
                {{ getEditState(item.key_name).saving ? '保存中...' : '保存并启用' }}
              </button>
              <button class="action-btn cancel" @click="cancelEdit(item.key_name)">取消</button>
            </template>
            <template v-else>
              <span class="key-value" :class="{ empty: !item.masked_value }">
                {{ item.masked_value || '未配置' }}
              </span>
              <button class="action-btn edit" @click="startEdit(item)">编辑</button>
              <button
                class="action-btn test"
                :disabled="testingKeys.has(item.key_name) || !canToggle(item)"
                @click="runTest(item)"
              >
                {{ testingKeys.has(item.key_name) ? '测试中...' : '测试' }}
              </button>
              <button class="action-btn edit" @click="toggleHistory(item)">
                {{ historyOpen[item.key_name] ? '收起历史' : '历史' }}
              </button>
            </template>
          </div>

          <div
            v-if="testResults[item.key_name]"
            class="test-result"
            :class="{ success: testResults[item.key_name].success, fail: !testResults[item.key_name].success }"
          >
            {{ testResults[item.key_name].message }}
          </div>

          <div v-if="historyOpen[item.key_name]" class="history-panel">
            <div class="history-head">
              <span>密钥历史（脱敏）</span>
              <button
                class="action-btn cancel"
                :disabled="historyBusy[item.key_name] || historyRows(item.key_name).length === 0"
                @click="clearHistory(item)"
              >
                清空
              </button>
            </div>
            <p v-if="historyLoading[item.key_name]" class="history-empty">加载中…</p>
            <p v-else-if="historyRows(item.key_name).length === 0" class="history-empty">暂无历史版本</p>
            <ul v-else class="history-list">
              <li v-for="row in historyRows(item.key_name)" :key="row.id" class="history-row">
                <div class="history-meta">
                  <code>{{ row.masked_value }}</code>
                  <span>{{ row.label || '无备注' }}</span>
                  <span>{{ sourceLabel(row.source) }}</span>
                  <span>{{ row.superseded_at }}</span>
                </div>
                <div class="history-actions">
                  <button
                    class="action-btn save"
                    :disabled="historyBusy[item.key_name]"
                    @click="restoreHistory(item, row.id)"
                  >
                    恢复
                  </button>
                  <button
                    class="action-btn cancel"
                    :disabled="historyBusy[item.key_name]"
                    @click="deleteHistory(item, row.id)"
                  >
                    删除
                  </button>
                </div>
              </li>
            </ul>
          </div>
        </div>
      </div>
    </section>

    <section class="settings-section">
      <h3 class="section-title">Open-Meteo 天气 API</h3>
      <div class="info-grid">
        <div v-for="row in weatherItems" :key="row.label" class="info-row">
          <span class="info-label">{{ row.label }}</span>
          <span class="info-value">{{ row.value }}</span>
        </div>
      </div>
      <p class="section-hint">Open-Meteo 为免费 API，无需 Key。限流参数通过环境变量配置。</p>
    </section>

    <section v-if="backendAuthItem" class="settings-section">
      <h3 class="section-title">后端 API 认证</h3>
      <div class="key-card" :class="{ disabled: !backendAuthItem.enabled }">
        <div class="key-card-header">
          <span class="key-name">{{ backendAuthItem.display_name }}</span>
          <button
            class="toggle-switch"
            :class="{ on: backendAuthItem.enabled, locked: !canToggle(backendAuthItem) }"
            :disabled="!canToggle(backendAuthItem)"
            :title="!canToggle(backendAuthItem) ? '请先保存认证 Key' : (backendAuthItem.enabled ? '点击禁用' : '点击启用')"
            @click="toggleKey(backendAuthItem)"
          >
            <span class="toggle-knob"></span>
          </button>
        </div>
        <p class="key-desc">{{ backendAuthItem.description }}</p>
        <div class="key-input-area">
          <template v-if="getEditState(backendAuthItem.key_name).editing">
            <input
              v-model="getEditState(backendAuthItem.key_name).value"
              class="key-input"
              type="text"
              placeholder="输入新的认证 Key..."
              :disabled="getEditState(backendAuthItem.key_name).saving"
            />
            <button
              class="action-btn save"
              :disabled="getEditState(backendAuthItem.key_name).saving || !getEditState(backendAuthItem.key_name).value.trim()"
              @click="saveKey(backendAuthItem)"
            >
              {{ getEditState(backendAuthItem.key_name).saving ? '保存中...' : '保存' }}
            </button>
            <button class="action-btn cancel" @click="cancelEdit(backendAuthItem.key_name)">取消</button>
          </template>
          <template v-else>
            <span class="key-value" :class="{ empty: !backendAuthItem.masked_value }">
              {{ backendAuthItem.masked_value || '未配置' }}
            </span>
            <button class="action-btn edit" @click="startEdit(backendAuthItem)">编辑</button>
            <button class="action-btn edit" @click="toggleHistory(backendAuthItem)">
              {{ historyOpen[backendAuthItem.key_name] ? '收起历史' : '历史' }}
            </button>
          </template>
        </div>
        <div v-if="historyOpen[backendAuthItem.key_name]" class="history-panel">
          <p v-if="historyLoading[backendAuthItem.key_name]" class="history-empty">加载中…</p>
          <p v-else-if="historyRows(backendAuthItem.key_name).length === 0" class="history-empty">暂无历史版本</p>
          <ul v-else class="history-list">
            <li v-for="row in historyRows(backendAuthItem.key_name)" :key="row.id" class="history-row">
              <div class="history-meta">
                <code>{{ row.masked_value }}</code>
                <span>{{ row.superseded_at }}</span>
              </div>
              <div class="history-actions">
                <button class="action-btn save" @click="restoreHistory(backendAuthItem, row.id)">恢复</button>
                <button class="action-btn cancel" @click="deleteHistory(backendAuthItem, row.id)">删除</button>
              </div>
            </li>
          </ul>
        </div>
      </div>
    </section>

    <section class="settings-section">
      <h3 class="section-title">浏览器写请求密钥</h3>
      <p class="section-hint">
        设置页与工作流写接口需要带 <code>X-Api-Key</code>。值保存在本机 <code>localStorage</code>（兼容旧 sessionStorage）。
        当前：{{ writeKeyStatus }}
      </p>
      <div class="key-card">
        <div class="key-input-area">
          <input
            v-model="writeKeyDraft"
            class="key-input"
            type="password"
            autocomplete="new-password"
            placeholder="粘贴与后端 BACKEND_API_KEY / backend_auth 一致的密钥"
          />
          <button class="action-btn save" :disabled="!writeKeyDraft.trim()" @click="saveWriteKey">保存到本机</button>
          <button class="action-btn cancel" :disabled="!writeKeyLocalSet" @click="clearWriteKey">清除本机密钥</button>
          <button class="action-btn edit" @click="clearLocalPrefsOnly">清除本机偏好</button>
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.api-key-settings {
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
.section-hint {
  margin: 0;
  color: #5a7080;
  font-size: 0.54rem;
  line-height: 1.5;
}
.section-hint code {
  color: #9ec9ff;
}
.key-card-list {
  display: flex;
  flex-direction: column;
  gap: 0.52rem;
}
.key-card {
  padding: 0.62rem 0.72rem;
  border-radius: 0.52rem;
  background: rgba(4, 12, 23, 0.5);
  border: 1px solid rgba(136, 192, 255, 0.1);
}
.key-card.disabled {
  opacity: 0.5;
}
.key-card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 0.52rem;
  margin-bottom: 0.32rem;
}
.key-name {
  color: #e8f3fc;
  font-size: 0.66rem;
  font-weight: 600;
}
.key-badges {
  display: flex;
  align-items: center;
  gap: 0.42rem;
}
.key-badge {
  padding: 0.1rem 0.36rem;
  border-radius: 0.26rem;
  font-size: 0.52rem;
  font-weight: 600;
}
.badge-ok {
  background: rgba(114, 255, 207, 0.14);
  color: #9ff8cf;
}
.badge-fail {
  background: rgba(255, 100, 100, 0.14);
  color: #ff9999;
}
.badge-source {
  background: rgba(136, 192, 255, 0.12);
  color: #9ec9ff;
}
.key-desc {
  margin: 0 0 0.42rem;
  color: #5a7080;
  font-size: 0.56rem;
  line-height: 1.4;
}
.key-input-area {
  display: flex;
  align-items: center;
  gap: 0.32rem;
  flex-wrap: wrap;
}
.key-value {
  flex: 1;
  min-width: 8rem;
  padding: 0.32rem 0.52rem;
  border-radius: 0.36rem;
  background: rgba(4, 12, 23, 0.6);
  border: 1px solid rgba(136, 192, 255, 0.08);
  color: #d8e6f5;
  font-size: 0.58rem;
  font-family: 'SF Mono', 'Consolas', monospace;
}
.key-value.empty {
  color: #5a7080;
  font-style: italic;
}
.key-input {
  flex: 1;
  min-width: 7rem;
  padding: 0.32rem 0.52rem;
  border-radius: 0.36rem;
  background: rgba(4, 12, 23, 0.8);
  border: 1px solid rgba(90, 213, 255, 0.24);
  color: #d8e6f5;
  font-size: 0.58rem;
  font-family: 'SF Mono', 'Consolas', monospace;
  outline: none;
}
.label-input {
  flex: 0.7;
  min-width: 5rem;
}
.action-btn {
  padding: 0.26rem 0.62rem;
  border: 1px solid rgba(136, 192, 255, 0.16);
  border-radius: 0.36rem;
  background: transparent;
  color: #8aa8bf;
  cursor: pointer;
  font: inherit;
  font-size: 0.56rem;
  white-space: nowrap;
}
.action-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.action-btn.save {
  border-color: rgba(114, 255, 207, 0.24);
  color: #9ff8cf;
}
.action-btn.cancel {
  border-color: rgba(255, 100, 100, 0.16);
  color: #ff9999;
}
.toggle-switch {
  position: relative;
  width: 2rem;
  height: 1.06rem;
  border: 1px solid rgba(136, 192, 255, 0.16);
  border-radius: 999px;
  background: rgba(4, 12, 23, 0.8);
  cursor: pointer;
  padding: 0;
}
.toggle-switch.on {
  background: rgba(10, 132, 255, 0.4);
  border-color: rgba(90, 213, 255, 0.4);
}
.toggle-switch.locked,
.toggle-switch:disabled {
  opacity: 0.45;
  cursor: not-allowed;
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
  transition: left 0.2s ease;
}
.toggle-switch.on .toggle-knob {
  left: calc(100% - 0.88rem);
  background: #5ad5ff;
}
.info-grid {
  display: flex;
  flex-direction: column;
  gap: 0.22rem;
}
.info-row {
  display: flex;
  justify-content: space-between;
  gap: 0.62rem;
  padding: 0.36rem 0.52rem;
  border-radius: 0.4rem;
  background: rgba(4, 12, 23, 0.5);
  border: 1px solid rgba(136, 192, 255, 0.06);
}
.info-label {
  color: #8aa8bf;
  font-size: 0.6rem;
}
.info-value {
  color: #d8e6f5;
  font-size: 0.6rem;
}
.test-result {
  margin-top: 0.42rem;
  padding: 0.32rem 0.52rem;
  border-radius: 0.36rem;
  font-size: 0.56rem;
}
.test-result.success {
  background: rgba(114, 255, 207, 0.08);
  color: #9ff8cf;
}
.test-result.fail {
  background: rgba(255, 100, 100, 0.08);
  color: #ff9999;
}
.history-panel {
  margin-top: 0.5rem;
  padding-top: 0.45rem;
  border-top: 1px solid rgba(136, 192, 255, 0.1);
}
.history-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  color: #8aa8bf;
  font-size: 0.54rem;
  margin-bottom: 0.36rem;
}
.history-empty {
  margin: 0;
  color: #5a7080;
  font-size: 0.54rem;
}
.history-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.36rem;
}
.history-row {
  display: flex;
  justify-content: space-between;
  gap: 0.4rem;
  align-items: center;
  padding: 0.36rem 0.42rem;
  border-radius: 0.36rem;
  background: rgba(2, 8, 16, 0.55);
}
.history-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 0.36rem;
  color: #8aa0b4;
  font-size: 0.52rem;
}
.history-meta code {
  color: #cfe6ff;
}
.history-actions {
  display: flex;
  gap: 0.28rem;
}
</style>
