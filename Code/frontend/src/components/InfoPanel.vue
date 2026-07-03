<script setup lang="ts">
import { computed } from 'vue'

import type { ActiveLayerDisplay } from '../stores/layers/types'
import type { DemoHotspot } from '../app/demo-data'
import { buildResultDisplayModel } from './info-panel/result-adapter'

const props = defineProps<{
  viewLabel: string
  activeLayer: ActiveLayerDisplay
  hourLabel: string
  stageLabel: string
  visibleHotspots: DemoHotspot[]
  selectedLayer?: ActiveLayerDisplay | null
  isSubmitting?: boolean
  workflowError?: string | null
}>()

const emit = defineEmits<{
  runWorkflow: [catalogId: string]
}>()

const displayLayer = computed(() => props.selectedLayer ?? props.activeLayer)
const jobLayer = computed(() => displayLayer.value?.jobLayer)
const resultModel = computed(() => buildResultDisplayModel(jobLayer.value?.resultView ?? null))
const canRunWorkflow = computed(() => !displayLayer.value?.isAdminBoundary)
const isWorkflowRunning = computed(() => jobLayer.value?.status === 'running' || jobLayer.value?.status === 'queued')
const buttonDisabled = computed(() => isWorkflowRunning.value || props.isSubmitting)
const buttonLabel = computed(() => {
  if (props.isSubmitting) return '提交中...'
  if (isWorkflowRunning.value) return '任务进行中'
  return '运行工作流'
})

function handleRunWorkflow() {
  if (!displayLayer.value || !canRunWorkflow.value || buttonDisabled.value) return
  emit('runWorkflow', displayLayer.value.catalogId)
}
</script>

