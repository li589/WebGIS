<script setup lang="ts">
import { computed, ref, toRef } from 'vue'
import { useSettingsStore } from '../../stores/settings'
import { BRAND } from '../../ui-copy'
import Tooltip from '../ui/Tooltip.vue'
import SystemStatusSettings from './SystemStatusSettings.vue'

const settingsStore = useSettingsStore()
const aboutInfo = toRef(settingsStore, 'aboutInfo')
const weatherConfig = toRef(settingsStore, 'weatherConfig')
const geeRuntimeConfig = toRef(settingsStore, 'geeRuntimeConfig')
const dataSourceConfig = toRef(settingsStore, 'dataSourceConfig')

const selectedNode = ref<string | null>(null)

type NodeStatus = 'enabled' | 'disabled' | 'loading'
type StatusKey = 'gee' | 'weather' | 'data'

type ArchNode = {
  name: string
  level: number
  statusKey?: StatusKey
  children?: ArchNode[]
}

// 架构树节点 — 与当前实际部署拓扑一致（AGENTS.md / infra 现状）：
// Nginx Gateway 为默认同域入口；MapLibre 为 2D 主路径、Cesium 3D 实验链；
// 后端 FastAPI + Celery（Worker/Beat）；数据面含 Open-Meteo 与 MinIO。
const archTree = computed((): ArchNode[] => [
  {
    name: BRAND.fullName,
    level: 0,
    children: [
      {
        name: '前端层',
        level: 1,
        children: [
          { name: 'Vue 3 + TypeScript', level: 2 },
          { name: 'Pinia Store', level: 2 },
          { name: 'MapLibre GL 2D', level: 2 },
          { name: 'Cesium 3D（实验）', level: 2 },
          { name: 'ECharts 图表', level: 2 },
          { name: 'Vite 构建', level: 2 },
        ],
      },
      {
        name: '网关层',
        level: 1,
        children: [{ name: 'Nginx Gateway', level: 2 }],
      },
      {
        name: '后端层',
        level: 1,
        children: [
          { name: 'FastAPI 路由', level: 2 },
          { name: 'Celery 工作流', level: 2 },
          { name: 'Celery Beat 定时', level: 2 },
          { name: 'Redis 缓存', level: 2 },
          { name: 'SQLite 持久化', level: 2 },
        ],
      },
      {
        name: '引擎层',
        level: 1,
        children: [
          { name: 'GEE 引擎', level: 2, statusKey: 'gee' },
          { name: '天气引擎', level: 2, statusKey: 'weather' },
          { name: '算法引擎', level: 2 },
        ],
      },
      {
        name: '数据层',
        level: 1,
        statusKey: 'data',
        children: [
          { name: '本地文件系统', level: 2 },
          { name: 'MinIO 对象存储', level: 2 },
          { name: 'Open-Meteo 气象数据', level: 2 },
          {
            name: '远程存储',
            level: 2,
            children: [{ name: '开放数据站', level: 3 }],
          },
        ],
      },
    ],
  },
])

// 引擎/数据服务启停状态 — 取代原「引擎状态」卡片区，以架构图节点颜色 + 悬停提示呈现
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
  enabled: '启用',
  disabled: '关闭',
  loading: '加载中',
}

function statusOf(node: ArchNode): NodeStatus | null {
  return node.statusKey ? nodeStatuses.value[node.statusKey] : null
}

function statusTooltip(node: ArchNode): string {
  const status = statusOf(node)
  return status ? `${node.name}：${STATUS_LABEL[status]}` : ''
}

