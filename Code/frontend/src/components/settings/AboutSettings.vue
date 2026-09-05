<script setup lang="ts">
import { computed, ref, toRef } from 'vue'
import { useSettingsStore } from '../../stores/settings'
import { useAuthStore } from '../../stores/auth'
import Tooltip from '../ui/Tooltip.vue'
import SystemStatusSettings from './SystemStatusSettings.vue'

const settingsStore = useSettingsStore()
const authStore = useAuthStore()
const brand = computed(() => authStore.resolvedBrand)
const aboutInfo = toRef(settingsStore, 'aboutInfo')
const weatherConfig = toRef(settingsStore, 'weatherConfig')
const geeRuntimeConfig = toRef(settingsStore, 'geeRuntimeConfig')
const dataSourceConfig = toRef(settingsStore, 'dataSourceConfig')

const selectedLayerId = ref<string | null>(null)

type NodeStatus = 'enabled' | 'disabled' | 'loading'
type StatusKey = 'gee' | 'weather' | 'data'

type ArchItem = {
  title: string
  tech?: string
  statusKey?: StatusKey
}

type ArchLayer = {
  id: string
  title: string
  blurb: string
  statusKey?: StatusKey
  items: ArchItem[]
}

/** 运维向分层示意（入口 → 网关 → 服务 → 引擎 → 数据），弱化技术脑图枝杈 */
const archLayers = computed((): ArchLayer[] => [
  {
    id: 'entry',
    title: '使用入口',
    blurb: '浏览器打开同域页面（默认 :5175）',
    items: [
      { title: '地图与界面', tech: 'Vue 3' },
      { title: '二维地图', tech: 'MapLibre' },
      { title: '三维地球（实验）', tech: 'Cesium' },
      { title: '统计图表', tech: 'ECharts' },
    ],
  },
  {
    id: 'gateway',
    title: '同域网关',
    blurb: '静态页面与 API 统一入口，转发到后端',
    items: [{ title: 'Nginx Gateway', tech: '同域反代' }],
  },
  {
    id: 'services',
    title: '应用服务',
    blurb: '接口、后台任务与定时调度',
    items: [
      { title: '接口服务', tech: 'FastAPI' },
      { title: '后台任务', tech: 'Celery Worker' },
      { title: '定时调度', tech: 'Celery Beat' },
      { title: '缓存队列', tech: 'Redis' },
      { title: '业务库', tech: 'SQLite' },
    ],
  },
  {
    id: 'engines',
    title: '分析引擎',
    blurb: '天气、遥感与算法计算',
    items: [
      { title: '天气引擎', tech: 'Open-Meteo 等', statusKey: 'weather' },
      { title: 'GEE 引擎', tech: 'Google Earth Engine', statusKey: 'gee' },
      { title: '算法引擎', tech: 'Python 模块' },
    ],
  },
  {
    id: 'data',
    title: '数据与存储',
    blurb: '本地盘、对象存储与气象同步数据',
    statusKey: 'data',
    items: [
      { title: '本地数据根', tech: '文件系统' },
      { title: '对象存储', tech: 'MinIO' },
      { title: '气象本地库', tech: 'Open-Meteo' },
    ],
  },
])

const nodeStatuses = computed<Record<StatusKey, NodeStatus>>(() => ({
  gee: geeRuntimeConfig.value
    ? geeRuntimeConfig.value.gee_enabled
      ? 'enabled'
      : 'disabled'
    : 'loading',
  weather: weatherConfig.value ? 'enabled' : 'loading',
  data: dataSourceConfig.value ? 'enabled' : 'loading',
}))

const STATUS_LABEL: Record<NodeStatus, string> = {
  enabled: '已就绪',
  disabled: '已关闭',
  loading: '读取中',
}

function statusOfKey(key?: StatusKey): NodeStatus | null {
  return key ? nodeStatuses.value[key] : null
}

function statusTooltip(title: string, key?: StatusKey): string {
  const status = statusOfKey(key)
  return status ? `${title}：${STATUS_LABEL[status]}` : title
}

function selectLayer(id: string) {
  selectedLayerId.value = selectedLayerId.value === id ? null : id
}

// 浏览器内核识别（About「前端界面」行）：UA 解析浏览器 + 渲染内核
function detectBrowserEngine(): string {
  const ua = navigator.userAgent
  const edge = ua.match(/Edg\w*\/([\d.]+)/)
  if (edge) return `Edge ${edge[1]}（Blink 内核）`
  const chrome = ua.match(/Chrome\/([\d.]+)/)
  if (chrome) return `Chrome ${chrome[1]}（Blink 内核）`
  const firefox = ua.match(/Firefox\/([\d.]+)/)
  if (firefox) return `Firefox ${firefox[1]}（Gecko 内核）`
  const webkit = ua.match(/AppleWebKit\/([\d.]+)/)
  const safari = ua.match(/Version\/([\d.]+) Safari/)
  if (safari) return `Safari ${safari[1]}（WebKit${webkit ? ` ${webkit[1]}` : ''} 内核）`
  if (webkit) return `WebKit ${webkit[1]}`
  return '未知浏览器内核'
}

