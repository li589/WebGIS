/**
 * InfoPanel 元数据 Tab：总览 / 导入图层 / 任务调度 / 报告 / 选中图层 / 主指标 / 洞察 / 元数据 / 历史对比。
 *
 * 从 InfoPanel.vue 模板抽取（原 1287-1663 行与 2338-2412 行）。纯展示组件，
 * 全部状态由父组件通过 props 传入；交互通过 emit 回传父组件。
 */
<script setup lang="ts">
import { computed } from 'vue'
import type { ActiveLayerDisplay } from '../../stores/layers/types'
import { ANALYSIS_COPY, DATA_COPY, LAYERS_COPY } from '../../ui-copy'
import { openDataWorkspace } from '../../data-manager/core/workspace-store'

const props = defineProps<{
  displayLayer: ActiveLayerDisplay
  isRealtimeWeatherLayer: boolean
  jobLayer: any
  resultModel: any
  analysisSummary: string
  showCompactHero: boolean
  workflowStage: string
  workflowStageCopy: string
  workflowMeta: { name: string; engine: string; engineLabel: string; engineIcon: string }
  workflowProgress: number
  latestEventMessage: string
  canRunWorkflow: boolean
  isWorkflowRunning: boolean
  runBlockedReason: string | null
  showWorkflowStageRow: boolean
  weatherTopLines: string[]
  staticTopHint: string
  jobEventNotes: string[]
  jobReportSummary: string
  hasLayerStyleSection: boolean
  workflowError: string | null
  interactionMode: string
  importActionHint: string
}>()

const emit = defineEmits<{
  setActiveTab: [tab: string]
  enterSelectMode: []
  exportGeoJson: []
  exportCsv: []
  exportShp: []
  openExportPanel: []
  exportRaster: [format: string]
  openDataWorkspace: [payload: { tab: string; layerInstanceId: string }]
}>()

const layerMetadata = computed(() => {
  const dl = props.displayLayer
  const meta: { label: string; value: string }[] = [
    { label: '数据源', value: dl.sourceLabel || '—' },
    { label: '更新频率', value: dl.updateLabel || '—' },
    { label: '观测时间', value: dl.observationTimeLabel || '—' },
    { label: '可用性', value: dl.availabilityLabel || '—' },
  ]
  if (dl.jobLayer) {
    meta.push({ label: '作业状态', value: dl.jobLayer.status || '—' })
    if (dl.jobLayer.diagnosticNotes?.length) {
      meta.push({ label: '诊断', value: dl.jobLayer.diagnosticNotes.slice(0, 2).join('；') })
    }
  }
  return meta
})

const trendDirection = computed<'up' | 'down' | 'flat'>(() => {
  const text = props.displayLayer?.trendLabel ?? ''
  if (/上升|增长|偏高|高于|增|升|回暖/.test(text)) return 'up'
  if (/下降|降低|偏低|低于|减|降|转凉/.test(text)) return 'down'
  return 'flat'
})

const trendArrowSymbol = computed(() => {
  if (trendDirection.value === 'up') return '↗'
  if (trendDirection.value === 'down') return '↘'
  return '→'
})

function formatBounds(bounds?: [number, number, number, number] | null): string {
  if (!bounds || bounds.length !== 4) return '—'
  return `${bounds[0].toFixed(3)}, ${bounds[1].toFixed(3)} → ${bounds[2].toFixed(3)}, ${bounds[3].toFixed(3)}`
}

function enterInspectTools() {
  emit('setActiveTab', 'tools')
  emit('enterSelectMode')
}
</script>

