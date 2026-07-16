<script setup lang="ts">
import { computed } from 'vue'
import { storeToRefs } from 'pinia'
import { useSettingsStore } from '../../stores/settings'

const settingsStore = useSettingsStore()
const { dataSourceConfig } = storeToRefs(settingsStore)

const storageItems = computed(() => {
  if (!dataSourceConfig.value) return []
  const cfg = dataSourceConfig.value
  return [
    { label: '存储后端类型', value: cfg.storage_backend },
    { label: '数据根目录', value: cfg.data_root || '未配置' },
    { label: '产物输出目录', value: cfg.output_root || '未配置' },
    { label: '下载源根目录', value: cfg.download_source_root || '未配置' },
    { label: '真实抓取', value: cfg.download_real_fetch_enabled ? '启用' : '禁用' },
  ]
})

const tileProxyItems = computed(() => {
  if (!dataSourceConfig.value) return []
  const cfg = dataSourceConfig.value
  return [
    { label: '底图代理', value: cfg.tile_proxy_enabled ? '启用' : '禁用' },
    { label: '代理缓存 TTL', value: `${cfg.tile_proxy_cache_ttl_seconds} 秒` },
  ]
})

const minioItems = computed(() => {
  if (!dataSourceConfig.value?.minio) return []
  const m = dataSourceConfig.value.minio
  return [
    { label: 'MinIO 端点', value: m.endpoint },
    { label: '存储桶', value: m.bucket },
    { label: 'HTTPS', value: m.secure ? '是' : '否' },
  ]
})
</script>

<template>
  <div class="data-source-settings">
    <section class="settings-section">
      <h3 class="section-title">存储配置</h3>
      <div class="info-grid">
        <div v-for="item in storageItems" :key="item.label" class="info-row">
          <span class="info-label">{{ item.label }}</span>
          <span class="info-value" :title="item.value">{{ item.value }}</span>
        </div>
      </div>
    </section>

    <section class="settings-section">
      <h3 class="section-title">底图代理</h3>
      <div class="info-grid">
        <div v-for="item in tileProxyItems" :key="item.label" class="info-row">
          <span class="info-label">{{ item.label }}</span>
          <span class="info-value">{{ item.value }}</span>
        </div>
      </div>
    </section>

    <section v-if="minioItems.length > 0" class="settings-section">
      <h3 class="section-title">MinIO 对象存储</h3>
      <div class="info-grid">
        <div v-for="item in minioItems" :key="item.label" class="info-row">
          <span class="info-label">{{ item.label }}</span>
          <span class="info-value">{{ item.value }}</span>
        </div>
      </div>
    </section>

    <p class="section-hint">
      数据源配置通过环境变量设定，如需修改请编辑后端 .env 文件并重启服务。
    </p>
  </div>
</template>

<style scoped>
.data-source-settings {
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
