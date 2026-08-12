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
import AppSelect from '../ui/AppSelect.vue'

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

const ROLE_LABEL: Record<UserRole, string> = {
  admin: '管理员',
  operator: '操作员',
  viewer: '只读',
}

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
  const username = newUsername.value.trim()
  if (!username) {
    error.value = '请输入用户名'
    return
  }
  if (newPassword.value.length < 8) {
    error.value = '密码至少需要 8 位'
    return
  }
  try {
    await auth.addUser(username, newPassword.value, newRole.value)
    message.value = '用户已创建'
    newUsername.value = ''
    newPassword.value = ''
    newRole.value = 'operator'
  } catch (err) {
    const msg = err instanceof Error ? err.message : '创建失败'
    if (msg.includes('username already exists') || msg.includes('已存在')) {
      error.value = `用户名「${username}」已存在，请换一个`
    } else if (msg.includes('400')) {
      error.value = '请求参数有误，请检查用户名和密码格式'
    } else {
      error.value = msg
    }
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
    <section v-if="auth.user" class="account-hero">
      <div class="account-avatar" aria-hidden="true">
        {{ auth.user.username.slice(0, 1).toUpperCase() }}
      </div>
      <div class="account-meta">
        <p class="account-name">{{ auth.user.username }}</p>
        <p class="account-role">{{ ROLE_LABEL[auth.user.role] }}</p>
      </div>
      <button type="button" class="logout-btn" @click="logout">退出登录</button>
    </section>

    <section class="settings-section">
      <h3 class="section-title">账户与登录</h3>
      <p class="section-hint">
        浏览器通过 HttpOnly 会话 Cookie 鉴权；外部脚本可使用下方个人 API
        Token，或联系管理员获取服务密钥。
      </p>
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
        <AppSelect
          v-model="newRole"
          :options="[
            { label: '管理员', value: 'admin' },
            { label: '操作员', value: 'operator' },
            { label: '只读', value: 'viewer' },
          ]"
        />
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
              <AppSelect
                :model-value="u.role"
                :disabled="u.id === auth.user?.id"
                :options="[
                  { label: '管理员', value: 'admin' },
                  { label: '操作员', value: 'operator' },
                  { label: '只读', value: 'viewer' },
                ]"
                @change="(val) => changeRole(u.id, val as UserRole)"
              />
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

.account-hero {
  display: flex;
  align-items: center;
  gap: 0.65rem;
  padding: 0.75rem 0.8rem;
  border-radius: 0.65rem;
  border: 1px solid var(--success-surface);
  background: linear-gradient(135deg, var(--success-surface), var(--accent-surface));
}

.account-avatar {
  width: 2.2rem;
  height: 2.2rem;
  border-radius: 50%;
  display: grid;
  place-items: center;
  font-size: 0.9rem;
  font-weight: 700;
  color: var(--success);
  background: var(--success-surface);
  border: 1px solid var(--success-border);
  flex: none;
}

.account-meta {
  flex: 1;
  min-width: 0;
}

.account-name {
  margin: 0;
  font-size: var(--font-size-caption);
  font-weight: 600;
  color: var(--text-strong);
}

.account-role {
  margin: 0.12rem 0 0;
  font-size: var(--font-size-caption);
  color: var(--text-muted);
}

.logout-btn {
  flex: none;
  padding: 0.38rem 0.55rem;
  border-radius: 0.35rem;
  border: 1px solid var(--danger-border);
  background: var(--danger-surface);
  color: var(--danger);
  font: inherit;
  font-size: var(--font-size-caption);
  cursor: pointer;
}

.logout-btn:hover {
  background: var(--surface-hover);
}

.settings-section {
  display: flex;
  flex-direction: column;
  gap: 0.55rem;
}

.section-title {
  margin: 0;
  font-size: var(--font-size-caption);
  color: var(--text-strong);
}

.section-hint {
  margin: 0;
  font-size: var(--font-size-caption);
  line-height: 1.45;
  color: var(--text-muted);
}

.create-form {
  display: grid;
  grid-template-columns: minmax(8rem, 14rem) minmax(8rem, 14rem) minmax(6rem, 8rem) auto;
  gap: 0.4rem;
  align-items: center;
}

.token-form {
  grid-template-columns: 1fr auto;
}

.create-form input,
.create-form select,
.user-table select {
  width: 100%;
  padding: 0.38rem 0.45rem;
  border: 1px solid var(--border-default);
  border-radius: 0.35rem;
  background: var(--surface-1);
  color: var(--text-strong);
  font: inherit;
  font-size: var(--font-size-caption);
}

.primary-btn,
.secondary-btn,
.danger-btn {
  padding: 0.38rem 0.55rem;
  border-radius: 0.35rem;
  border: 1px solid var(--border-accent);
  background: var(--accent-surface);
  color: var(--accent-strong);
  font: inherit;
  font-size: var(--font-size-caption);
  cursor: pointer;
}

.secondary-btn {
  align-self: flex-start;
}

.danger-btn {
  border-color: var(--danger-border);
  background: var(--danger-surface);
  color: var(--danger);
}

.user-table {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--font-size-caption);
  color: var(--text-primary);
}

.user-table th,
.user-table td {
  padding: 0.35rem 0.3rem;
  border-bottom: 1px solid var(--border-subtle);
  text-align: left;
}

.enabled-toggle {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
}

.ok {
  margin: 0;
  color: var(--success);
  font-size: var(--font-size-caption);
}

.token-plain {
  word-break: break-all;
}

.err {
  margin: 0;
  color: var(--danger);
  font-size: var(--font-size-caption);
}

.loading {
  font-size: var(--font-size-caption);
  color: var(--text-muted);
}

@media (max-width: 768px) {
  .create-form {
    grid-template-columns: 1fr;
  }
}
</style>
