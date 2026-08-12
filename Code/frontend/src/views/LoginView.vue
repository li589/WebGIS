<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { safeRedirect } from '../app/router'
import { useAuthStore } from '../stores/auth'
import { BRAND } from '../ui-copy'
import AppButton from '../components/ui/AppButton.vue'

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
      <!-- 星点（最底层） -->
      <div class="stars"></div>
      <!-- 光晕 -->
      <div class="glow glow-a"></div>
      <div class="glow glow-b"></div>
      <div class="glow glow-c"></div>
      <!-- 等高线装饰 -->
      <div class="contour-lines"></div>
      <!-- SVG 地球经纬网格背景 -->
      <svg class="bg-globe" viewBox="0 0 800 800" xmlns="http://www.w3.org/2000/svg">
        <defs>
          <radialGradient id="globeGrad" cx="400" cy="400" r="380" gradientUnits="userSpaceOnUse">
            <stop offset="0%" stop-color="rgba(90,213,255,0.1)" />
            <stop offset="40%" stop-color="rgba(90,213,255,0.05)" />
            <stop offset="100%" stop-color="rgba(90,213,255,0)" />
          </radialGradient>
          <radialGradient id="atmosGrad" cx="400" cy="400" r="400" gradientUnits="userSpaceOnUse">
            <stop offset="82%" stop-color="rgba(10,132,255,0)" />
            <stop offset="93%" stop-color="rgba(10,132,255,0.1)" />
            <stop offset="100%" stop-color="rgba(90,213,255,0.2)" />
          </radialGradient>
          <linearGradient id="gridFade" x1="0%" y1="0%" x2="0%" y2="100%">
            <stop offset="0%" stop-color="rgba(90,213,255,0.1)" />
            <stop offset="100%" stop-color="rgba(90,213,255,0)" />
          </linearGradient>
        </defs>
        <!-- 大气层光晕 -->
        <circle cx="400" cy="400" r="400" fill="url(#atmosGrad)" />
        <!-- 地球主体 -->
        <circle
          cx="400"
          cy="400"
          r="300"
          fill="url(#globeGrad)"
          stroke="rgba(90,213,255,0.18)"
          stroke-width="1.2"
        />
        <!-- 纬线（水平椭圆） -->
        <ellipse
          v-for="lat in [-60, -45, -30, -15, 0, 15, 30, 45, 60]"
          :key="'lat' + lat"
          cx="400"
          cy="400"
          :rx="300 * Math.cos((lat * Math.PI) / 180)"
          :ry="Math.max(300 * Math.cos((lat * Math.PI) / 180) * 0.3, 15)"
          fill="none"
          stroke="rgba(90,213,255,0.08)"
          stroke-width="0.7"
          :transform="`translate(0, ${300 * Math.sin((lat * Math.PI) / 180) * 0.3})`"
        />
        <!-- 赤道（高亮） -->
        <ellipse
          cx="400"
          cy="400"
          rx="300"
          ry="90"
          fill="none"
          stroke="rgba(90,213,255,0.15)"
          stroke-width="1.2"
        />
        <!-- 经线（垂直椭圆旋转） -->
        <ellipse
          v-for="lon in [0, 20, 40, 60, 80, 100, 120, 140, 160]"
          :key="'lon' + lon"
          cx="400"
          cy="400"
          rx="300"
          ry="300"
          fill="none"
          stroke="rgba(90,213,255,0.06)"
          stroke-width="0.7"
          :transform="`rotate(${lon} 400 400) scale(1, 0.3)`"
        />
        <!-- 本初子午线（高亮） -->
        <ellipse
          cx="400"
          cy="400"
          rx="300"
          ry="300"
          fill="none"
          stroke="var(--accent-surface)"
          stroke-width="1"
          transform="rotate(0 400 400) scale(1, 0.3)"
        />
        <!-- 点阵装饰（数据节点感） -->
        <g fill="rgba(90,213,255,0.2)">
          <circle
            v-for="(p, i) in [
              [280, 280],
              [340, 320],
              [420, 300],
              [480, 350],
              [520, 420],
              [380, 450],
              [300, 400],
              [460, 270],
              [350, 500],
              [500, 480],
              [260, 350],
              [540, 380],
              [320, 240],
              [440, 480],
              [250, 440],
              [490, 250],
            ]"
            :key="i"
            :cx="p[0] + 100"
            :cy="p[1] + 50"
            r="1.8"
          />
        </g>
        <!-- 连线装饰（数据网络感） -->
        <g stroke="rgba(90,213,255,0.08)" stroke-width="0.5" fill="none">
          <line x1="380" y1="330" x2="420" y2="350" />
          <line x1="420" y1="350" x2="480" y2="400" />
          <line x1="480" y1="400" x2="520" y2="470" />
          <line x1="380" y1="330" x2="340" y2="370" />
          <line x1="340" y1="370" x2="300" y2="450" />
          <line x1="560" y1="330" x2="520" y2="370" />
        </g>
      </svg>
      <!-- 网格地面（透视网格） -->
      <div class="grid-lines"></div>
      <!-- 扫描线效果 -->
      <div class="scan-line"></div>
    </div>

    <div class="login-card">
      <div class="brand-block">
        <div class="brand-mark" aria-hidden="true">
          <!-- SVG 地球 Logo 替换 Unicode 字符 -->
          <svg class="mark-svg" viewBox="0 0 48 48" xmlns="http://www.w3.org/2000/svg">
            <circle
              cx="24"
              cy="24"
              r="20"
              fill="none"
              stroke="currentColor"
              stroke-width="1.5"
              opacity="0.6"
            />
            <ellipse
              cx="24"
              cy="24"
              rx="20"
              ry="6"
              fill="none"
              stroke="currentColor"
              stroke-width="1"
              opacity="0.4"
            />
            <ellipse
              cx="24"
              cy="16"
              rx="17"
              ry="5"
              fill="none"
              stroke="currentColor"
              stroke-width="0.8"
              opacity="0.3"
            />
            <ellipse
              cx="24"
              cy="32"
              rx="17"
              ry="5"
              fill="none"
              stroke="currentColor"
              stroke-width="0.8"
              opacity="0.3"
            />
            <ellipse
              cx="24"
              cy="24"
              rx="6"
              ry="20"
              fill="none"
              stroke="currentColor"
              stroke-width="0.8"
              opacity="0.3"
            />
            <ellipse
              cx="24"
              cy="24"
              rx="20"
              ry="20"
              fill="none"
              stroke="currentColor"
              stroke-width="0.5"
              opacity="0.2"
              transform="rotate(30 24 24) scale(1, 0.3)"
            />
            <circle cx="24" cy="24" r="3" fill="currentColor" opacity="0.8" />
          </svg>
          <span class="mark-ring"></span>
          <span class="mark-ring-outer"></span>
        </div>
        <div class="brand-copy">
          <p class="eyebrow">{{ BRAND.eyebrow }}</p>
          <h1>{{ BRAND.shortName }}</h1>
          <p class="subtitle">登录以访问地图分析、工作流与数据服务</p>
        </div>
      </div>

      <p v-if="auth.bootstrapError" class="banner banner-warn">
        {{ auth.bootstrapError }}
        <AppButton variant="ghost" size="sm" :disabled="retrying" @click="retryBootstrap">
          {{ retrying ? '重试中…' : '重试连接' }}
        </AppButton>
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

        <AppButton
          variant="primary"
          type="submit"
          :loading="submitting"
          :disabled="submitting"
          block
        >
          {{ submitting ? '登录中…' : '进入系统' }}
        </AppButton>
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
  padding: var(--space-4);
  position: relative;
  overflow: hidden;
  background:
    radial-gradient(ellipse at 20% 20%, rgba(10, 132, 255, 0.08) 0%, transparent 50%),
    radial-gradient(ellipse at 80% 80%, rgba(90, 213, 255, 0.06) 0%, transparent 50%),
    linear-gradient(180deg, #02060d 0%, #040d1a 50%, #030912 100%);
  color: var(--text-strong);
}

