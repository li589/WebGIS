<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { storeToRefs } from 'pinia'
import { useSettingsStore } from '../../stores/settings'
import type { ApiKeyItem } from '../../services/settings-api'
import {
  clearBackendWriteApiKey,
  setBackendWriteApiKey,
} from '../../services/backend-auth'

const settingsStore = useSettingsStore()
const { apiKeys, weatherConfig } = storeToRefs(settingsStore)

const writeKeyDraft = ref('')
function _sessionWriteKeyPresent(): boolean {
  try {
    return Boolean(sessionStorage.getItem('cgda.backend_write_api_key'))
  } catch {
    return false
  }
}
const writeKeySessionSet = ref(_sessionWriteKeyPresent())
const writeKeyFromEnv = computed(() => Boolean((import.meta.env.VITE_BACKEND_API_KEY as string | undefined)?.trim()))
const writeKeyStatus = computed(() => {
  if (writeKeySessionSet.value) return '已配置 session'
  if (writeKeyFromEnv.value) return '可用环境变量 VITE_BACKEND_API_KEY'
  return '未配置'
})

function saveWriteKey() {
  const value = writeKeyDraft.value.trim()
  if (!value) return
  setBackendWriteApiKey(value)
  writeKeyDraft.value = ''
  writeKeySessionSet.value = true
}

function clearWriteKey() {
  clearBackendWriteApiKey()
  writeKeySessionSet.value = false
  writeKeyDraft.value = ''
}

// ── 编辑状态 ──────────────────────────────────────────────────────────────────

interface EditState {
  editing: boolean
  value: string
  saving: boolean
}

const editStates = reactive<Record<string, EditState>>({})
const testingKeys = ref<Set<string>>(new Set())
const testResults = reactive<Record<string, { success: boolean; message: string }>>({})

function getEditState(keyName: string): EditState {
  if (!editStates[keyName]) {
    editStates[keyName] = { editing: false, value: '', saving: false }
  }
  return editStates[keyName]
}

function startEdit(item: ApiKeyItem) {
  const state = getEditState(item.key_name)
  state.editing = true
  state.value = ''
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
    await settingsStore.saveApiKey(item.key_name, {
      key_value: state.value.trim(),
      display_name: item.display_name,
      description: item.description,
    })
    state.editing = false
    state.value = ''
  } catch (e) {
    alert(`保存失败: ${(e as Error).message}`)
  } finally {
    state.saving = false
  }
}

async function runTest(item: ApiKeyItem) {
  testingKeys.value.add(item.key_name)
  try {
    const result = await settingsStore.runApiKeyTest(item.key_name)
    testResults[item.key_name] = { success: result.success, message: result.message }
  } catch (e) {
    testResults[item.key_name] = { success: false, message: (e as Error).message }
  } finally {
    testingKeys.value.delete(item.key_name)
  }
}

async function toggleKey(item: ApiKeyItem) {
  try {
    await settingsStore.toggleApiKeyEnabled(item.key_name, !item.enabled)
  } catch (e) {
    alert(`切换失败: ${(e as Error).message}`)
  }
}

