<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { storeToRefs } from 'pinia'
import { useSettingsStore } from '../../stores/settings'
import type { GeeAccountItem } from '../../services/settings-api'

const settingsStore = useSettingsStore()
const { geeAccounts, geeRuntimeConfig } = storeToRefs(settingsStore)

// ── 添加账户表单 ────────────────────────────────────────────────────────────

const showAddForm = ref(false)
const addForm = reactive({
  account_id: '',
  sa_json_text: '',
  display_name: '',
  saving: false,
  error: '' as string,
})

function openAddForm() {
  showAddForm.value = true
  addForm.account_id = ''
  addForm.sa_json_text = ''
  addForm.display_name = ''
  addForm.error = ''
}

function closeAddForm() {
  showAddForm.value = false
}

function handleFileUpload(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  const reader = new FileReader()
  reader.onload = (e) => {
    addForm.sa_json_text = e.target?.result as string
    // 尝试从 JSON 中提取 client_email 作为 account_id 建议
    try {
      const parsed = JSON.parse(addForm.sa_json_text)
      if (parsed.client_email && !addForm.account_id) {
        addForm.account_id = parsed.client_email.split('@')[0] || ''
      }
      if (parsed.client_email && !addForm.display_name) {
        addForm.display_name = parsed.client_email
      }
    } catch {
      // JSON 解析失败，用户可手动修改
    }
  }
  reader.readAsText(file)
}

async function submitAddForm() {
  addForm.error = ''
  if (!addForm.account_id.trim()) {
    addForm.error = '请输入账户 ID'
    return
  }
  let saJson: Record<string, unknown>
  try {
    saJson = JSON.parse(addForm.sa_json_text)
  } catch {
    addForm.error = 'service_account JSON 格式无效'
    return
  }
  // 验证必要字段
  const required = ['client_email', 'private_key', 'private_key_id']
  const missing = required.filter((f) => !saJson[f])
  if (missing.length > 0) {
    addForm.error = `JSON 缺少必要字段: ${missing.join(', ')}`
    return
  }

  addForm.saving = true
  try {
    await settingsStore.addGeeAccount({
      account_id: addForm.account_id.trim(),
      service_account_json: saJson,
      display_name: addForm.display_name.trim() || undefined,
    })
    closeAddForm()
  } catch (e) {
    addForm.error = (e as Error).message
  } finally {
    addForm.saving = false
  }
}

// ── 账户操作 ────────────────────────────────────────────────────────────────

const testingAccounts = ref<Set<string>>(new Set())
const testResults = reactive<Record<string, { success: boolean; message: string }>>({})
const deletingAccounts = ref<Set<string>>(new Set())
const confirmDelete = ref<string | null>(null)
const reloading = ref(false)
const reloadResult = ref<{ success: boolean; message: string } | null>(null)

async function runTest(accountId: string) {
  testingAccounts.value.add(accountId)
  try {
    const result = await settingsStore.runGeeAccountTest(accountId)
    testResults[accountId] = { success: result.success, message: result.message }
  } catch (e) {
    testResults[accountId] = { success: false, message: (e as Error).message }
  } finally {
    testingAccounts.value.delete(accountId)
  }
}

async function toggleAccount(account: GeeAccountItem) {
  try {
    await settingsStore.toggleGeeAccountEnabled(account.account_id, !account.enabled)
  } catch (e) {
    alert(`切换失败: ${(e as Error).message}`)
  }
}

async function deleteAccount(accountId: string) {
  deletingAccounts.value.add(accountId)
  try {
    await settingsStore.removeGeeAccount(accountId)
    confirmDelete.value = null
  } catch (e) {
    alert(`删除失败: ${(e as Error).message}`)
  } finally {
    deletingAccounts.value.delete(accountId)
  }
}

async function reloadPool() {
  reloading.value = true
  reloadResult.value = null
  try {
    const result = await settingsStore.reloadGeePool()
    reloadResult.value = { success: result.success, message: result.message }
  } catch (e) {
    reloadResult.value = { success: false, message: (e as Error).message }
  } finally {
    reloading.value = false
  }
}

