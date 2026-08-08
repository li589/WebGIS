<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { safeRedirect } from '../app/router'
import { useAuthStore } from '../stores/auth'
import { BRAND } from '../ui-copy'

const auth = useAuthStore()
const router = useRouter()
const route = useRoute()

const username = ref('')
const password = ref('')
const error = ref<string | null>(null)
const submitting = ref(false)
const retrying = ref(false)

const devHint = computed(() => (import.meta.env.DEV ? auth.config?.dev_prefill : null))

onMounted(() => {
  if (devHint.value) {
    username.value = devHint.value.username
    password.value = devHint.value.password
  }
})

async function retryBootstrap() {
  retrying.value = true
  try {
    await auth.retryBootstrap()
  } finally {
    retrying.value = false
  }
}

async function submit() {
  error.value = null
  submitting.value = true
  try {
    await auth.login(username.value.trim(), password.value)
    const redirect =
      typeof route.query.redirect === 'string' ? safeRedirect(route.query.redirect) : '/'
    await router.replace(redirect)
  } catch (err) {
    error.value = err instanceof Error ? err.message : '登录失败'
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <div class="login-page">
    <div class="login-card">
      <div class="brand">
        <span class="brand-mark" aria-hidden="true">◎</span>
        <div>
          <h1>{{ BRAND.shortName }}</h1>
          <p>请登录以继续使用系统</p>
        </div>
      </div>

      <p v-if="auth.bootstrapError" class="error">{{ auth.bootstrapError }}</p>
      <button
        v-if="auth.bootstrapError"
        type="button"
        class="retry-btn"
        :disabled="retrying"
        @click="retryBootstrap"
      >
        {{ retrying ? '重试中…' : '重试连接' }}
      </button>

      <form class="login-form" @submit.prevent="submit">
        <label class="field">
          <span>用户名</span>
          <input v-model="username" type="text" autocomplete="username" required />
        </label>
        <label class="field">
          <span>密码</span>
          <input v-model="password" type="password" autocomplete="current-password" required />
        </label>

        <p v-if="devHint" class="dev-hint">
          调试环境已预填默认账号；生产环境请使用管理员分配的凭据。
        </p>
        <p v-if="auth.config?.dev_write_api_key" class="dev-hint">
          脚本/CI 服务密钥（仅展示）：{{ auth.config.dev_write_api_key }}
        </p>
        <p v-if="error" class="error">{{ error }}</p>

        <button class="submit-btn" type="submit" :disabled="submitting">
          {{ submitting ? '登录中…' : '登录' }}
        </button>
      </form>
    </div>
  </div>
</template>

<style scoped>
.login-page {
  min-height: 100vh;
  display: grid;
  place-items: center;
  padding: 1.5rem;
  background:
    radial-gradient(circle at 20% 20%, rgba(10, 132, 255, 0.12), transparent 45%),
    radial-gradient(circle at 80% 0%, rgba(90, 213, 255, 0.08), transparent 40%), #040a12;
}

.login-card {
  width: min(24rem, 100%);
  padding: 1.4rem 1.3rem 1.2rem;
  border: 1px solid rgba(136, 192, 255, 0.16);
  border-radius: 0.9rem;
  background: rgba(8, 17, 31, 0.96);
  box-shadow: 0 18px 48px rgba(1, 8, 16, 0.45);
}

.brand {
  display: flex;
  gap: 0.7rem;
  align-items: center;
  margin-bottom: 1.2rem;
  color: #e8f3fc;
}

.brand-mark {
  font-size: 1.4rem;
  color: #5ad5ff;
}

.brand h1 {
  margin: 0;
  font-size: 1rem;
  font-weight: 700;
}

.brand p {
  margin: 0.2rem 0 0;
  font-size: 0.68rem;
  color: #8aa8bf;
}

.login-form {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 0.28rem;
  font-size: 0.62rem;
  color: #8aa8bf;
}

.field input {
  padding: 0.55rem 0.62rem;
  border: 1px solid rgba(136, 192, 255, 0.18);
  border-radius: 0.45rem;
  background: rgba(4, 10, 18, 0.85);
  color: #e8f3fc;
  font: inherit;
}

.field input:focus {
  outline: none;
  border-color: rgba(90, 213, 255, 0.45);
}

.dev-hint {
  margin: 0;
  font-size: 0.58rem;
  line-height: 1.45;
  color: #9ab0c2;
}

.error {
  margin: 0;
  font-size: 0.6rem;
  color: #ffb4a8;
}

.retry-btn {
  margin: 0 0 0.75rem;
  padding: 0.45rem 0.7rem;
  border: 1px solid rgba(255, 180, 120, 0.35);
  border-radius: 0.45rem;
  background: rgba(255, 140, 100, 0.1);
  color: #ffc8b0;
  font: inherit;
  font-size: 0.62rem;
  cursor: pointer;
}

.retry-btn:disabled {
  opacity: 0.6;
  cursor: wait;
}

.submit-btn {
  margin-top: 0.2rem;
  padding: 0.58rem 0.8rem;
  border: 1px solid rgba(90, 213, 255, 0.35);
  border-radius: 0.45rem;
  background: rgba(10, 132, 255, 0.2);
  color: #5ad5ff;
  font: inherit;
  font-size: 0.68rem;
  font-weight: 600;
  cursor: pointer;
}

.submit-btn:disabled {
  opacity: 0.6;
  cursor: wait;
}
</style>
