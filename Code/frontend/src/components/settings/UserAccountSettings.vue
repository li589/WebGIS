<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import {
  createAuthToken,
  listAuthTokens,
  revokeAuthToken,
  type AuthToken,
  type UserRole,
} from '../../services/auth-api'
import { useAuthStore } from '../../stores/auth'

const emit = defineEmits<{ close: [] }>()

const auth = useAuthStore()
const router = useRouter()

const newUsername = ref('')
const newPassword = ref('')
const newRole = ref<UserRole>('operator')
const tokenLabel = ref('')
const tokens = ref<AuthToken[]>([])
const tokensLoading = ref(false)
const createdToken = ref<string | null>(null)
const message = ref<string | null>(null)
const error = ref<string | null>(null)

async function loadTokens() {
  tokensLoading.value = true
  try {
    tokens.value = await listAuthTokens()
  } catch (err) {
    error.value = err instanceof Error ? err.message : '加载 Token 失败'
  } finally {
    tokensLoading.value = false
  }
}

onMounted(() => {
  if (auth.isAdmin) void auth.loadUsers()
  void loadTokens()
})

async function logout() {
  await auth.logout()
  emit('close')
  await router.replace('/login')
}

async function createAccount() {
  error.value = null
  message.value = null
  try {
    await auth.addUser(newUsername.value.trim(), newPassword.value, newRole.value)
    message.value = '用户已创建'
    newUsername.value = ''
    newPassword.value = ''
    newRole.value = 'operator'
  } catch (err) {
    error.value = err instanceof Error ? err.message : '创建失败'
  }
}

async function createToken() {
  error.value = null
  createdToken.value = null
  try {
    const created = await createAuthToken({ label: tokenLabel.value || undefined })
    createdToken.value = created.token
    tokenLabel.value = ''
    await loadTokens()
    message.value = 'API Token 已创建（明文仅显示一次）'
  } catch (err) {
    error.value = err instanceof Error ? err.message : '创建 Token 失败'
  }
}

async function revokeToken(tokenId: number) {
  error.value = null
  try {
    await revokeAuthToken(tokenId)
    await loadTokens()
    message.value = 'Token 已吊销'
  } catch (err) {
    error.value = err instanceof Error ? err.message : '吊销失败'
  }
}

async function toggleEnabled(userId: number, enabled: boolean) {
  error.value = null
  try {
    await auth.patchUser(userId, { enabled })
  } catch (err) {
    error.value = err instanceof Error ? err.message : '更新失败'
  }
}

async function changeRole(userId: number, role: UserRole) {
  error.value = null
  try {
    await auth.patchUser(userId, { role })
  } catch (err) {
    error.value = err instanceof Error ? err.message : '更新失败'
  }
}

async function removeAccount(userId: number, username: string) {
  if (!window.confirm(`确定删除用户 ${username}？`)) return
  error.value = null
  try {
    await auth.removeUser(userId)
    message.value = '用户已删除'
  } catch (err) {
    error.value = err instanceof Error ? err.message : '删除失败'
  }
}
</script>

