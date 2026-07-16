<script setup lang="ts">
import { computed } from 'vue'
import { storeToRefs } from 'pinia'
import { useSettingsStore } from '../../stores/settings'

const settingsStore = useSettingsStore()
const { generalConfig } = storeToRefs(settingsStore)

const readonlyItems = computed(() => {
  if (!generalConfig.value) return []
  const cfg = generalConfig.value
  return [
    { label: '服务名称', value: cfg.service_name },
    { label: '运行环境', value: cfg.environment },
    { label: '监听地址', value: `${cfg.host}:${cfg.port}` },
    { label: '数据根目录', value: cfg.data_root || '未配置' },
    { label: '产物输出目录', value: cfg.output_root || '未配置' },
    { label: '缓存目录', value: cfg.cache_dir },
    { label: '日志目录', value: cfg.log_dir },
    { label: 'Redis 地址', value: cfg.redis_url },
    { label: '存储后端', value: cfg.storage_backend },
    { label: '热重载', value: cfg.reload ? '启用' : '禁用' },
  ]
})

const runtimeItems = computed(() => {
  if (!generalConfig.value) return []
  const cfg = generalConfig.value
  return [
    { label: '日志级别', value: cfg.log_level },
    { label: '最大并发工作流', value: String(cfg.max_active_runs) },
    { label: '最大请求输出数', value: String(cfg.max_requested_outputs) },
  ]
})
</script>

<template>
  <div class="general-settings">
    <section class="settings-section">
      <h3 class="section-title">系统信息</h3>
      <div class="info-grid">
        <div v-for="item in readonlyItems" :key="item.label" class="info-row">
          <span class="info-label">{{ item.label }}</span>
          <span class="info-value" :title="item.value">{{ item.value }}</span>
        </div>
      </div>
    </section>

    <section class="settings-section">
      <h3 class="section-title">运行时参数</h3>
      <div class="info-grid">
        <div v-for="item in runtimeItems" :key="item.label" class="info-row">
          <span class="info-label">{{ item.label }}</span>
          <span class="info-value">{{ item.value }}</span>
        </div>
      </div>
      <p class="section-hint">运行时参数通过环境变量配置，修改后需重启后端生效。</p>
    </section>
  </div>
</template>

<style scoped>
.general-settings {
  display: flex;
  flex-direction: column;
  gap: 1.2rem;
}

.settings-section {
  display: flex;
  flex-direction: column;
  gap: 0.52rem;
}

.section-title {
  margin: 0 0 0.32rem;
  color: #e8f3fc;
  font-size: 0.7rem;
  font-weight: 600;
  letter-spacing: 0.02em;
}

.info-grid {
  display: flex;
  flex-direction: column;
  gap: 0.22rem;
}

.info-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 0.62rem;
  padding: 0.36rem 0.52rem;
  border-radius: 0.4rem;
  background: rgba(4, 12, 23, 0.5);
  border: 1px solid rgba(136, 192, 255, 0.06);
}

.info-label {
  color: #8aa8bf;
  font-size: 0.6rem;
  flex: none;
  white-space: nowrap;
}

.info-value {
  color: #d8e6f5;
  font-size: 0.6rem;
  font-family: 'SF Mono', 'Consolas', monospace;
  text-align: right;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
  min-width: 0;
}

.section-hint {
  margin: 0;
  color: #5a7080;
  font-size: 0.54rem;
  line-height: 1.5;
}
</style>