function statusBadge(account: GeeAccountItem): { text: string; class: string } {
  if (!account.enabled) return { text: '已禁用', class: 'badge-disabled' }
  if (!account.last_tested_at) return { text: '未测试', class: 'badge-unknown' }
  if (account.last_test_status === 'ok') return { text: '有效', class: 'badge-ok' }
  if (account.last_test_status === 'failed') return { text: '无效', class: 'badge-fail' }
  return { text: '未知', class: 'badge-unknown' }
}

const enabledCount = computed(() => geeAccounts.value.filter((a) => a.enabled).length)
</script>

<template>
  <div class="gee-account-settings">
    <!-- GEE 引擎状态 -->
    <section v-if="geeRuntimeConfig" class="settings-section">
      <h3 class="section-title">GEE 引擎状态</h3>
      <div class="engine-info">
        <div class="info-row">
          <span class="info-label">引擎状态</span>
          <span class="info-value" :class="{ active: geeRuntimeConfig.gee_enabled }">
            {{ geeRuntimeConfig.gee_enabled ? '启用' : '禁用' }}
          </span>
        </div>
        <div class="info-row">
          <span class="info-label">加密存储</span>
          <span class="info-value">{{
            geeRuntimeConfig.credentials_encryption_enabled ? '已启用' : '未启用'
          }}</span>
        </div>
        <div class="info-row">
          <span class="info-label">API 管理</span>
          <span class="info-value">{{
            geeRuntimeConfig.api_account_management_enabled ? '允许' : '禁止'
          }}</span>
        </div>
      </div>
    </section>

    <!-- 账户管理 -->
    <section class="settings-section">
      <div class="section-header">
        <h3 class="section-title">
          GEE 账户
          <span class="count-badge">{{ enabledCount }}/{{ geeAccounts.length }}</span>
        </h3>
        <div class="section-actions">
          <button class="action-btn reload" @click="reloadPool" :disabled="reloading">
            {{ reloading ? '重载中...' : '重载账户池' }}
          </button>
          <button class="action-btn add" @click="openAddForm" v-if="!showAddForm">
            + 添加账户
          </button>
        </div>
      </div>

      <!-- 重载结果 -->
      <div
        v-if="reloadResult"
        class="test-result"
        :class="{ success: reloadResult.success, fail: !reloadResult.success }"
      >
        {{ reloadResult.message }}
      </div>

      <!-- 添加表单 -->
      <div v-if="showAddForm" class="add-form">
        <div class="form-row">
          <label class="form-label">账户 ID</label>
          <input
            v-model="addForm.account_id"
            class="form-input"
            type="text"
            placeholder="自定义账户标识，如 my-gee-account"
          />
        </div>
        <div class="form-row">
          <label class="form-label">显示名称（可选）</label>
          <input
            v-model="addForm.display_name"
            class="form-input"
            type="text"
            placeholder="默认使用 client_email"
          />
        </div>
        <div class="form-row">
          <label class="form-label">Service Account JSON</label>
          <textarea
            v-model="addForm.sa_json_text"
            class="form-textarea"
            placeholder="粘贴 service_account JSON 内容，或点击下方上传文件..."
            rows="8"
          ></textarea>
        </div>
        <div class="form-row">
          <label class="form-label">或上传 .json 文件</label>
          <input
            type="file"
            accept=".json,application/json"
            @change="handleFileUpload"
            class="form-file"
          />
        </div>
        <div v-if="addForm.error" class="form-error">{{ addForm.error }}</div>
        <div class="form-actions">
          <button class="action-btn save" @click="submitAddForm" :disabled="addForm.saving">
            {{ addForm.saving ? '保存中...' : '保存账户' }}
          </button>
          <button class="action-btn cancel" @click="closeAddForm">取消</button>
        </div>
      </div>

      <!-- 账户列表 -->
      <div v-if="geeAccounts.length === 0 && !showAddForm" class="empty-state">
        <span class="empty-icon">🌍</span>
        <span>暂无 GEE 账户，点击"添加账户"开始配置</span>
      </div>

      <div class="account-list">
        <div
          v-for="account in geeAccounts"
          :key="account.account_id"
          class="account-card"
          :class="{ disabled: !account.enabled }"
        >
          <div class="account-header">
            <div class="account-info">
              <span class="account-id">{{ account.account_id }}</span>
              <span v-if="account.display_name" class="account-email">{{
                account.display_name
              }}</span>
            </div>
            <div class="account-badges">
              <span class="key-badge" :class="statusBadge(account).class">
                {{ statusBadge(account).text }}
              </span>
              <button
                class="toggle-switch"
                :class="{ on: account.enabled }"
                @click="toggleAccount(account)"
                :title="account.enabled ? '点击禁用' : '点击启用'"
              >
                <span class="toggle-knob"></span>
              </button>
            </div>
          </div>

          <div class="account-meta">
            <span v-if="account.project_id" class="meta-item">项目: {{ account.project_id }}</span>
            <span class="meta-item">类型: {{ account.account_type }}</span>
          </div>

          <div class="account-actions">
            <button
              class="action-btn test"
              @click="runTest(account.account_id)"
              :disabled="testingAccounts.has(account.account_id)"
            >
              {{ testingAccounts.has(account.account_id) ? '测试中...' : '测试' }}
            </button>
            <button
              v-if="confirmDelete !== account.account_id"
              class="action-btn delete"
              @click="confirmDelete = account.account_id"
            >
              删除
            </button>
            <template v-else>
              <button
                class="action-btn confirm-delete"
                @click="deleteAccount(account.account_id)"
                :disabled="deletingAccounts.has(account.account_id)"
              >
                {{ deletingAccounts.has(account.account_id) ? '删除中...' : '确认删除' }}
              </button>
              <button class="action-btn cancel" @click="confirmDelete = null">取消</button>
            </template>
          </div>

          <div
            v-if="testResults[account.account_id]"
            class="test-result"
            :class="{
              success: testResults[account.account_id].success,
              fail: !testResults[account.account_id].success,
            }"
          >
            {{ testResults[account.account_id].message }}
          </div>
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.gee-account-settings {
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

/* 引擎信息 */
.engine-info,
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

.info-value.active {
  color: #9ff8cf;
}

/* 添加表单 */
.add-form {
  display: flex;
  flex-direction: column;
  gap: 0.52rem;
  padding: 0.72rem;
  border-radius: 0.52rem;
  background: rgba(4, 12, 23, 0.6);
  border: 1px solid rgba(90, 213, 255, 0.16);
}

.form-row {
  display: flex;
  flex-direction: column;
  gap: 0.22rem;
}

.form-label {
  color: #8aa8bf;
  font-size: 0.58rem;
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
  min-height: 8rem;
}

.form-textarea:focus {
  border-color: rgba(90, 213, 255, 0.4);
}

.form-file {
  font-size: 0.56rem;
  color: #8aa8bf;
}

.form-error {
  padding: 0.32rem 0.52rem;
  border-radius: 0.36rem;
  background: rgba(255, 100, 100, 0.08);
  border: 1px solid rgba(255, 100, 100, 0.16);
  color: #ff9999;
  font-size: 0.56rem;
}

.form-actions {
  display: flex;
  gap: 0.32rem;
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

/* 账户卡片 */
.account-list {
  display: flex;
  flex-direction: column;
  gap: 0.42rem;
}

.account-card {
  padding: 0.62rem 0.72rem;
  border-radius: 0.52rem;
  background: rgba(4, 12, 23, 0.5);
  border: 1px solid rgba(136, 192, 255, 0.1);
  transition: opacity 0.2s ease;
}

.account-card.disabled {
  opacity: 0.5;
}

.account-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 0.52rem;
  margin-bottom: 0.32rem;
}

.account-info {
  display: flex;
  flex-direction: column;
  gap: 0.12rem;
  min-width: 0;
  flex: 1;
}

.account-id {
  color: #e8f3fc;
  font-size: 0.64rem;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.account-email {
  color: #8aa8bf;
  font-size: 0.56rem;
  font-family: 'SF Mono', 'Consolas', monospace;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.account-badges {
  display: flex;
  align-items: center;
  gap: 0.42rem;
  flex: none;
}

.account-meta {
  display: flex;
  gap: 0.62rem;
  flex-wrap: wrap;
  margin-bottom: 0.42rem;
}

.meta-item {
  color: #5a7080;
  font-size: 0.54rem;
  font-family: 'SF Mono', 'Consolas', monospace;
}

.account-actions {
  display: flex;
  gap: 0.32rem;
}

/* 徽章 */
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

.action-btn.add {
  border-color: rgba(90, 213, 255, 0.3);
  color: #5ad5ff;
  background: rgba(10, 132, 255, 0.12);
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