const browserEngine = detectBrowserEngine()
</script>

<template>
  <div class="about-settings">
    <SystemStatusSettings />

    <!-- 项目信息 -->
    <section class="settings-section">
      <h3 class="section-title">项目信息</h3>
      <div v-if="aboutInfo" class="about-info">
        <div class="info-row">
          <span class="info-label">项目名称</span>
          <span class="info-value">{{ brand.displayNameEn }}</span>
        </div>
        <div class="info-row">
          <span class="info-label">版本</span>
          <span class="info-value">{{ aboutInfo.version }}</span>
        </div>
        <div class="info-row">
          <span class="info-label">描述</span>
          <span class="info-value">{{ aboutInfo.description }}</span>
        </div>
        <div class="info-row">
          <span class="info-label">后端服务</span>
          <span class="info-value">{{ aboutInfo.project_name }}</span>
        </div>
        <div class="info-row">
          <span class="info-label">当前浏览器</span>
          <span class="info-value">{{ browserEngine }}</span>
        </div>
      </div>
      <p v-else class="loading-hint">加载中...</p>
    </section>

    <!-- 技术栈 -->
    <section v-if="aboutInfo" class="settings-section">
      <h3 class="section-title">技术栈</h3>
      <div class="tech-stack">
        <span v-for="tech in aboutInfo.tech_stack" :key="tech" class="tech-tag">
          {{ tech }}
        </span>
      </div>
    </section>

    <!-- 运维向分层架构 -->
    <section class="settings-section">
      <h3 class="section-title">系统架构图</h3>
      <p class="section-hint">
        从上到下是一次请求怎么走：入口 → 网关 → 服务 → 引擎 →
        数据。色点表示相关能力是否已配好（悬停可看说明）。
      </p>
      <div class="arch-stack">
        <template v-for="(layer, idx) in archLayers" :key="layer.id">
          <div v-if="idx > 0" class="arch-flow" aria-hidden="true">↓</div>
          <Tooltip :text="statusTooltip(layer.title, layer.statusKey)" block>
            <div
              class="arch-layer"
              :class="[
                statusOfKey(layer.statusKey) ?? '',
                { selected: selectedLayerId === layer.id },
              ]"
              role="button"
              tabindex="0"
              @click="selectLayer(layer.id)"
              @keydown.enter.prevent="selectLayer(layer.id)"
              @keydown.space.prevent="selectLayer(layer.id)"
            >
              <div class="arch-layer-head">
                <div class="arch-layer-titles">
                  <span class="arch-layer-title">{{ layer.title }}</span>
                  <span class="arch-layer-blurb">{{ layer.blurb }}</span>
                </div>
                <span
                  v-if="statusOfKey(layer.statusKey)"
                  class="status-dot"
                  :class="statusOfKey(layer.statusKey)"
                ></span>
              </div>
              <div class="arch-layer-items">
                <Tooltip
                  v-for="item in layer.items"
                  :key="item.title"
                  :text="statusTooltip(item.title, item.statusKey)"
                >
                  <div class="arch-item" :class="statusOfKey(item.statusKey) ?? ''">
                    <span class="arch-item-title">{{ item.title }}</span>
                    <span v-if="item.tech" class="arch-item-tech">{{ item.tech }}</span>
                    <span
                      v-if="statusOfKey(item.statusKey)"
                      class="status-dot"
                      :class="statusOfKey(item.statusKey)"
                    ></span>
                  </div>
                </Tooltip>
              </div>
            </div>
          </Tooltip>
        </template>
      </div>
    </section>

    <!-- 功能模块 -->
    <section v-if="aboutInfo" class="settings-section">
      <h3 class="section-title">功能模块</h3>
      <div class="module-list">
        <div v-for="mod in aboutInfo.modules" :key="mod.name" class="module-card">
          <span class="module-name">{{ mod.name }}</span>
          <span class="module-desc">{{ mod.description }}</span>
        </div>
      </div>
    </section>

    <!-- 架构概述 -->
    <section v-if="aboutInfo" class="settings-section">
      <h3 class="section-title">架构概述</h3>
      <p class="arch-summary">{{ aboutInfo.architecture_summary }}</p>
    </section>
  </div>
</template>

<style scoped>
.about-settings {
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
  color: var(--text-strong);
  font-size: var(--font-size-caption);
  font-weight: 600;
}

.section-hint {
  margin: 0 0 0.45rem;
  color: var(--text-muted);
  font-size: 0.75rem;
  line-height: 1.45;
}

