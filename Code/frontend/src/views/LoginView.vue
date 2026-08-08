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
    <div class="login-backdrop" aria-hidden="true">
      <div class="grid-lines"></div>
      <div class="glow glow-a"></div>
      <div class="glow glow-b"></div>
    </div>

    <div class="login-card">
      <div class="brand-block">
        <div class="brand-mark" aria-hidden="true">
          <span class="mark-ring"></span>
          <span class="mark-core">◎</span>
        </div>
        <div class="brand-copy">
          <p class="eyebrow">{{ BRAND.eyebrow }}</p>
          <h1>{{ BRAND.shortName }}</h1>
          <p class="subtitle">登录以访问地图分析、工作流与数据服务</p>
        </div>
      </div>

      <p v-if="auth.bootstrapError" class="banner banner-warn">
        {{ auth.bootstrapError }}
        <button type="button" class="inline-link" :disabled="retrying" @click="retryBootstrap">
          {{ retrying ? '重试中…' : '重试连接' }}
        </button>
      </p>

      <form class="login-form" @submit.prevent="submit">
        <label class="field">
          <span class="field-label">用户名</span>
          <input
            v-model="username"
            type="text"
            autocomplete="username"
            placeholder="请输入用户名"
            required
          />
        </label>
        <label class="field">
          <span class="field-label">密码</span>
          <input
            v-model="password"
            type="password"
            autocomplete="current-password"
            placeholder="请输入密码"
            required
          />
        </label>

        <p v-if="devHint" class="dev-hint">
          开发环境已预填默认账号；生产环境请使用管理员分配的凭据。
        </p>
        <p v-if="error" class="banner banner-error">{{ error }}</p>

        <button class="submit-btn" type="submit" :disabled="submitting">
          <span v-if="submitting" class="btn-spinner" aria-hidden="true"></span>
          {{ submitting ? '登录中…' : '进入系统' }}
        </button>
      </form>

      <p class="footer-note">会话通过安全 Cookie 维持，请勿在公共设备保持登录。</p>
    </div>
  </div>
</template>

<style scoped>
.login-page {
  min-height: 100vh;
  display: grid;
  place-items: center;
  padding: 1.5rem;
  position: relative;
  overflow: hidden;
  background: #030912;
  color: #e8f3fc;
}

.login-backdrop {
  position: absolute;
  inset: 0;
  pointer-events: none;
}

.grid-lines {
  position: absolute;
  inset: -20%;
  background-image:
    linear-gradient(rgba(90, 213, 255, 0.04) 1px, transparent 1px),
    linear-gradient(90deg, rgba(90, 213, 255, 0.04) 1px, transparent 1px);
  background-size: 48px 48px;
  transform: perspective(600px) rotateX(58deg) translateY(-8%);
  opacity: 0.55;
}

.glow {
  position: absolute;
  border-radius: 50%;
  filter: blur(80px);
  opacity: 0.35;
}

.glow-a {
  width: 420px;
  height: 420px;
  top: -120px;
  left: -80px;
  background: rgba(10, 132, 255, 0.35);
}

.glow-b {
  width: 360px;
  height: 360px;
  bottom: -100px;
  right: -60px;
  background: rgba(90, 213, 255, 0.2);
}

.login-card {
  position: relative;
  width: min(26rem, 100%);
  padding: 1.6rem 1.45rem 1.35rem;
  border: 1px solid rgba(136, 192, 255, 0.18);
  border-radius: 1rem;
  background: linear-gradient(165deg, rgba(10, 22, 40, 0.96), rgba(6, 14, 26, 0.92));
  box-shadow:
    0 24px 64px rgba(1, 8, 16, 0.55),
    inset 0 1px 0 rgba(136, 192, 255, 0.08);
}

.brand-block {
  display: flex;
  gap: 0.85rem;
  align-items: center;
  margin-bottom: 1.35rem;
}

.brand-mark {
  position: relative;
  width: 2.6rem;
  height: 2.6rem;
  display: grid;
  place-items: center;
}