/* ═══ 背景层 ═══ */
.login-backdrop {
  position: absolute;
  inset: 0;
  pointer-events: none;
}

.bg-globe {
  position: absolute;
  width: min(950px, 95vw);
  height: min(950px, 95vw);
  top: 50%;
  left: 50%;
  transform: translate(-50%, -48%);
  opacity: 0.95;
  animation: globe-float 25s ease-in-out infinite;
}

@keyframes globe-float {
  0%,
  100% {
    transform: translate(-50%, -48%) scale(1);
  }
  50% {
    transform: translate(-50%, -52%) scale(1.02);
  }
}

/* 增加等高线装饰 */
.contour-lines {
  position: absolute;
  inset: 0;
  background-image:
    radial-gradient(ellipse 800px 400px at 50% 120%, rgba(90, 213, 255, 0.04) 0%, transparent 70%),
    radial-gradient(ellipse 600px 300px at 50% 115%, rgba(90, 213, 255, 0.03) 0%, transparent 70%),
    radial-gradient(ellipse 400px 200px at 50% 110%, rgba(90, 213, 255, 0.02) 0%, transparent 70%);
}

.grid-lines {
  position: absolute;
  inset: -20%;
  background-image:
    linear-gradient(rgba(90, 213, 255, 0.04) 1px, transparent 1px),
    linear-gradient(90deg, rgba(90, 213, 255, 0.04) 1px, transparent 1px);
  background-size: 48px 48px;
  transform: perspective(800px) rotateX(65deg) translateY(5%);
  opacity: 0.5;
  mask-image: linear-gradient(to top, black 0%, transparent 65%);
  -webkit-mask-image: linear-gradient(to top, black 0%, transparent 65%);
}

