<script setup lang="ts">
import { computed, ref } from 'vue'
import { storeToRefs } from 'pinia'
import { useSettingsStore } from '../../stores/settings'
import { BRAND } from '../../ui-copy'

const settingsStore = useSettingsStore()
const { aboutInfo, weatherConfig, geeRuntimeConfig, dataSourceConfig } = storeToRefs(settingsStore)

const selectedNode = ref<string | null>(null)

// 架构树节点
const archTree = computed(() => [
  {
    name: BRAND.fullName,
    level: 0,
    children: [
      {
        name: '前端层',
        level: 1,
        children: [
          { name: 'UI 组件 (Vue 3)', level: 2 },
          { name: 'Pinia Store', level: 2 },
          { name: 'MapLibre GL', level: 2 },
          { name: 'Vite 构建', level: 2 },
        ],
      },
      {
        name: '后端层',
        level: 1,
        children: [
          { name: 'FastAPI 路由', level: 2 },
          { name: 'Celery 工作流', level: 2 },
          { name: 'Redis 缓存', level: 2 },
          { name: 'SQLite 持久化', level: 2 },
        ],
      },
      {
        name: '引擎层',
        level: 1,
        children: [
          { name: 'GEE 引擎', level: 2 },
          { name: '天气引擎', level: 2 },
          { name: '算法引擎', level: 2 },
        ],
      },
      {
        name: '数据层',
        level: 1,
        children: [
          { name: '本地文件系统', level: 2 },
          { name: 'MinIO 对象存储', level: 2 },
          { name: '远程 FileBrowser', level: 2 },
        ],
      },
    ],
  },
])

function selectNode(name: string) {
  selectedNode.value = selectedNode.value === name ? null : name
}
</script>

<template>
  <div class="about-settings">
    <!-- 项目信息 -->
    <section class="settings-section">
      <h3 class="section-title">项目信息</h3>
      <div v-if="aboutInfo" class="about-info">
        <div class="info-row">
          <span class="info-label">项目名称</span>
          <span class="info-value">{{ aboutInfo.project_name }}</span>
        </div>
        <div class="info-row">
          <span class="info-label">版本</span>
          <span class="info-value">{{ aboutInfo.version }}</span>
        </div>
        <div class="info-row">
          <span class="info-label">描述</span>
          <span class="info-value">{{ aboutInfo.description }}</span>
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
          <!-- 根节点 -->
          <div
            class="arch-node root"
            :class="{ selected: selectedNode === rootNode.name }"
            @click="selectNode(rootNode.name)"
          >
            {{ rootNode.name }}
          </div>

          <!-- 连接线 -->
          <div class="arch-connector"></div>

          <!-- 子节点 -->
          <div class="arch-children">
            <div v-for="child in rootNode.children" :key="child.name" class="arch-branch">
              <div
                class="arch-node level-1"
                :class="{ selected: selectedNode === child.name }"
                @click="selectNode(child.name)"
              >
                {{ child.name }}
              </div>
              <div class="arch-connector sub"></div>
              <div class="arch-leaves">
                <div
                  v-for="leaf in child.children"
                  :key="leaf.name"
                  class="arch-node level-2"
                  :class="{ selected: selectedNode === leaf.name }"
                  @click="selectNode(leaf.name)"
                >
                  {{ leaf.name }}
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

    <!-- 引擎状态摘要 -->
    <section class="settings-section">
      <h3 class="section-title">引擎状态</h3>
      <div class="engine-status">
        <div class="engine-card" :class="{ active: geeRuntimeConfig?.gee_enabled }">
          <span class="engine-name">GEE 引擎</span>
          <span class="engine-state">{{ geeRuntimeConfig?.gee_enabled ? '启用' : '禁用' }}</span>
        </div>
        <div class="engine-card" :class="{ active: !!weatherConfig }">
          <span class="engine-name">天气引擎</span>
          <span class="engine-state">{{ weatherConfig ? '启用' : '加载中' }}</span>
        </div>
        <div class="engine-card" :class="{ active: !!dataSourceConfig }">
          <span class="engine-name">数据引擎</span>
          <span class="engine-state">{{ dataSourceConfig ? '启用' : '加载中' }}</span>
        </div>
      </div>
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
  color: #e8f3fc;
  font-size: 0.7rem;
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
  justify-content: space-between;
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
}

.info-value {
  color: #d8e6f5;
  font-size: 0.6rem;
  text-align: right;
  flex: 1;
}

.loading-hint {
  color: #5a7080;
  font-size: 0.6rem;
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
  background: rgba(10, 132, 255, 0.14);
  border: 1px solid rgba(90, 213, 255, 0.18);
  color: #5ad5ff;
  font-size: 0.56rem;
  font-weight: 500;
}

/* 架构图 */
.arch-diagram {
  padding: 0.62rem;
  border-radius: 0.52rem;
  background: rgba(4, 12, 23, 0.6);
  border: 1px solid rgba(136, 192, 255, 0.08);
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
  font-size: 0.58rem;
  font-weight: 500;
  transition: all 0.16s ease;
  white-space: nowrap;
}

.arch-node.root {
  background: linear-gradient(135deg, rgba(10, 132, 255, 0.3), rgba(125, 125, 255, 0.2));
  border: 1px solid rgba(90, 213, 255, 0.4);
  color: #f0faff;
  font-size: 0.64rem;
  font-weight: 600;
}

.arch-node.level-1 {
  background: rgba(10, 132, 255, 0.16);
  border: 1px solid rgba(90, 213, 255, 0.22);
  color: #5ad5ff;
}

.arch-node.level-2 {
  background: rgba(4, 12, 23, 0.6);
  border: 1px solid rgba(136, 192, 255, 0.1);
  color: #8aa8bf;
}

.arch-node:hover {
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(10, 132, 255, 0.18);
}

.arch-node.selected {
  border-color: rgba(90, 213, 255, 0.6);
  box-shadow: 0 0 0 2px rgba(90, 213, 255, 0.2);
}

.arch-connector {
  width: 1px;
  height: 0.72rem;
  background: rgba(136, 192, 255, 0.2);
}

.arch-connector.sub {
  height: 0.52rem;
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
  background: rgba(4, 12, 23, 0.5);
  border: 1px solid rgba(136, 192, 255, 0.06);
}

.module-name {
  color: #5ad5ff;
  font-size: 0.62rem;
  font-weight: 600;
}

.module-desc {
  color: #8aa8bf;
  font-size: 0.56rem;
  line-height: 1.4;
}

.arch-summary {
  margin: 0;
  color: #9fb6cc;
  font-size: 0.58rem;
  line-height: 1.6;
}

/* 引擎状态 */
.engine-status {
  display: flex;
  gap: 0.52rem;
  flex-wrap: wrap;
}

.engine-card {
  display: flex;
  flex-direction: column;
  gap: 0.16rem;
  padding: 0.42rem 0.72rem;
  border-radius: 0.4rem;
  background: rgba(4, 12, 23, 0.5);
  border: 1px solid rgba(136, 192, 255, 0.1);
  opacity: 0.6;
}

.engine-card.active {
  opacity: 1;
  border-color: rgba(114, 255, 207, 0.2);
  background: rgba(114, 255, 207, 0.06);
}

.engine-name {
  color: #d8e6f5;
  font-size: 0.62rem;
  font-weight: 600;
}

.engine-state {
  color: #8aa8bf;
  font-size: 0.54rem;
}

.engine-card.active .engine-state {
  color: #9ff8cf;
}
</style>
