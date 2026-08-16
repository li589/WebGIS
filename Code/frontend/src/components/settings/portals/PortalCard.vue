<script setup lang="ts">
/**
 * PortalCard — 门户目录卡片。
 *
 * 徽标：region（国际/国内）/ 凭据状态 / 检索能力；操作：配置凭据 / 测试 / 检索 / 编辑地址 / 删除（自定义）。
 */

import { computed, ref } from 'vue'
import type { PortalCatalogEntry } from '../../../types/api-reexports'
import { useSettingsStore } from '../../../stores/settings'

const props = defineProps<{
  portal: PortalCatalogEntry
}>()

const emit = defineEmits<{
  configure: [portal: PortalCatalogEntry]
  search: [portal: PortalCatalogEntry]
  editUrl: [portal: PortalCatalogEntry]
}>()

const settingsStore = useSettingsStore()
const testing = ref(false)
const testMsg = ref('')
const testOk = ref(false)

const credLabel = computed(() => {
  if (!props.portal.requires_credentials) return { text: '无需凭据', cls: 'badge-none' }
  if (props.portal.has_credentials) return { text: '已配置凭据', cls: 'badge-ok' }
  return { text: '需要凭据', cls: 'badge-warn' }
})

const credProfile = computed(() => props.portal.credential_profile || props.portal.portal_id)

async function runTest() {
  testing.value = true
  testMsg.value = ''
  try {
    const res = await settingsStore.runPortalTest(props.portal.portal_id)
    testOk.value = res.ok
    testMsg.value = `${res.message}${res.tested_url ? `（${res.tested_url}）` : ''}`
  } catch (e) {
    testOk.value = false
    testMsg.value = (e as Error).message
  } finally {
    testing.value = false
  }
}
</script>

<template>
  <div class="portal-card">
    <div class="portal-head">
      <div class="portal-title">
        <span class="portal-name">{{ portal.name }}</span>
        <a
          v-if="portal.website"
          :href="portal.website"
          target="_blank"
          rel="noopener noreferrer"
          class="portal-site"
          title="访问官网"
        >
          ↗
        </a>
      </div>
      <div class="portal-badges">
        <span class="portal-badge" :class="portal.region === 'china' ? 'badge-cn' : 'badge-intl'">
          {{ portal.region === 'china' ? '国内' : '国际' }}
        </span>
        <span class="portal-badge" :class="credLabel.cls">{{ credLabel.text }}</span>
        <span v-if="portal.account_count > 0" class="portal-badge badge-accounts">
          账号 ×{{ portal.account_count }}
        </span>
        <span v-if="portal.search_capability !== 'none'" class="portal-badge badge-search">
          可检索
        </span>
        <span v-if="!portal.builtin" class="portal-badge badge-custom">自定义</span>
      </div>
    </div>
    <p class="portal-org">{{ portal.organization }}</p>
    <p class="portal-desc">{{ portal.description }}</p>
    <p class="portal-url" :title="portal.effective_base_url">
      <code>{{ portal.effective_base_url }}</code>
      <span v-if="portal.base_url_overridden" class="url-override">（已覆盖内置地址）</span>
      <template v-if="portal.effective_alt_url">
        · 备 <code>{{ portal.effective_alt_url }}</code>
      </template>
    </p>
    <p v-if="portal.credentials_hint && portal.requires_credentials" class="portal-hint">
      {{ portal.credentials_hint }}
      <template v-if="credProfile !== portal.portal_id">
        （凭据键 <code>{{ credProfile }}</code
        >，与同键门户共用）
      </template>
    </p>
    <p v-if="testMsg" class="portal-test" :class="{ ok: testOk }">{{ testMsg }}</p>
    <div class="actions">
      <button
        v-if="portal.requires_credentials"
        type="button"
        class="btn"
        @click="emit('configure', portal)"
      >
        {{ portal.has_credentials ? '修改凭据' : '配置凭据' }}
      </button>
      <button type="button" class="btn" :disabled="testing" @click="runTest">
        {{ testing ? '测试中…' : '测试连通' }}
      </button>
      <button
        v-if="portal.search_capability !== 'none'"
        type="button"
        class="btn"
        @click="emit('search', portal)"
      >
        在线检索
      </button>
      <button type="button" class="btn" @click="emit('editUrl', portal)">编辑地址</button>
    </div>
  </div>
</template>

<style scoped src="../settings-form.css"></style>
<style scoped>
.portal-card {
  padding: 0.58rem 0.66rem;
  border-radius: 0.5rem;
  border: 1px solid var(--border-subtle);
  background: var(--surface-sunken);
  display: flex;
  flex-direction: column;
  gap: 0.32rem;
}
.portal-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 0.4rem;
  flex-wrap: wrap;
}
.portal-title {
  display: flex;
  align-items: baseline;
  gap: 0.32rem;
  min-width: 0;
}
.portal-name {
  color: var(--text-strong);
  font-size: var(--font-size-caption);
  font-weight: 600;
}
.portal-site {
  color: var(--accent);
  font-size: var(--font-size-caption);
  text-decoration: none;
}
.portal-badges {
  display: flex;
  gap: 0.28rem;
  flex-wrap: wrap;
}
.portal-badge {
  padding: 0.08rem 0.32rem;
  border-radius: 0.24rem;
  font-size: var(--font-size-caption);
  background: var(--border-default);
  color: var(--accent-strong);
  white-space: nowrap;
}
.badge-intl {
  background: var(--accent-surface);
  color: var(--accent-strong);
}
.badge-cn {
  background: var(--warning-surface);
  color: var(--accent-warm);
}
.badge-ok {
  background: var(--success-surface);
  color: var(--success);
}
.badge-warn {
  background: var(--danger-surface);
  color: var(--danger);
}
.badge-none {
  background: var(--surface-2);
  color: var(--text-muted);
}
.badge-search {
  background: var(--accent-surface);
  color: var(--accent-strong);
}
.badge-accounts {
  background: var(--success-surface);
  color: var(--success);
}
.badge-custom {
  background: var(--surface-2);
  color: var(--text-strong);
}
.portal-org {
  margin: 0;
  color: var(--text-muted);
  font-size: var(--font-size-caption);
}
.portal-desc {
  margin: 0;
  color: var(--text-disabled);
  font-size: var(--font-size-caption);
  line-height: 1.45;
}
.portal-url {
  margin: 0;
  color: var(--text-muted);
  font-size: var(--font-size-caption);
  word-break: break-all;
}
.portal-url code {
  color: var(--text-primary);
}
.url-override {
  color: var(--accent-warm);
}
.portal-hint {
  margin: 0;
  color: var(--accent-warm);
  font-size: var(--font-size-caption);
  line-height: 1.4;
}
.portal-hint code {
  color: var(--text-primary);
}
.portal-test {
  margin: 0;
  color: var(--danger);
  font-size: var(--font-size-caption);
  word-break: break-all;
}
.portal-test.ok {
  color: var(--success);
}
</style>
