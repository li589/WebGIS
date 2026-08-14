<script setup lang="ts">
/**
 * PortalCredHint.vue
 *
 * 门户凭据状态提示（下载节点表单共用）。
 *
 * 下载模块在节点 username/password 留空时会回退到门户凭据库
 * （earthdata / nsmc / copernicus …，见设置 → 远程与存储 → 开放门户）。
 * 本组件读取门户目录，显示对应凭据键的配置状态与配置入口提示。
 *
 * Props: credKey（凭据键，如 earthdata / nsmc）
 */
import { computed, onMounted, ref } from 'vue'
import { fetchPortalCatalog } from '../../../services/settings-api'
import type { PortalCatalogEntry } from '../../../types/api-reexports'

const props = defineProps<{
  credKey: string
}>()

const portals = ref<PortalCatalogEntry[]>([])

const entry = computed(
  () =>
    portals.value.find(
      (p) => p.portal_id === props.credKey || String(p.credential_profile || '') === props.credKey,
    ) ?? null,
)

const otherPortalsWithKey = computed(() =>
  portals.value.filter(
    (p) => p !== entry.value && String(p.credential_profile || '') === props.credKey,
  ),
)

onMounted(async () => {
  try {
    const data = await fetchPortalCatalog()
    portals.value = (data.portals ?? []).slice()
  } catch {
    portals.value = []
  }
})
</script>

<template>
  <div class="cred-hint-row">
    <template v-if="entry">
      <span class="cred-dot" :class="{ ok: entry.has_credentials }"></span>
      <span class="cred-text">
        <template v-if="entry.has_credentials">
          {{ entry.name }}凭据已配置（{{ credKey }}），节点无需填写账号密码
        </template>
        <template v-else>
          未配置 {{ entry.name }}凭据（{{ credKey }}）— 设置 → 远程与存储 → 开放门户
          <span v-if="entry.credentials_hint" class="cred-note" :title="entry.credentials_hint">
            {{ entry.credentials_hint }}
          </span>
        </template>
      </span>
    </template>
    <template v-else-if="portals.length">
      <span class="cred-dot"></span>
      <span class="cred-text">
        凭据 {{ credKey }}：设置 → 远程与存储 → 开放门户 配置；留空账号密码时自动使用
      </span>
    </template>
    <template v-else>
      <span class="cred-dot"></span>
      <span class="cred-text">账号密码留空时使用门户凭据库（设置 → 远程与存储 → 开放门户）</span>
    </template>
    <span
      v-if="entry && otherPortalsWithKey.length"
      class="cred-shared"
      :title="otherPortalsWithKey.map((p) => p.name).join('、')"
    >
      {{ otherPortalsWithKey.length }} 个门户共用此凭据
    </span>
  </div>
</template>

<style scoped>
.cred-hint-row {
  display: flex;
  align-items: center;
  gap: 0.36rem;
  padding: 0.3rem 0.42rem;
  border: 1px solid var(--border-subtle);
  border-radius: 0.32rem;
  background: var(--surface-sunken);
  font-size: var(--font-size-caption);
  color: var(--text-muted);
  flex-wrap: wrap;
}

.cred-dot {
  flex: none;
  width: 0.56rem;
  height: 0.56rem;
  border-radius: 50%;
  border: 1px solid var(--surface-3);
  background: var(--danger);
}

.cred-dot.ok {
  background: var(--success);
}

.cred-text {
  min-width: 0;
  line-height: 1.4;
}

.cred-note {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--text-faint);
}

.cred-shared {
  margin-left: auto;
  flex: none;
  color: var(--text-faint);
  white-space: nowrap;
}
</style>