.mark-ring {
  position: absolute;
  inset: 0;
  border-radius: 50%;
  border: 1px solid rgba(90, 213, 255, 0.35);
  box-shadow: 0 0 24px rgba(10, 132, 255, 0.2);
}

.mark-core {
  font-size: 1.1rem;
  color: #5ad5ff;
}

.brand-copy .eyebrow {
  margin: 0;
  font-size: 0.58rem;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: #6e8ba0;
}

.brand-copy h1 {
  margin: 0.15rem 0 0;
  font-size: 1.15rem;
  font-weight: 700;
  letter-spacing: 0.02em;
}

.subtitle {
  margin: 0.35rem 0 0;
  font-size: 0.68rem;
  line-height: 1.45;
  color: #8aa8bf;
}

.login-form {
  display: flex;
  flex-direction: column;
  gap: 0.85rem;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 0.32rem;
}

.field-label {
  font-size: 0.62rem;
  color: #8aa8bf;
}

.field input {
  padding: 0.62rem 0.72rem;
  border: 1px solid rgba(136, 192, 255, 0.16);
  border-radius: 0.55rem;
  background: rgba(4, 10, 18, 0.9);
  color: #e8f3fc;
  font: inherit;
  font-size: 0.72rem;
  transition:
    border-color 0.15s ease,
    box-shadow 0.15s ease;
}

.field input::placeholder {
  color: #5a7080;
}

.field input:focus {
  outline: none;
  border-color: rgba(90, 213, 255, 0.45);
  box-shadow: 0 0 0 3px rgba(10, 132, 255, 0.12);
}

.dev-hint {
  margin: 0;
  font-size: 0.58rem;
  line-height: 1.45;
  color: #7a94a8;
}

.banner {
  margin: 0 0 0.75rem;
  padding: 0.5rem 0.65rem;
  border-radius: 0.5rem;
  font-size: 0.62rem;
  line-height: 1.45;
}

.banner-warn {
  border: 1px solid rgba(255, 180, 120, 0.28);
  background: rgba(120, 48, 24, 0.35);
  color: #ffc8b0;
}

.banner-error {
  border: 1px solid rgba(255, 120, 90, 0.28);
  background: rgba(90, 24, 16, 0.4);
  color: #ffb4a8;
}

.inline-link {
  margin-left: 0.35rem;
  padding: 0;
  border: none;
  background: none;
  color: #ffd8c8;
  font: inherit;
  font-size: inherit;
  cursor: pointer;
  text-decoration: underline;
}

.inline-link:disabled {
  opacity: 0.6;
  cursor: wait;
}

.submit-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 0.45rem;
  margin-top: 0.15rem;
  padding: 0.68rem 0.9rem;
  border: 1px solid rgba(90, 213, 255, 0.4);
  border-radius: 0.55rem;
  background: linear-gradient(180deg, rgba(10, 132, 255, 0.28), rgba(10, 132, 255, 0.16));
  color: #dff6ff;
  font: inherit;
  font-size: 0.72rem;
  font-weight: 600;
  cursor: pointer;
  transition:
    background 0.15s ease,
    transform 0.1s ease;
}

.submit-btn:hover:not(:disabled) {
  background: linear-gradient(180deg, rgba(10, 132, 255, 0.38), rgba(10, 132, 255, 0.22));
}

.submit-btn:active:not(:disabled) {
  transform: translateY(1px);
}

.submit-btn:disabled {
  opacity: 0.65;
  cursor: wait;
}

.btn-spinner {
  width: 0.75rem;
  height: 0.75rem;
  border: 2px solid rgba(223, 246, 255, 0.25);
  border-top-color: #dff6ff;
  border-radius: 50%;
  animation: spin 0.7s linear infinite;
}

.footer-note {
  margin: 1rem 0 0;
  font-size: 0.56rem;
  line-height: 1.4;
  color: #5a7080;
  text-align: center;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}
</style>