<template>
  <aside class="panel">
    <div class="panel-topline">
      <div class="panel-header">
        <div>
          <h2>分析</h2>
          <p class="panel-subtitle">当前摘要</p>
        </div>
        <span class="readiness">{{ stageLabel }}</span>
      </div>

      <!-- Error display -->
      <div v-if="workflowError" class="workflow-error">
        <span class="error-icon">⚠️</span>
        <span class="error-message">{{ workflowError }}</span>
      </div>

      <div class="action-row">
        <button
          v-if="canRunWorkflow"
          class="run-workflow-btn"
          :disabled="buttonDisabled"
          @click="handleRunWorkflow"
        >
          {{ buttonLabel }}
        </button>
      </div>

      <dl class="meta-list">
        <div>
          <dt>图层</dt>
          <dd>{{ displayLayer.name }}</dd>
        </div>
        <div>
          <dt>时间</dt>
          <dd>{{ hourLabel }}</dd>
        </div>
        <div>
          <dt>视图</dt>
          <dd>{{ viewLabel }}</dd>
        </div>
        <div>
          <dt>来源</dt>
          <dd>{{ displayLayer.sourceLabel }}</dd>
        </div>
      </dl>
    </div>

    <!-- Job layer report section -->
    <div v-if="jobLayer" class="job-report-card">
      <div class="job-report-header">
        <span class="job-report-title">作业生产报告</span>
        <span class="job-status-chip" :class="`job-${jobLayer.status}`">
          {{ jobLayer.status === 'running' ? `运行中 ${jobLayer.progress}%` : jobLayer.status === 'succeeded' ? '已完成' : jobLayer.status === 'failed' ? '失败' : jobLayer.status }}
        </span>
      </div>

      <div v-if="jobLayer.status === 'running'" class="job-progress-row">
        <div class="job-progress-bar">
          <div class="job-progress-fill" :style="{ width: `${jobLayer.progress}%` }"></div>
        </div>
        <span class="job-progress-label">{{ jobLayer.progress }}%</span>
      </div>

      <p class="job-message">{{ jobLayer.message || '作业正在处理中...' }}</p>

      <div v-if="resultModel?.metricRows.length" class="job-metrics">
        <div v-for="m in resultModel.metricRows" :key="m.label" class="job-metric-item">
          <span class="jm-label">{{ m.label }}</span>
          <strong class="jm-value">{{ m.value }}</strong>
        </div>
      </div>

      <div v-if="resultModel" class="job-summary">
        <h3>结果视图</h3>
        <p>{{ resultModel.title }} · {{ resultModel.subtitle }}</p>
      </div>

      <div v-if="resultModel?.metricRows.length" class="job-summary-meta">
        <h3>稳定适配层</h3>
        <dl class="summary-grid">
          <div v-for="row in resultModel.metricRows" :key="row.label" class="summary-item">
            <dt>{{ row.label }}</dt>
            <dd>{{ row.value }}</dd>
          </div>
        </dl>
      </div>

      <a
        v-if="resultModel?.canShowResultLink && resultModel.resultUrl"
        :href="resultModel.resultUrl"
        target="_blank"
        class="job-result-link"
      >
        查看结果文件 →
      </a>
    </div>

    <section class="hero-metric" :style="{ '--accent-color': displayLayer.accentColor }">
      <span>{{ displayLayer.metricLabel }}</span>
      <strong>{{ displayLayer.metricValue }}</strong>
      <p>{{ displayLayer.trendLabel }}</p>
    </section>

    <div class="insight-grid">
      <article class="insight-card">
        <span>更新频率</span>
        <strong>{{ displayLayer.updateLabel }}</strong>
      </article>
      <article class="insight-card">
        <span>可用性</span>
        <strong>{{ displayLayer.availabilityLabel }}</strong>
      </article>
      <article class="insight-card">
        <span>可靠性</span>
        <strong>{{ displayLayer.confidenceLabel }}</strong>
      </article>
      <article class="insight-card">
        <span>观测时间</span>
        <strong>{{ displayLayer.observationTimeLabel }}</strong>
      </article>
    </div>

    <div class="learning-note">
      <h3>摘要</h3>
      <p>{{ displayLayer.summary }}</p>
    </div>

    <details class="protocol-details">
      <summary>接入占位</summary>
      <p>协议模式：{{ displayLayer.dataState === 'real' ? '真实数据' : '演示数据' }}</p>
      <p>状态说明：{{ displayLayer.availabilityDescription }}</p>
      <p>缺失字段：{{ displayLayer.missingFieldsLabel }}</p>
    </details>

    <div class="learning-note">
      <h3>热点区域</h3>
      <p v-if="visibleHotspots.length === 0" class="empty-hotspot">当前时段暂无可用热点，保留协议占位。</p>
      <ul v-else class="hotspot-list">
        <li v-for="hotspot in visibleHotspots" :key="hotspot.id">
          <span>{{ hotspot.name }}</span>
          <strong>{{ hotspot.value }}</strong>
        </li>
      </ul>
    </div>
  </aside>
</template>

<style scoped>
.panel {
  display: grid;
  gap: 0.56rem;
  padding: 0.58rem;
  border-radius: 0.88rem;
  border: 1px solid rgba(148, 163, 184, 0.15);
  background: linear-gradient(180deg, rgba(13, 21, 36, 0.72), rgba(8, 15, 28, 0.6));
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.03),
    0 12px 26px rgba(1, 8, 16, 0.14);
  max-height: min(31rem, calc(100vh - 10rem));
  overflow: auto;
  /* 性能优化：contain 隔离渲染 */
  contain: layout style;
}

.panel-topline {
  display: grid;
  gap: 0.46rem;
  padding: 0.12rem;
}

.action-row {
  display: flex;
  justify-content: flex-start;
}

.workflow-error {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  padding: 0.34rem 0.48rem;
  border-radius: 0.62rem;
  background: rgba(255, 80, 80, 0.12);
  border: 1px solid rgba(255, 80, 80, 0.22);
  color: #ff9999;
  font-size: 0.58rem;
}

.error-icon {
  font-size: 0.72rem;
}

.error-message {
  line-height: 1.3;
}

