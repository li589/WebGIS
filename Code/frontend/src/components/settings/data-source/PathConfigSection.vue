<script setup lang="ts">
/**
 * PathConfigSection — 细分路径配置卡（只读）。
 *
 * 展示数据根 / 产物根 / 静态下载缓存 / 通用缓存目录 / 下载源根的进程生效值。
 * 修改入口已收敛至「部署与数据源配置中心」（/deployment，仅 admin）：
 * 变更经校验、预览后原子应用，重启 FastAPI + Worker + Beat 生效；
 * 本卡不再提供编辑与保存（旧 PUT /config/data-source/paths 前端入口已下线）。
 */
import { computed } from 'vue'
import { useSettingsStore } from '../../../stores/settings'

const settingsStore = useSettingsStore()

const cfg = computed(() => settingsStore.dataSourceConfig)
const pendingRestart = computed(() => Boolean(cfg.value?.pending_restart))

const envRows = computed(() => {
  const c = cfg.value
  if (!c) return [] as { label: string; value: string }[]
  return [
    { label: '进程生效数据根', value: c.data_root || '未配置' },
    { label: '进程生效产物根', value: c.output_root || '默认' },
    { label: '进程生效静态缓存', value: c.static_cache_root || '默认（数据根下）' },
    { label: '进程生效缓存目录', value: c.cache_dir || '默认' },
    { label: '进程生效下载源根', value: c.download_source_root || '默认' },
  ]
})
</script>

<template>
  <section class="form-card">
    <h4 class="card-title">
      路径配置（只读）
      <span v-if="pendingRestart" class="badge badge-warn" title="配置已保存，待重启后端生效">
        待重启
      </span>
    </h4>
    <p class="card-hint">
      数据路径仅可在「部署与数据源配置中心」修改（需管理员权限）；此处仅展示当前进程生效值。
      变更经校验、预览后原子应用，重启 FastAPI + Worker + Beat 生效。
    </p>

    <div class="env-grid">
      <div v-for="row in envRows" :key="row.label" class="env-row">
        <span class="env-label">{{ row.label }}</span>
        <span class="env-value" :title="row.value">{{ row.value }}</span>
      </div>
    </div>
  </section>
</template>

<style scoped src="../settings-form.css"></style>
<style scoped>
.card-title {
  margin: 0;
  color: var(--text-strong);
  font-size: var(--font-size-caption);
  font-weight: 600;
  display: flex;
  align-items: center;
  gap: 0.4rem;
}
.card-hint {
  margin: 0;
  color: var(--text-muted);
  font-size: var(--font-size-caption);
  line-height: 1.45;
}
.badge {
  padding: 0.06rem 0.32rem;
  border-radius: 0.24rem;
  font-size: var(--font-size-caption);
}
.badge-warn {
  background: var(--warning-surface);
  color: var(--accent-warm);
}
.env-grid {
  display: flex;
  flex-direction: column;
  gap: 0.28rem;
}
.env-row {
  display: grid;
  grid-template-columns: 8.5rem 1fr;
  gap: 0.5rem;
  font-size: var(--font-size-caption);
  align-items: center;
}
.env-label {
  color: var(--text-muted);
}
.env-value {
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