<template>
  <div class="user-account-settings">
    <section class="settings-section">
      <h3 class="section-title">账户与登录</h3>
      <p class="section-hint">
        浏览器通过 HttpOnly 会话 Cookie 鉴权；外部工具可使用下方个人 API Token
        或联系管理员获取服务密钥。 当前登录：<strong>{{ auth.user?.username }}</strong
        >（{{ auth.user?.role }}）
      </p>
      <button type="button" class="secondary-btn" @click="logout">退出登录</button>
    </section>

    <section class="settings-section">
      <h3 class="section-title">个人 API Token</h3>
      <div class="create-form token-form">
        <input v-model="tokenLabel" type="text" placeholder="标签（可选）" />
        <button type="button" class="primary-btn" :disabled="!auth.canWrite" @click="createToken">
          创建 Token
        </button>
      </div>
      <p v-if="!auth.canWrite" class="section-hint">只读账户无法创建 API Token。</p>
      <p v-if="createdToken" class="ok token-plain">新 Token：{{ createdToken }}</p>
      <div v-if="tokensLoading" class="loading">加载 Token…</div>
      <table v-else-if="tokens.length" class="user-table">
        <thead>
          <tr>
            <th>用户</th>
            <th>标签</th>
            <th>创建时间</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="t in tokens" :key="t.id">
            <td>{{ t.username }}</td>
            <td>{{ t.label || '—' }}</td>
            <td>{{ t.created_at }}</td>
            <td>
              <button type="button" class="danger-btn" @click="revokeToken(t.id)">吊销</button>
            </td>
          </tr>
        </tbody>
      </table>
    </section>

    <section v-if="auth.isAdmin" class="settings-section">
      <h3 class="section-title">用户管理（管理员）</h3>
      <p v-if="message" class="ok">{{ message }}</p>
      <p v-if="error" class="err">{{ error }}</p>

      <div class="create-form">
        <input v-model="newUsername" type="text" placeholder="新用户名" />
        <input v-model="newPassword" type="password" placeholder="初始密码（≥8位）" />
        <select v-model="newRole">
          <option value="admin">管理员</option>
          <option value="operator">操作员</option>
          <option value="viewer">只读</option>
        </select>
        <button type="button" class="primary-btn" @click="createAccount">创建用户</button>
      </div>

      <div v-if="auth.usersLoading" class="loading">加载用户列表…</div>
      <table v-else class="user-table">
        <thead>
          <tr>
            <th>用户名</th>
            <th>角色</th>
            <th>状态</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="u in auth.users" :key="u.id">
            <td>{{ u.username }}</td>
            <td>
              <select
                :value="u.role"
                :disabled="u.id === auth.user?.id"
                @change="changeRole(u.id, ($event.target as HTMLSelectElement).value as UserRole)"
              >
                <option value="admin">管理员</option>
                <option value="operator">操作员</option>
                <option value="viewer">只读</option>
              </select>
            </td>
            <td>
              <label class="enabled-toggle">
                <input
                  type="checkbox"
                  :checked="u.enabled"
                  :disabled="u.id === auth.user?.id"
                  @change="toggleEnabled(u.id, ($event.target as HTMLInputElement).checked)"
                />
                {{ u.enabled ? '启用' : '禁用' }}
              </label>
            </td>
            <td>
              <button
                v-if="u.id !== auth.user?.id"
                type="button"
                class="danger-btn"
                @click="removeAccount(u.id, u.username)"
              >
                删除
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </section>
  </div>
</template>

<style scoped>
.user-account-settings {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.settings-section {
  display: flex;
  flex-direction: column;
  gap: 0.55rem;
}

.section-title {
  margin: 0;
  font-size: 0.72rem;
  color: #e8f3fc;
}

.section-hint {
  margin: 0;
  font-size: 0.6rem;
  line-height: 1.45;
  color: #8aa8bf;
}

.create-form {
  display: grid;
  grid-template-columns: 1fr 1fr auto auto;
  gap: 0.4rem;
}

.token-form {
  grid-template-columns: 1fr auto;
}

.create-form input,
.create-form select,
.user-table select {
  padding: 0.38rem 0.45rem;
  border: 1px solid rgba(136, 192, 255, 0.18);
  border-radius: 0.35rem;
  background: rgba(4, 10, 18, 0.85);
  color: #e8f3fc;
  font: inherit;
  font-size: 0.58rem;
}

.primary-btn,
.secondary-btn,
.danger-btn {
  padding: 0.38rem 0.55rem;
  border-radius: 0.35rem;
  border: 1px solid rgba(90, 213, 255, 0.28);
  background: rgba(10, 132, 255, 0.14);
  color: #5ad5ff;
  font: inherit;
  font-size: 0.58rem;
  cursor: pointer;
}

.secondary-btn {
  align-self: flex-start;
}

.danger-btn {
  border-color: rgba(255, 120, 90, 0.35);
  background: rgba(120, 30, 20, 0.35);
  color: #ffb4a8;
}

.user-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.58rem;
  color: #d8e6f5;
}

.user-table th,
.user-table td {
  padding: 0.35rem 0.3rem;
  border-bottom: 1px solid rgba(136, 192, 255, 0.08);
  text-align: left;
}

.enabled-toggle {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
}

.ok {
  margin: 0;
  color: #9dffc8;
  font-size: 0.58rem;
}

.token-plain {
  word-break: break-all;
}

.err {
  margin: 0;
  color: #ffb4a8;
  font-size: 0.58rem;
}

.loading {
  font-size: 0.58rem;
  color: #8aa8bf;
}

@media (max-width: 700px) {
  .create-form {
    grid-template-columns: 1fr;
  }
}
</style>