function selectNode(name: string) {
  selectedNode.value = selectedNode.value === name ? null : name
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
          <span class="info-value">{{ BRAND.displayNameEn }}</span>
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
          <span class="info-label">前端界面</span>
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

    <!-- 架构思维导图 -->
    <section class="settings-section">
      <h3 class="section-title">系统架构图</h3>
      <div class="arch-diagram">
        <div v-for="rootNode in archTree" :key="rootNode.name" class="arch-node-container">
          <div
            class="arch-node root"
            :class="{ selected: selectedNode === rootNode.name }"
            role="button"
            tabindex="0"
            @click="selectNode(rootNode.name)"
            @keydown.enter.prevent="selectNode(rootNode.name)"
            @keydown.space.prevent="selectNode(rootNode.name)"
          >
            {{ rootNode.name }}
          </div>

          <div class="arch-connector"></div>

          <div class="arch-children">
            <div v-for="child in rootNode.children" :key="child.name" class="arch-branch">
              <Tooltip :text="statusTooltip(child)">
                <div
                  class="arch-node level-1"
                  :class="[statusOf(child) ?? '', { selected: selectedNode === child.name }]"
                  role="button"
                  tabindex="0"
                  @click="selectNode(child.name)"
                  @keydown.enter.prevent="selectNode(child.name)"
                  @keydown.space.prevent="selectNode(child.name)"
                >
                  {{ child.name }}
                  <span v-if="statusOf(child)" class="status-dot" :class="statusOf(child)"></span>
                </div>
              </Tooltip>
              <div class="arch-connector sub"></div>
              <div class="arch-leaves">
                <div v-for="leaf in child.children" :key="leaf.name" class="arch-leaf-wrap">
                  <Tooltip :text="statusTooltip(leaf)">
                    <div
                      class="arch-node level-2"
                      :class="[statusOf(leaf) ?? '', { selected: selectedNode === leaf.name }]"
                      role="button"
                      tabindex="0"
                      @click="selectNode(leaf.name)"
                      @keydown.enter.prevent="selectNode(leaf.name)"
                      @keydown.space.prevent="selectNode(leaf.name)"
                    >
                      {{ leaf.name }}
                      <span v-if="statusOf(leaf)" class="status-dot" :class="statusOf(leaf)"></span>
                    </div>
                  </Tooltip>
                  <template v-if="leaf.children?.length">
                    <div class="arch-connector nested"></div>
                    <div class="arch-nested">
                      <div
                        v-for="nested in leaf.children"
                        :key="nested.name"
                        class="arch-node level-3"
                        :class="{ selected: selectedNode === nested.name }"
                        role="button"
                        tabindex="0"
                        @click="selectNode(nested.name)"
                        @keydown.enter.prevent="selectNode(nested.name)"
                        @keydown.space.prevent="selectNode(nested.name)"
                      >
                        {{ nested.name }}
                      </div>
                    </div>
                  </template>
                </div>
              </div>
            </div>
          </div>
        </div>
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

/* 架构图 */
.arch-diagram {
  padding: 0.62rem;
  border-radius: 0.52rem;
  background: var(--surface-raised);
  border: 1px solid var(--border-subtle);
  overflow-x: auto;
}

.arch-node-container {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0;
}

.arch-node {
  padding: 0.32rem 0.72rem;
  border-radius: 0.4rem;
  cursor: pointer;
  font-size: var(--font-size-caption);
  font-weight: 500;
  transition: all 0.16s ease;
  white-space: nowrap;
}

.arch-node.root {
  background: linear-gradient(135deg, var(--accent-border), var(--surface-violet-tint));
  border: 1px solid var(--border-strong);
  color: var(--text-strong);
  font-size: var(--font-size-caption);
  font-weight: 600;
}

.arch-node.level-1 {
  background: var(--accent-surface);
  border: 1px solid var(--accent-border);
  color: var(--accent);
}

.arch-node.level-2 {
  background: var(--surface-raised);
  border: 1px solid var(--border-subtle);
  color: var(--text-muted);
}

.arch-node.level-3 {
  background: var(--surface-raised);
  border: 1px dashed var(--border-default);
  color: var(--text-muted);
  font-size: var(--font-size-caption);
}

/* 引擎/数据服务状态（颜色承载状态，悬停经 Tooltip 显示文字说明） */
.arch-node.enabled {
  border-color: var(--success-border);
}

.arch-node.disabled {
  opacity: 0.55;
}

.status-dot {
  display: inline-block;
  width: 6px;
  height: 6px;
  margin-left: 0.45em;
  border-radius: 50%;
  vertical-align: middle;
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

.arch-node:hover {
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(10, 132, 255, 0.18);
}

.arch-node.selected {
  border-color: var(--border-strong);
  box-shadow: 0 0 0 2px var(--accent-border);
}

.arch-connector {
  width: 1px;
  height: 0.72rem;
  background: var(--border-strong);
}

.arch-connector.sub {
  height: 0.52rem;
}

.arch-connector.nested {
  height: 0.36rem;
}

.arch-children {
  display: flex;
  gap: 0.82rem;
  flex-wrap: wrap;
  justify-content: center;
}

.arch-branch {
  display: flex;
  flex-direction: column;
  align-items: center;
}

.arch-leaves {
  display: flex;
  flex-direction: column;
  gap: 0.22rem;
  align-items: center;
}

.arch-leaf-wrap {
  display: flex;
  flex-direction: column;
  align-items: center;
}

.arch-nested {
  display: flex;
  flex-direction: column;
  gap: 0.16rem;
  align-items: center;
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