/* 增加扫描线效果 */
.scan-line {
  position: absolute;
  left: 0;
  right: 0;
  height: 2px;
  background: linear-gradient(90deg, transparent, rgba(90, 213, 255, 0.15), transparent);
  animation: scan-move 8s linear infinite;
  opacity: 0.6;
}

@keyframes scan-move {
  0% {
    top: -5%;
  }
  100% {
    top: 105%;
  }
}

.glow {
  position: absolute;
  border-radius: 50%;
  filter: blur(120px);
}

.glow-a {
  width: 560px;
  height: 560px;
  top: -200px;
  left: -120px;
  background: radial-gradient(
    circle,
    rgba(10, 132, 255, 0.25) 0%,
    rgba(10, 132, 255, 0.08) 50%,
    transparent 70%
  );
  opacity: 0.7;
  animation: glow-pulse-a 12s ease-in-out infinite;
}

.glow-b {
  width: 480px;
  height: 480px;
  bottom: -160px;
  right: -100px;
  background: radial-gradient(
    circle,
    rgba(90, 213, 255, 0.2) 0%,
    rgba(90, 213, 255, 0.06) 50%,
    transparent 70%
  );
  opacity: 0.6;
  animation: glow-pulse-b 15s ease-in-out infinite reverse;
}

.glow-c {
  width: 360px;
  height: 360px;
  top: 35%;
  right: 15%;
  background: radial-gradient(circle, rgba(255, 200, 120, 0.08) 0%, transparent 70%);
  opacity: 0.5;
}

@keyframes glow-pulse-a {
  0%,
  100% {
    opacity: 0.5;
    transform: scale(1);
  }
  50% {
    opacity: 0.7;
    transform: scale(1.1);
  }
}

@keyframes glow-pulse-b {
  0%,
  100% {
    opacity: 0.4;
    transform: scale(1);
  }
  50% {
    opacity: 0.6;
    transform: scale(1.05);
  }
}