.about-info,
.info-grid {
  display: flex;
  flex-direction: column;
  gap: 0.22rem;
}

.info-row {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 0.62rem;
  padding: 0.36rem 0.52rem;
  border-radius: 0.4rem;
  background: var(--surface-sunken);
  border: 1px solid var(--border-subtle);
}

.info-label {
  color: var(--text-muted);
  font-size: var(--font-size-caption);
  flex: none;
}

.info-value {
  color: var(--text-primary);
  font-size: var(--font-size-caption);
  text-align: right;
  flex: 1;
  min-width: 0;
  line-height: 1.5;
  /* 长值（英文服务名/中文描述）允许在行内断行，避免溢出容器 */
  overflow-wrap: break-word;
}

.loading-hint {
  color: var(--text-disabled);
  font-size: var(--font-size-caption);
}

/* 技术栈标签云 */
.tech-stack {
  display: flex;
  flex-wrap: wrap;
  gap: 0.32rem;
}

.tech-tag {
  padding: 0.22rem 0.52rem;
  border-radius: 999px;
  background: var(--accent-surface);
  border: 1px solid var(--accent-surface);
  color: var(--accent);
  font-size: var(--font-size-caption);
  font-weight: 500;
}

/* 运维向分层架构 */
.arch-stack {
  display: flex;
  flex-direction: column;
  gap: 0;
  padding: 0.55rem;
  border-radius: 0.52rem;
  background: var(--surface-raised);
  border: 1px solid var(--border-subtle);
}

.arch-flow {
  align-self: center;
  color: var(--text-faint);
  font-size: 0.85rem;
  line-height: 1.2;
  padding: 0.15rem 0;
  user-select: none;
}

.arch-layer {
  display: flex;
  flex-direction: column;
  gap: 0.45rem;
  width: 100%;
  box-sizing: border-box;
  padding: 0.55rem 0.65rem;
  border-radius: 0.45rem;
  border: 1px solid var(--border-subtle);
  background: var(--surface-1);
  cursor: pointer;
  text-align: left;
  transition:
    border-color 0.15s ease,
    background 0.15s ease,
    box-shadow 0.15s ease;
}

.arch-layer:hover {
  border-color: var(--border-default);
  background: color-mix(in srgb, var(--surface-2, var(--surface-1)) 90%, transparent);
}

.arch-layer.selected {
  border-color: var(--accent-border);
  box-shadow: 0 0 0 1px color-mix(in srgb, var(--accent-border) 50%, transparent);
}

.arch-layer.enabled {
  border-color: color-mix(in srgb, var(--success-border) 55%, var(--border-subtle));
}

.arch-layer.disabled {
  opacity: 0.72;
}

.arch-layer-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 0.5rem;
}

.arch-layer-titles {
  display: flex;
  flex-direction: column;
  gap: 0.15rem;
  min-width: 0;
}

.arch-layer-title {
  font-size: var(--font-size-caption);
  font-weight: 600;
  color: var(--text-strong);
  line-height: 1.35;
}

.arch-layer-blurb {
  font-size: 0.72rem;
  color: var(--text-muted);
  line-height: 1.4;
}

.arch-layer-items {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem;
}

.arch-item {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  max-width: 100%;
  padding: 0.28rem 0.5rem;
  border-radius: 0.35rem;
  border: 1px solid var(--border-subtle);
  background: var(--surface-sunken, var(--surface-raised));
  color: var(--text-secondary);
}

.arch-item.enabled {
  border-color: var(--success-border);
}

.arch-item.disabled {
  opacity: 0.55;
}

.arch-item-title {
  font-size: 0.72rem;
  font-weight: 500;
  color: var(--text-primary);
  line-height: 1.3;
}

.arch-item-tech {
  font-size: 0.65rem;
  color: var(--text-faint);
  line-height: 1.3;
}

.status-dot {
  display: inline-block;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  flex: none;
}

.status-dot.enabled {
  background: var(--success);
  box-shadow: 0 0 5px var(--success-border);
}

.status-dot.disabled {
  background: var(--text-disabled);
}

.status-dot.loading {
  background: var(--warning);
}

/* 功能模块 */
.module-list {
  display: flex;
  flex-direction: column;
  gap: 0.32rem;
}

.module-card {
  display: flex;
  flex-direction: column;
  gap: 0.16rem;
  padding: 0.42rem 0.62rem;
  border-radius: 0.4rem;
  background: var(--surface-sunken);
  border: 1px solid var(--border-subtle);
}

.module-name {
  color: var(--accent);
  font-size: var(--font-size-caption);
  font-weight: 600;
}

.module-desc {
  color: var(--text-muted);
  font-size: var(--font-size-caption);
  line-height: 1.4;
}

.arch-summary {
  margin: 0;
  color: var(--text-secondary);
  font-size: var(--font-size-caption);
  line-height: 1.6;
}
</style>
