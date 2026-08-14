<script setup lang="ts">
/**
 * ProfileCard — 单个远程存储 Profile 卡片。
 *
 * 徽标：协议 / 测试状态 / 当前活动路径（primary/alt）；操作：测试/浏览/搜索/切主备/历史/启停/编辑/删除。
 */

import { computed, ref } from 'vue'
import type { RemoteStorageProfile } from '../../../types/api-reexports'
import { failoverRemoteStorage, testRemoteStorageProfile } from '../../../services/settings-api'
import { PROTOCOL_META } from './protocols'

const props = defineProps<{
  profile: RemoteStorageProfile
}>()

const emit = defineEmits<{
  edit: [profile: RemoteStorageProfile]
  browse: [profile: RemoteStorageProfile]
  addRemoteSource: [profile: RemoteStorageProfile]
  changed: []
}>()

const meta = computed(() => PROTOCOL_META[props.profile.protocol as keyof typeof PROTOCOL_META])

const FALLBACK_LABELS: Record<string, string> = {
  auto: '自动',
  manual: '手动',
  off: '关闭',
}

const testing = ref(false)
const testMsg = ref('')
const testOk = ref(false)
const busy = ref(false)

const activeIsAlt = computed(() => {
  const state = props.profile.failover_state || {}
  return String(state.active || 'primary') === 'alt'
})

const hasAlt = computed(() =>
  Boolean(props.profile.alt_host || props.profile.alt_url || props.profile.alt_port != null),
)

function targetLabel(): string {
  if (meta.value?.usesUrl) return props.profile.host || ''
  if (meta.value?.usesPath) return props.profile.host || ''
  return `${props.profile.host || ''}${props.profile.port ? `:${props.profile.port}` : ''}`
}

async function runTest() {
  testing.value = true
  testMsg.value = ''
  try {
    const res = await testRemoteStorageProfile(props.profile.profile_id)
    testOk.value = res.success
    testMsg.value = res.message
    emit('changed')
  } catch (e) {
    testOk.value = false
    testMsg.value = (e as Error).message
  } finally {
    testing.value = false
  }
}

async function switchPath(target: 'primary' | 'alt') {
  if (activeIsAlt.value === (target === 'alt')) return
  busy.value = true
  try {
    await failoverRemoteStorage(props.profile.profile_id, target)
    emit('changed')
  } catch (e) {
    alert(`切换失败: ${(e as Error).message}`)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="key-card" :class="{ disabled: !profile.enabled }">
    <div class="key-card-header">
      <div class="key-title">
        <span class="key-name">{{ profile.display_name || profile.profile_id }}</span>
        <code class="key-id">{{ profile.profile_id }}</code>
      </div>
      <div class="key-badges">
        <span class="key-badge">{{ profile.protocol }}</span>
        <span v-if="profile.last_test_status === 'ok'" class="key-badge badge-ok">已验证</span>
        <span v-else-if="profile.last_test_status === 'failed'" class="key-badge badge-fail"
          >测试失败</span
        >
        <span
          v-if="hasAlt"
          class="key-badge"
          :class="activeIsAlt ? 'badge-alt' : 'badge-primary'"
          :title="activeIsAlt ? '当前经备用（隧道）路径访问' : '当前经主（内网）路径访问'"
        >
          {{ activeIsAlt ? '备用路径' : '主路径' }}
        </span>
      </div>
    </div>

    <p class="key-desc">
      <code>{{ targetLabel() }}</code>
      <template v-if="hasAlt && !meta?.usesUrl && profile.alt_host">
        · 备 <code>{{ profile.alt_host }}{{ profile.alt_port ? `:${profile.alt_port}` : '' }}</code>
      </template>
      <template v-if="hasAlt && meta?.usesUrl && profile.alt_url">
        · 备 <code>{{ profile.alt_url }}</code>
      </template>
      · {{ profile.has_secret || profile.has_private_key ? '已配置凭据' : '未配置凭据' }}
      <template v-if="profile.protocol === 'smb' && (profile.extra || {}).default_share">
        · share={{ (profile.extra || {}).default_share }}
      </template>
      · 回退{{ FALLBACK_LABELS[profile.fallback_mode] || profile.fallback_mode }}
    </p>

    <p v-if="testMsg" class="test-msg" :class="{ ok: testOk }">{{ testMsg }}</p>

    <div class="actions">
      <button type="button" class="btn" :disabled="testing" @click="runTest">
        {{ testing ? '测试中…' : '测试连通' }}
      </button>
      <button v-if="meta?.browsable" type="button" class="btn" @click="emit('browse', profile)">
        浏览
      </button>
      <button
        v-if="hasAlt"
        type="button"
        class="btn"
        :disabled="busy"
        :title="`当前活动：${activeIsAlt ? '备用' : '主'}路径`"
        @click="switchPath(activeIsAlt ? 'primary' : 'alt')"
      >
        {{ activeIsAlt ? '切回主路径' : '切至备用' }}
      </button>
      <button type="button" class="btn" @click="emit('edit', profile)">编辑</button>
      <button type="button" class="btn" @click="emit('addRemoteSource', profile)">
        添加为远程数据源
      </button>
    </div>
  </div>
</template>

<style scoped src="../settings-form.css"></style>
<style scoped>
.key-card {
  padding: 0.62rem 0.72rem;
  border-radius: 0.52rem;
  background: var(--surface-sunken);
  border: 1px solid var(--border-subtle);
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
}
.key-card.disabled {
  opacity: 0.55;
}
.key-card-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 0.4rem;
}
.key-title {
  display: flex;
  align-items: baseline;
  gap: 0.4rem;
  min-width: 0;
  flex-wrap: wrap;
}
.key-name {
  color: var(--text-strong);
  font-size: var(--font-size-caption);
  font-weight: 600;
}
.key-id {
  color: var(--accent-strong);
  font-size: var(--font-size-caption);
}
.key-badges {
  display: flex;
  gap: 0.32rem;
  flex-wrap: wrap;
}
.key-badge {
  padding: 0.1rem 0.36rem;
  border-radius: 0.26rem;
  font-size: var(--font-size-caption);
  background: var(--border-default);
  color: var(--accent-strong);
  white-space: nowrap;
}
.badge-ok {
  background: var(--success-surface);
  color: var(--success);
}
.badge-fail {
  background: var(--danger-surface);
  color: var(--danger);
}
.badge-primary {
  background: var(--accent-surface);
  color: var(--accent-strong);
}
.badge-alt {
  background: var(--warning-surface);
  color: var(--accent-warm);
}
.key-desc {
  margin: 0;
  color: var(--text-muted);
  font-size: var(--font-size-caption);
  line-height: 1.5;
  word-break: break-all;
}
.key-desc code {
  color: var(--text-primary);
}
.test-msg {
  margin: 0;
  color: var(--danger);
  font-size: var(--font-size-caption);
  word-break: break-all;
}
.test-msg.ok {
  color: var(--success);
}
</style>