.stars {
  position: absolute;
  inset: 0;
  background-image:
    radial-gradient(1px 1px at 10% 20%, rgba(255, 255, 255, 0.2) 0%, transparent 100%),
    radial-gradient(1px 1px at 30% 70%, rgba(255, 255, 255, 0.15) 0%, transparent 100%),
    radial-gradient(2px 2px at 50% 10%, rgba(200, 240, 255, 0.2) 0%, transparent 100%),
    radial-gradient(1px 1px at 70% 40%, rgba(255, 255, 255, 0.12) 0%, transparent 100%),
    radial-gradient(1px 1px at 85% 80%, rgba(255, 255, 255, 0.15) 0%, transparent 100%),
    radial-gradient(1.5px 1.5px at 15% 85%, rgba(200, 240, 255, 0.12) 0%, transparent 100%),
    radial-gradient(1px 1px at 90% 25%, rgba(255, 255, 255, 0.18) 0%, transparent 100%),
    radial-gradient(1px 1px at 45% 55%, rgba(255, 255, 255, 0.1) 0%, transparent 100%),
    radial-gradient(1.5px 1.5px at 25% 35%, rgba(255, 255, 255, 0.1) 0%, transparent 100%),
    radial-gradient(1px 1px at 65% 15%, rgba(255, 255, 255, 0.08) 0%, transparent 100%),
    radial-gradient(1px 1px at 5% 50%, rgba(255, 255, 255, 0.12) 0%, transparent 100%),
    radial-gradient(2px 2px at 95% 60%, rgba(200, 240, 255, 0.1) 0%, transparent 100%);
  animation: stars-twinkle 8s ease-in-out infinite alternate;
}

@keyframes stars-twinkle {
  0% {
    opacity: 0.5;
  }
  100% {
    opacity: 1;
  }
}

/* ═══ 登录卡片 ═══ */
.login-card {
  position: relative;
  width: min(28rem, 100%);
  padding: var(--space-7) var(--space-6) var(--space-6);
  border: 1px solid rgba(90, 213, 255, 0.15);
  border-radius: var(--radius-xl);
  background:
    linear-gradient(165deg, rgba(12, 26, 48, 0.88), rgba(6, 14, 26, 0.82)),
    linear-gradient(180deg, rgba(90, 213, 255, 0.03) 0%, transparent 40%);
  backdrop-filter: blur(32px) saturate(1.2);
  -webkit-backdrop-filter: blur(32px) saturate(1.2);
  box-shadow:
    0 40px 100px rgba(1, 8, 16, 0.7),
    0 0 0 1px rgba(255, 255, 255, 0.04) inset,
    0 1px 0 rgba(136, 223, 255, 0.15) inset,
    0 0 60px rgba(10, 132, 255, 0.08);
  animation: card-enter 0.7s cubic-bezier(0.16, 1, 0.3, 1) both;
}