.run-workflow-btn {
  border: 1px solid rgba(103, 212, 255, 0.24);
  border-radius: 999px;
  background: rgba(29, 78, 216, 0.18);
  color: #d8f3ff;
  font-size: 0.62rem;
  padding: 0.34rem 0.7rem;
  cursor: pointer;
  transition: background-color 0.18s ease, opacity 0.18s ease;
}

.run-workflow-btn:hover:not(:disabled) {
  background: rgba(29, 78, 216, 0.28);
}

.run-workflow-btn:disabled {
  cursor: not-allowed;
  opacity: 0.62;
}

.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 0.55rem;
}

h2,
h3 {
  margin: 0;
  color: #eef7ff;
  font-size: 0.76rem;
}

.panel-subtitle {
  margin: 0.14rem 0 0;
  color: #8195aa;
  font-size: 0.62rem;
}

.readiness {
  padding: 0.18rem 0.4rem;
  border-radius: 999px;
  background: rgba(84, 181, 255, 0.1);
  border: 1px solid rgba(84, 181, 255, 0.14);
  color: #a7dbff;
  font-size: 0.58rem;
}

.meta-list {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0.34rem;
  margin: 0;
}

.meta-list div {
  padding: 0.34rem 0.38rem;
  border: 1px solid rgba(148, 163, 184, 0.08);
  border-radius: 0.7rem;
  background: rgba(8, 18, 33, 0.3);
}

dt {
  margin-bottom: 0.16rem;
  color: #8fa5b9;
  font-size: 0.58rem;
}

dd {
  margin: 0;
  color: #e1ebf5;
  font-size: 0.68rem;
}

/* Job report card */
.job-report-card {
  display: grid;
  gap: 0.32rem;
  padding: 0.5rem 0.54rem;
  border-radius: 0.72rem;
  background: rgba(10, 60, 120, 0.18);
  border: 1px solid rgba(90, 213, 255, 0.18);
}

.job-report-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.4rem;
}

.job-report-title {
  color: #8fe7ff;
  font-size: 0.66rem;
  font-weight: 600;
}

.job-status-chip {
  padding: 0.1rem 0.34rem;
  border-radius: 999px;
  font-size: 0.54rem;
  font-weight: 600;
}