<template>
  <!-- ── 总览 ─────────────────────────────────────────────────────── -->
  <section
    v-show="true"
    id="global-overview"
    class="analysis-section analysis-section--overview"
  >
    <div class="section-kicker">{{ ANALYSIS_COPY.overviewKicker }}</div>
    <h3>
      {{
        showCompactHero
          ? ANALYSIS_COPY.overviewTitleCompact
          : ANALYSIS_COPY.overviewTitleFull
      }}
    </h3>
    <p>{{ analysisSummary }}</p>
    <div class="overview-quick-actions">
      <button
        v-if="isRealtimeWeatherLayer && interactionMode !== 'select'"
        type="button"
        class="weather-mini-btn"
        @click="enterInspectTools"
      >
        {{ ANALYSIS_COPY.toolsQuickInspect }}
      </button>
      <button
        v-if="canRunWorkflow"
        type="button"
        class="weather-mini-btn"
        @click="emit('setActiveTab', 'tools')"
      >
        {{ ANALYSIS_COPY.toolsQuickBuffer }}
      </button>
      <button
        v-if="hasLayerStyleSection"
        type="button"
        class="weather-mini-btn"
        @click="emit('setActiveTab', 'style')"
      >
        符号样式
      </button>
    </div>
  </section>

  <!-- ── 导入图层 ─────────────────────────────────────────────────── -->
  <section
    v-if="displayLayer.isImported || displayLayer.isImportedRaster"
    v-show="true"
    id="imported-layer"
    class="analysis-section analysis-section--imported"
  >
    <div class="section-kicker">{{ ANALYSIS_COPY.importedSectionKicker }}</div>
    <h3>{{ ANALYSIS_COPY.importedSectionTitle }}</h3>
    <dl class="meta-list imported-meta">
      <div v-if="displayLayer.isImported">
        <dt>{{ ANALYSIS_COPY.metaGeometry }}</dt>
        <dd>{{ displayLayer.importedGeometryType ?? '—' }}</dd>
      </div>
      <div v-if="displayLayer.isImported">
        <dt>{{ ANALYSIS_COPY.metaFeatures }}</dt>
        <dd>{{ displayLayer.importedFeatureCount ?? 0 }}</dd>
      </div>
      <div v-if="displayLayer.isImportedRaster">
        <dt>{{ ANALYSIS_COPY.metaMode }}</dt>
        <dd>{{ ANALYSIS_COPY.importedRasterType }}</dd>
      </div>
      <div v-if="displayLayer.isImportedRaster">
        <dt>{{ ANALYSIS_COPY.metaCrs }}</dt>
        <dd>{{ displayLayer.importedRasterSourceCrs ?? '—' }}</dd>
      </div>
      <div v-if="displayLayer.isImportedRaster && displayLayer.importedRasterNativeStep">
        <dt>{{ ANALYSIS_COPY.metaNativeStep }}</dt>
        <dd>{{ displayLayer.importedRasterNativeStep }}</dd>
      </div>
      <div v-if="displayLayer.isImportedRaster && displayLayer.importedRasterEffectiveTime">
        <dt>{{ ANALYSIS_COPY.metaEffectiveTime }}</dt>
        <dd>{{ displayLayer.importedRasterEffectiveTime }}</dd>
      </div>
      <div
        v-if="
          displayLayer.isImportedRaster && (displayLayer.importedRasterTimeCount ?? 0) > 0
        "
      >
        <dt>{{ ANALYSIS_COPY.metaTimeSlices }}</dt>
        <dd>{{ displayLayer.importedRasterTimeCount }}</dd>
      </div>
      <div v-if="displayLayer.isImportedRaster">
        <dt>叠加层 ID</dt>
        <dd class="mono">{{ displayLayer.catalogId }}</dd>
      </div>
      <div v-if="displayLayer.importedFileName">
        <dt>{{ ANALYSIS_COPY.metaFile }}</dt>
        <dd>{{ displayLayer.importedFileName }}</dd>
      </div>
      <div>
        <dt>{{ ANALYSIS_COPY.metaBounds }}</dt>
        <dd>
          {{
            formatBounds(displayLayer.importedBounds ?? displayLayer.importedRasterBounds)
          }}
        </dd>
      </div>
      <div>
        <dt>{{ ANALYSIS_COPY.metaSource }}</dt>
        <dd>{{ displayLayer.sourceLabel }}</dd>
      </div>
    </dl>
    <div v-if="displayLayer.isImported" class="imported-export-row">
      <button
        class="imported-export-btn"
        type="button"
        @click="
          openDataWorkspace({
            tab: 'attributes',
            layerInstanceId: displayLayer.instanceId,
          })
        "
      >
        {{ DATA_COPY.openAttrTable }}
      </button>
      <button
        class="imported-export-btn"
        type="button"
        @click="
          openDataWorkspace({
            tab: 'details',
            layerInstanceId: displayLayer.instanceId,
          })
        "
      >
        {{ DATA_COPY.openDetails }}
      </button>
      <button class="imported-export-btn" type="button" @click="emit('exportGeoJson')">
        {{ LAYERS_COPY.exportGeoJson }}
      </button>
      <button class="imported-export-btn" type="button" @click="emit('exportCsv')">
        {{ LAYERS_COPY.exportCsv }}
      </button>
      <button class="imported-export-btn" type="button" @click="emit('exportShp')">
        {{ LAYERS_COPY.exportShp }}
      </button>
      <button class="imported-export-btn" type="button" @click="emit('openExportPanel')">
        {{ LAYERS_COPY.openExportPanel }}
      </button>
    </div>
    <div v-else-if="displayLayer.isImportedRaster" class="imported-export-row">
      <button
        class="imported-export-btn"
        type="button"
        @click="
          openDataWorkspace({
            tab: 'details',
            layerInstanceId: displayLayer.instanceId,
          })
        "
      >
        {{ DATA_COPY.openDetails }}
      </button>
      <button
        class="imported-export-btn"
        type="button"
        @click="emit('exportRaster', 'tif')"
      >
        {{ LAYERS_COPY.exportTif }}
      </button>
      <button class="imported-export-btn" type="button" @click="emit('exportRaster', 'nc')">
        {{ LAYERS_COPY.exportNc }}
      </button>
      <button
        class="imported-export-btn"
        type="button"
        @click="emit('exportRaster', 'mat')"
      >
        {{ LAYERS_COPY.exportMat }}
      </button>
      <button
        class="imported-export-btn"
        type="button"
        @click="emit('exportRaster', 'png')"
      >
        {{ LAYERS_COPY.exportPng }}
      </button>
      <button class="imported-export-btn" type="button" @click="emit('openExportPanel')">
        {{ LAYERS_COPY.openExportPanel }}
      </button>
    </div>
    <p
      v-if="importActionHint"
      class="imported-action-hint"
      :class="{ error: importActionHint.includes('失败') }"
    >
      {{ importActionHint }}
    </p>
  </section>

  <!-- ── 任务调度 ─────────────────────────────────────────────────── -->
  <section
    v-if="jobLayer"
    v-show="true"
    id="scheduler-status"
    class="job-report-card job-report-card--summary"
  >
    <div class="job-report-header">
      <div>
        <div class="section-kicker">任务调度</div>
        <span class="job-report-title">任务总览</span>
      </div>
      <span class="job-status-chip" :class="`job-${jobLayer.status}`">
        {{
          jobLayer.status === 'running'
            ? `运行中 ${jobLayer.progress}%`
            : jobLayer.status === 'succeeded'
              ? '已完成'
              : jobLayer.status === 'failed'
                ? '失败'
                : jobLayer.status
        }}
      </span>
    </div>

    <div class="job-progress-shell">
      <div v-if="jobLayer.status === 'running'" class="job-progress-row">
        <div class="job-progress-bar">
          <div class="job-progress-fill" :style="{ width: `${jobLayer.progress}%` }"></div>
        </div>
        <span class="job-progress-label">{{ jobLayer.progress }}%</span>
      </div>
      <p class="job-message">{{ jobLayer.message || '作业正在处理中...' }}</p>
      <div v-if="jobLayer.nodeProgress?.length" class="job-node-progress-section">
        <div
          v-for="np in jobLayer.nodeProgress"
          :key="np.nodeId"
          class="job-node-progress-item"
        >
          <div class="job-node-progress-header">
            <span>{{ np.nodeLabel }}</span>
            <span>{{ np.progress }}%</span>
          </div>
          <div class="job-node-progress-bar">
            <div class="job-node-progress-fill" :style="{ width: `${np.progress}%` }"></div>
          </div>
          <p v-if="np.message" class="job-node-progress-message">{{ np.message }}</p>
          <p
            v-if="
              np.detail &&
              (np.detail.chunksTotal ||
                np.detail.pixelsTotal ||
                np.detail.blocksTotal ||
                np.detail.dateStart)
            "
            class="job-node-progress-detail"
          >
            <template v-if="np.detail.blocksTotal">
              块 {{ np.detail.blocksDone ?? 0 }}/{{ np.detail.blocksTotal }}
              <template v-if="np.detail.dateStart && np.detail.dateEnd">
                · {{ np.detail.dateStart }}–{{ np.detail.dateEnd }}
              </template>
            </template>
            <template v-else-if="np.detail.chunksTotal">
              数据块 {{ np.detail.chunksDone ?? 0 }}/{{ np.detail.chunksTotal }}
            </template>
            <template v-if="np.detail.pixelsTotal">
              · 像素 {{ np.detail.pixelsDone ?? 0 }}/{{ np.detail.pixelsTotal }}
            </template>
            <template v-if="np.detail.phase"> · {{ np.detail.phase }}</template>
          </p>
        </div>
      </div>
      <ul v-if="jobEventNotes.length" class="job-diagnostic-list">
        <li
          v-for="(note, idx) in jobEventNotes"
          :key="`job-note-${idx}`"
          class="job-diagnostic-item"
        >
          {{ note }}
        </li>
      </ul>
    </div>

    <div class="job-steps">
      <div class="job-step">1. 提交任务</div>
      <div
        class="job-step"
        :class="{ active: workflowStage === 'queued' || workflowStage === 'running' }"
      >
        2. 等待运行结果
      </div>
      <div class="job-step" :class="{ active: !!resultModel }">3. 读取视图</div>
    </div>
  </section>

  <!-- ── 报告 ─────────────────────────────────────────────────────── -->
  <section
    v-if="jobLayer"
    v-show="true"
    id="report-section"
    class="analysis-section analysis-section--report"
  >
    <div class="section-kicker">报告</div>
    <div class="report-section-head">
      <div>
        <h3>工作流报告</h3>
        <p>
          {{
            jobLayer.status === 'running' || jobLayer.status === 'queued'
              ? '运行中：下方为实时进度与已产出摘要。'
              : '这里展示该图层当前任务的摘要与结果说明。'
          }}
        </p>
      </div>
      <a
        v-if="jobLayer.resultUrl"
        class="job-result-link"
        :href="jobLayer.resultUrl"
        target="_blank"
        rel="noreferrer"
      >
        打开结果
      </a>
    </div>
    <p v-if="jobReportSummary" class="job-report-copy">{{ jobReportSummary }}</p>
    <p v-else class="job-report-copy">{{ jobLayer.message || '暂无摘要' }}</p>

    <div v-if="jobLayer.nodeProgress?.length" class="report-block">
      <h4>进度时间线</h4>
      <ul class="report-node-list">
        <li v-for="np in jobLayer.nodeProgress" :key="np.nodeId">
          <strong>{{ np.nodeLabel || np.nodeId }}</strong>
          <span>{{ np.stage }} · {{ np.progress }}%</span>
          <span v-if="np.message" class="report-node-msg">{{ np.message }}</span>
        </li>
      </ul>
    </div>

    <div
      v-if="jobLayer.eventMessages?.length || jobLayer.diagnosticNotes?.length"
      class="report-block"
    >
      <h4>事件 / 诊断</h4>
      <ul class="report-node-list">
        <li
          v-for="(note, idx) in (jobLayer.eventMessages?.length
            ? jobLayer.eventMessages
            : jobLayer.diagnosticNotes
          )?.slice(0, 12)"
          :key="`note-${idx}`"
        >
          {{ note }}
        </li>
      </ul>
    </div>

    <div v-if="displayLayer?.isImportedRaster" class="report-block">
      <h4>导出</h4>
      <div class="weather-layer-btn-row" style="gap: 0.4rem">
        <button type="button" class="weather-mini-btn" @click="emit('exportRaster', 'png')">
          PNG
        </button>
        <button type="button" class="weather-mini-btn" @click="emit('exportRaster', 'tif')">
          GeoTIFF
        </button>
      </div>
    </div>
  </section>

  <!-- ── 选中图层 ─────────────────────────────────────────────────── -->
  <section
    v-show="true"
    :id="`layer-${displayLayer.instanceId || 'default'}`"
    class="analysis-section analysis-section--layer"
  >
    <div class="section-kicker">{{ ANALYSIS_COPY.selectedLayerKicker }}</div>
    <h3>{{ ANALYSIS_COPY.selectedLayerTitle }}</h3>
    <p>
      {{ displayLayer.name }}
      <span v-if="displayLayer.availabilityLabel">
        · {{ displayLayer.availabilityLabel }}</span
      >
    </p>
    <p class="tools-empty-hint" style="margin-top: 0.35rem">
      透明度与符号请到「样式」Tab 调整。
    </p>
  </section>

  <!-- meta：主指标与洞察（去冗后只在此 Tab） -->
  <section
    v-if="displayLayer.instanceId && !showCompactHero"
    v-show="true"
    class="hero-metric"
    :style="{ '--accent-color': displayLayer.accentColor }"
  >
    <span>{{ displayLayer.metricLabel }}</span>
    <strong>{{ displayLayer.metricValue }}</strong>
    <p>{{ displayLayer.trendLabel }}</p>
  </section>

  <div
    v-if="displayLayer.instanceId && !showCompactHero"
    v-show="true"
    class="insight-grid"
  >
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

  <section
    v-if="layerMetadata.length && displayLayer.instanceId"
    v-show="true"
    class="info-card meta-card"
  >
    <div class="info-card-head">
      <span class="info-kicker">元数据</span>
      <span class="info-card-tag" :class="{ real: displayLayer.dataState === 'real' }">
        {{ displayLayer.dataState === 'real' ? '真实' : '目录' }}
      </span>
    </div>
    <dl class="meta-grid">
      <div v-for="row in layerMetadata" :key="row.label" class="meta-grid-row">
        <dt>{{ row.label }}</dt>
        <dd>{{ row.value }}</dd>
      </div>
    </dl>
  </section>

  <section
    v-if="displayLayer.trendLabel && displayLayer.instanceId"
    v-show="true"
    class="info-card trend-card"
    :style="{ '--accent-color': displayLayer.accentColor }"
  >
    <div class="info-card-head">
      <span class="info-kicker">历史对比</span>
      <span class="info-card-tag trend">{{ displayLayer.metricLabel }}</span>
    </div>
    <div class="trend-body">
      <div class="trend-current">
        <span class="trend-current-label">当前</span>
        <strong class="trend-current-value">{{ displayLayer.metricValue }}</strong>
      </div>
      <div class="trend-indicator">
        <span class="trend-arrow" :class="trendDirection">{{ trendArrowSymbol }}</span>
        <span class="trend-text">{{ displayLayer.trendLabel }}</span>
      </div>
    </div>
  </section>
</template>

<style scoped src="./InfoPanel.styles.css"></style>