// ── 分组 ─────────────────────────────────────────────────────────────────────

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
    <!-- 底图 API Key -->
    <section class="settings-section">
      <h3 class="section-title">底图服务 API Key</h3>
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
              <span v-if="statusBadge(item)" class="key-badge" :class="statusBadge(item)?.class">
                {{ statusBadge(item)?.text }}
              </span>
              <button
                class="toggle-switch"
                :class="{ on: item.enabled }"
                @click="toggleKey(item)"
                :title="item.enabled ? '点击禁用' : '点击启用'"
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
              <button
                class="action-btn save"
                @click="saveKey(item)"
                :disabled="getEditState(item.key_name).saving || !getEditState(item.key_name).value.trim()"
              >
                {{ getEditState(item.key_name).saving ? '保存中...' : '保存' }}
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
                @click="runTest(item)"
                :disabled="testingKeys.has(item.key_name) || !item.masked_value"
              >
                {{ testingKeys.has(item.key_name) ? '测试中...' : '测试' }}
              </button>
            </template>
          </div>

          <div v-if="testResults[item.key_name]" class="test-result" :class="{ success: testResults[item.key_name].success, fail: !testResults[item.key_name].success }">
            {{ testResults[item.key_name].message }}
          </div>
        </div>
      </div>
    </section>

    <!-- Open-Meteo 天气 API 配置 -->
    <section class="settings-section">
      <h3 class="section-title">Open-Meteo 天气 API</h3>
      <div class="info-grid">
        <div v-for="item in weatherItems" :key="item.label" class="info-row">
          <span class="info-label">{{ item.label }}</span>
          <span class="info-value">{{ item.value }}</span>
        </div>
      </div>
      <p class="section-hint">Open-Meteo 为免费 API，无需 Key。限流参数通过环境变量配置。</p>
    </section>

    <!-- 后端认证 -->
    <section v-if="backendAuthItem" class="settings-section">
      <h3 class="section-title">后端 API 认证</h3>
      <div class="key-card" :class="{ disabled: !backendAuthItem.enabled }">
        <div class="key-card-header">
          <span class="key-name">{{ backendAuthItem.display_name }}</span>
          <button
            class="toggle-switch"
            :class="{ on: backendAuthItem.enabled }"
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
              @click="saveKey(backendAuthItem)"
              :disabled="getEditState(backendAuthItem.key_name).saving || !getEditState(backendAuthItem.key_name).value.trim()"
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
          </template>
        </div>
      </div>
    </section>

    <!-- 浏览器写请求鉴权（sessionStorage / VITE_BACKEND_API_KEY） -->
    <section class="settings-section">
      <h3 class="section-title">浏览器写请求密钥</h3>
      <p class="section-hint">
        设置页与工作流写接口需要带 <code>X-Api-Key</code>。优先使用下方粘贴值（sessionStorage），否则读取
        <code>VITE_BACKEND_API_KEY</code>。当前：{{ writeKeyStatus }}
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
          <button class="action-btn save" :disabled="!writeKeyDraft.trim()" @click="saveWriteKey">保存到会话</button>
          <button class="action-btn cancel" :disabled="!writeKeySessionSet" @click="clearWriteKey">清除会话密钥</button>
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

/* Key 卡片 */
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
  transition: opacity 0.2s ease;
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
}

.key-value {
  flex: 1;
  padding: 0.32rem 0.52rem;
  border-radius: 0.36rem;
  background: rgba(4, 12, 23, 0.6);
  border: 1px solid rgba(136, 192, 255, 0.08);
  color: #d8e6f5;
  font-size: 0.58rem;
  font-family: 'SF Mono', 'Consolas', monospace;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.key-value.empty {
  color: #5a7080;
  font-style: italic;
}

.key-input {
  flex: 1;
  padding: 0.32rem 0.52rem;
  border-radius: 0.36rem;
  background: rgba(4, 12, 23, 0.8);
  border: 1px solid rgba(90, 213, 255, 0.24);
  color: #d8e6f5;
  font-size: 0.58rem;
  font-family: 'SF Mono', 'Consolas', monospace;
  outline: none;
}

.key-input:focus {
  border-color: rgba(90, 213, 255, 0.5);
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
  transition: background 0.2s ease, border-color 0.2s ease;
}

.toggle-switch.on {
  background: rgba(10, 132, 255, 0.4);
  border-color: rgba(90, 213, 255, 0.4);
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
  transition: left 0.2s ease, background 0.2s ease;
}

.toggle-switch.on .toggle-knob {
  left: calc(100% - 0.88rem);
  background: #5ad5ff;
}

/* 信息网格 */
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
}

.info-value {
  color: #d8e6f5;
  font-size: 0.6rem;
  text-align: right;
}

/* 测试结果 */
.test-result {
  margin-top: 0.42rem;
  padding: 0.32rem 0.52rem;
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
</style>