.job-running { color: #5ad5ff; background: rgba(10, 132, 255, 0.14); border: 1px solid rgba(90, 213, 255, 0.22); }
.job-succeeded { color: #9ff8cf; background: rgba(114, 255, 207, 0.1); border: 1px solid rgba(114, 255, 207, 0.2); }
.job-failed { color: #ff8080; background: rgba(255, 80, 80, 0.1); border: 1px solid rgba(255, 80, 80, 0.2); }
.job-queued, .job-cancelled { color: #d7c1ff; background: rgba(187, 137, 255, 0.08); border: 1px solid rgba(187, 137, 255, 0.16); }

.job-progress-row {
  display: flex;
  align-items: center;
  gap: 0.4rem;
}

.job-progress-bar {
  flex: 1;
  height: 0.28rem;
  border-radius: 999px;
  background: rgba(136, 192, 255, 0.12);
  overflow: hidden;
}

.job-progress-fill {
  height: 100%;
  border-radius: inherit;
  background: linear-gradient(90deg, rgba(10, 132, 255, 0.6), #5ad5ff);
  transition: width 0.4s ease;
}

.job-progress-label {
  color: #5ad5ff;
  font-size: 0.54rem;
  min-width: 2rem;
  text-align: right;
}

.job-message {
  margin: 0;
  color: #8ea8c0;
  font-size: 0.6rem;
  line-height: 1.35;
}

.job-metrics {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0.2rem;
}

.job-metric-item {
  display: grid;
  gap: 0.1rem;
  padding: 0.22rem 0.3rem;
  border-radius: 0.5rem;
  background: rgba(4, 12, 23, 0.3);
}

.jm-label {
  color: #7a8fa8;
  font-size: 0.52rem;
}

.jm-value {
  color: #d8e8f5;
  font-size: 0.64rem;
  font-weight: 600;
}

.job-summary,
.job-summary-meta {
  display: grid;
  gap: 0.18rem;
}

.job-summary h3,
.job-summary-meta h3 {
  font-size: 0.64rem;
  color: #b8d4ee;
}

.job-summary p {
  margin: 0;
  color: #8ea8c0;
  font-size: 0.6rem;
  line-height: 1.38;
}

.summary-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0.18rem;
  margin: 0;
}

.summary-item {
  display: grid;
  gap: 0.08rem;
  padding: 0.24rem 0.28rem;
  border-radius: 0.48rem;
  background: rgba(4, 12, 23, 0.26);
}

.summary-item dt {
  color: #7d90a7;
  font-size: 0.5rem;
}

.summary-item dd {
  color: #d8e6f2;
  font-size: 0.6rem;
}

.job-result-link {
  display: inline-flex;
  align-items: center;
  gap: 0.2rem;
  color: #5ad5ff;
  font-size: 0.6rem;
  text-decoration: none;
  padding: 0.18rem 0.3rem;
  border-radius: 0.5rem;
  border: 1px solid rgba(90, 213, 255, 0.18);
  background: rgba(10, 132, 255, 0.08);
  transition: background 0.16s ease, border-color 0.16s ease;
  align-self: flex-start;
}

.job-result-link:hover {
  background: rgba(10, 132, 255, 0.16);
  border-color: rgba(90, 213, 255, 0.3);
}

.hero-metric {
  display: grid;
  gap: 0.24rem;
  padding: 0.58rem;
  border-radius: 0.78rem;
  background:
    linear-gradient(135deg, rgba(90, 162, 255, 0.12), rgba(8, 18, 33, 0.58)),
    rgba(8, 18, 33, 0.52);
  border: 1px solid rgba(90, 162, 255, 0.22);
}

.hero-metric span {
  color: #95a8bb;
  font-size: 0.58rem;
}

.hero-metric strong {
  color: #f4fbff;
  font-size: 1.1rem;
  line-height: 1.1;
}

.hero-metric p {
  margin: 0;
  color: #d7e8f8;
  font-size: 0.64rem;
  line-height: 1.3;
}

.insight-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0.3rem;
}

.insight-card {
  display: grid;
  gap: 0.18rem;
  padding: 0.42rem 0.46rem;
  border-radius: 0.72rem;
  background: rgba(8, 18, 33, 0.34);
  border: 1px solid rgba(148, 163, 184, 0.08);
}

.insight-card span {
  color: #8aa0b5;
  font-size: 0.56rem;
}

.insight-card strong {
  color: #e7f2fc;
  font-size: 0.64rem;
}

.learning-note {
  display: grid;
  gap: 0.22rem;
  padding: 0.12rem;
}

.protocol-details {
  display: grid;
  gap: 0.22rem;
  padding: 0.12rem;
}

.protocol-details summary {
  cursor: pointer;
  color: #eef7ff;
  font-size: 0.7rem;
  list-style: none;
}

.protocol-details summary::-webkit-details-marker {
  display: none;
}

.protocol-details summary::after {
  content: '展开';
  float: right;
  color: #88a8c7;
  font-size: 0.58rem;
}

.protocol-details[open] summary::after {
  content: '收起';
}

.learning-note p {
  margin: 0;
  color: #91a5b9;
  line-height: 1.34;
  font-size: 0.62rem;
}

.hotspot-list {
  display: grid;
  gap: 0.26rem;
  margin: 0;
  padding: 0;
  list-style: none;
}

.hotspot-list li {
  display: flex;
  justify-content: space-between;
  gap: 0.4rem;
  padding: 0.38rem 0.44rem;
  border-radius: 0.68rem;
  background: rgba(8, 18, 33, 0.28);
  border: 1px solid rgba(148, 163, 184, 0.08);
  color: #d8e6f2;
  font-size: 0.6rem;
}

.hotspot-list strong {
  color: #f6fbff;
}

.empty-hotspot {
  margin: 0;
  color: #9aabc0;
  font-size: 0.62rem;
  line-height: 1.34;
}
</style>
