<script setup lang="ts">
/**
 * RemoteSourceCard — 远程数据源页的单源卡片（存储 profile 或开放门户）。
 *
 * 徽标：类型 / 协议 / 凭据与测试状态 / 搜索能力。
 * 操作（2026-08-25 改版）：统一单入口「添加为可访问远程数据源」——
 * 检索/浏览并入融合对话框（RemoteSourceAddDialog），卡片不再有独立按钮。
 */

export interface RemoteSourceCardData {
  kind: 'storage_profile' | 'portal'
  refId: string
  name: string
  subtitle: string
  protocol?: string | null
  enabled: boolean
  statusBadge?: { text: string; tone: 'ok' | 'fail' | 'neutral' } | null
  browsable: boolean
  searchable: boolean
  searchLabel?: string
  requiresCredentials?: boolean | null
  hasCredentials?: boolean | null
}

defineProps<{
  source: RemoteSourceCardData
}>()

const emit = defineEmits<{
  add: [source: RemoteSourceCardData]
}>()
</script>

<template>
  <div class="src-card" :class="{ disabled: !source.enabled }">
    <div class="card-head">
      <div class="title-wrap">
        <span class="name">{{ source.name }}</span>
        <code class="ref-id">{{ source.refId }}</code>
      </div>
      <div class="badges">
        <span class="badge">{{
          source.kind === 'portal' ? '门户' : source.protocol || '存储'
        }}</span>
        <span v-if="source.statusBadge" class="badge" :class="`tone-${source.statusBadge.tone}`">
          {{ source.statusBadge.text }}
        </span>
        <span
          v-if="source.requiresCredentials"
          class="badge"
          :class="source.hasCredentials ? 'tone-ok' : 'tone-warn'"
        >
          {{ source.hasCredentials ? '凭据已配置' : '缺凭据' }}
        </span>
        <span v-if="source.searchable" class="badge tone-accent">可检索</span>
        <span v-else-if="source.browsable" class="badge">可浏览</span>
        <span v-else class="badge muted">仅下载</span>
      </div>
    </div>
    <p class="subtitle">{{ source.subtitle }}</p>
    <div class="ops">
      <button type="button" class="btn btn-primary" @click="emit('add', source)">
        添加为可访问远程数据源
      </button>
    </div>
  </div>
</template>

<style scoped>
.src-card {
  padding: 0.62rem 0.72rem;
  border-radius: 0.52rem;
  background: var(--surface-sunken);
  border: 1px solid var(--border-subtle);
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
}
.src-card.disabled {
  opacity: 0.55;
}
.card-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 0.4rem;
  flex-wrap: wrap;
}
.title-wrap {
  display: flex;
  align-items: baseline;
  gap: 0.4rem;
  min-width: 0;
  flex-wrap: wrap;
}
.name {
  color: var(--text-strong);
  font-size: var(--font-size-caption);
  font-weight: 600;
}
.ref-id {
  color: var(--accent-strong);
  font-size: var(--font-size-caption);
}
.badges {
  display: flex;
  gap: 0.32rem;
  flex-wrap: wrap;
}
.badge {
  padding: 0.08rem 0.34rem;
  border-radius: 0.24rem;
  font-size: var(--font-size-caption);
  background: var(--border-default);
  color: var(--accent-strong);
  white-space: nowrap;
}
.badge.muted {
  color: var(--text-muted);
}
.badge.tone-ok {
  background: var(--success-surface);
  color: var(--success);
}
.badge.tone-fail {
  background: var(--danger-surface);
  color: var(--danger);
}
.badge.tone-warn {
  background: var(--warning-surface);
  color: var(--accent-warm);
}
.badge.tone-accent {
  background: var(--accent-surface);
}
.subtitle {
  margin: 0;
  color: var(--text-muted);
  font-size: var(--font-size-caption);
  line-height: 1.5;
  word-break: break-all;
}
.ops {
  display: flex;
  gap: 0.36rem;
  flex-wrap: wrap;
}
.btn {
  border: 1px solid var(--border-strong);
  background: var(--surface-3);
  color: var(--text-strong);
  border-radius: 0.36rem;
  padding: 0.28rem 0.6rem;
  font-size: var(--font-size-caption);
  cursor: pointer;
}
.btn-primary {
  border-color: var(--accent);
  background: var(--accent-surface);
  color: var(--accent-strong);
}
</style>