/* 卡片边框光效 */
.login-card::before {
  content: '';
  position: absolute;
  inset: -1px;
  border-radius: inherit;
  padding: 1px;
  background: linear-gradient(
    135deg,
    var(--accent-border),
    transparent 40%,
    transparent 60%,
    rgba(255, 200, 120, 0.15)
  );
  -webkit-mask:
    linear-gradient(#fff 0 0) content-box,
    linear-gradient(#fff 0 0);
  mask:
    linear-gradient(#fff 0 0) content-box,
    linear-gradient(#fff 0 0);
  -webkit-mask-composite: xor;
  mask-composite: exclude;
  pointer-events: none;
  opacity: 0.8;
}

/* 卡片顶部高光 */
.login-card::after {
  content: '';
  position: absolute;
  top: 0;
  left: 15%;
  right: 15%;
  height: 1px;
  background: linear-gradient(90deg, transparent, rgba(136, 223, 255, 0.4), transparent);
  border-radius: 50%;
  pointer-events: none;
}

@keyframes card-enter {
  from {
    opacity: 0;
    transform: translateY(16px) scale(0.98);
  }
  to {
    opacity: 1;
    transform: translateY(0) scale(1);
  }
}

/* ═══ 品牌区域 ═══ */
.brand-block {
  display: flex;
  gap: var(--space-4);
  align-items: center;
  margin-bottom: var(--space-6);
}

.brand-mark {
  position: relative;
  width: 56px;
  height: 56px;
  display: grid;
  place-items: center;
  color: var(--accent);
  flex-shrink: 0;
  background: radial-gradient(circle at 30% 30%, rgba(90, 213, 255, 0.15), transparent 60%);
  border-radius: var(--radius-lg);
}

.mark-svg {
  width: 44px;
  height: 44px;
  animation: mark-spin 50s linear infinite;
  filter: drop-shadow(0 0 8px var(--accent-border));
}

@keyframes mark-spin {
  to {
    transform: rotate(360deg);
  }
}

.mark-ring {
  position: absolute;
  inset: 2px;
  border-radius: 50%;
  border: 1px solid rgba(90, 213, 255, 0.25);
  box-shadow:
    0 0 24px rgba(10, 132, 255, 0.12),
    inset 0 0 12px rgba(90, 213, 255, 0.05);
}

.mark-ring-outer {
  position: absolute;
  inset: -3px;
  border-radius: 50%;
  border: 1px solid rgba(90, 213, 255, 0.1);
  animation: ring-pulse 4s ease-in-out infinite;
}

@keyframes ring-pulse {
  0%,
  100% {
    opacity: 0.3;
    transform: scale(1);
  }
  50% {
    opacity: 0.7;
    transform: scale(1.06);
  }
}

.brand-copy .eyebrow {
  margin: 0;
  font-size: var(--font-size-caption);
  letter-spacing: 0.18em;
  text-transform: uppercase;
  color: var(--accent);
  font-weight: var(--font-weight-semibold);
  text-shadow: 0 0 20px var(--accent-border);
}

.brand-copy h1 {
  margin: 6px 0 0;
  font-size: 1.6rem;
  font-weight: var(--font-weight-bold);
  letter-spacing: 0.02em;
  color: var(--text-strong);
  background: linear-gradient(135deg, var(--text-strong) 0%, var(--accent-strong) 100%);
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
}

.subtitle {
  margin: var(--space-2) 0 0;
  font-size: var(--font-size-body-sm, 0.875rem);
  line-height: 1.6;
  color: var(--text-secondary);
  opacity: 0.9;
}

/* ═══ 表单 ═══ */
.login-form {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.field {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.field-label {
  font-size: var(--font-size-caption);
  font-weight: var(--font-weight-medium);
  color: var(--text-secondary);
}

.field input {
  padding: 0.8rem 1rem;
  border: 1px solid var(--accent-surface);
  border-radius: var(--radius-md);
  background: linear-gradient(180deg, rgba(4, 12, 22, 0.8), rgba(6, 14, 26, 0.6));
  color: var(--text-strong);
  font-family: inherit;
  font-size: var(--font-size-body);
  transition:
    border-color var(--motion-fast) var(--ease-standard),
    box-shadow var(--motion-fast) var(--ease-standard),
    background-color var(--motion-fast) var(--ease-standard),
    transform var(--motion-fast) var(--ease-standard);
}

.field input::placeholder {
  color: var(--text-disabled);
}

.field input:hover {
  border-color: rgba(90, 213, 255, 0.25);
  background: linear-gradient(180deg, rgba(6, 14, 26, 0.9), rgba(8, 18, 32, 0.7));
}

.field input:focus {
  outline: none;
  border-color: var(--accent);
  box-shadow:
    0 0 0 3px rgba(10, 132, 255, 0.12),
    0 0 20px rgba(90, 213, 255, 0.08),
    inset 0 1px 0 rgba(136, 223, 255, 0.1);
  background: linear-gradient(180deg, rgba(6, 14, 26, 0.95), rgba(8, 18, 32, 0.8));
}

.dev-hint {
  margin: 0;
  font-size: var(--font-size-caption);
  line-height: 1.5;
  color: var(--text-faint);
  padding: var(--space-2) var(--space-3);
  background: var(--surface-sunken);
  border-radius: var(--radius-sm);
  border: 1px solid var(--border-subtle);
}

.banner {
  margin: 0 0 var(--space-3);
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-md);
  font-size: var(--font-size-caption);
  line-height: 1.5;
}

.banner-warn {
  border: 1px solid var(--warning-border);
  background: var(--warning-surface);
  color: var(--warning);
}

.banner-error {
  border: 1px solid var(--danger-border);
  background: var(--danger-surface);
  color: var(--danger);
}

.footer-note {
  margin: var(--space-4) 0 0;
  font-size: var(--font-size-caption);
  line-height: 1.5;
  color: var(--text-faint);
  text-align: center;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

/* 减弱动画偏好 */
@media (prefers-reduced-motion: reduce) {
  .bg-globe,
  .stars,
  .mark-svg,
  .mark-ring-outer,
  .login-card,
  .glow-a,
  .glow-b,
  .scan-line {
    animation: none !important;
    transition: none !important;
  }
  .login-card {
    opacity: 1;
    transform: none;
  }
}
</style>
