/** * InfoPanel 元数据 Tab：总览 / 导入图层 / 任务调度 / 报告 / 选中图层 / 主指标 / 洞察 / 元数据 /
历史对比。 * * 从 InfoPanel.vue 模板抽取（原 1287-1663 行与 2338-2412 行）。纯展示组件， *
全部状态由父组件通过 props 传入；交互通过 emit 回传父组件。 */
<script setup lang="ts">
import { computed } from 'vue'
import type { ActiveLayerDisplay, JobLayerItem } from '../../stores/layers/types'
import type { ResultDisplayModel } from './result-adapter'
import { ANALYSIS_COPY, DATA_COPY, LAYERS_COPY } from '../../ui-copy'
import { openDataWorkspace } from '../../data-manager/core/workspace-store'
import { useOverlaySymbologyStore } from '../../stores/overlay-symbology'
import AppButton from '../ui/AppButton.vue'
import { filterDisplayableNodeProgress } from '../../stores/layers/workflow-progress'
import {
  formatDownloadProgressDetail,
  hasDownloadProgressDetail,
} from '../../utils/workflow-download-display'
import { nodeMessageRedundantWithDetail } from '../../utils/workflow-node-progress-display'

const props = defineProps<{
  displayLayer: ActiveLayerDisplay
  isRealtimeWeatherLayer: boolean
  jobLayer: JobLayerItem | undefined
  resultModel: ResultDisplayModel | null
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
  /** 变量角色代号（SM / VOD / OMEGA），非反演产品时为空串 */
  productRole: string
  workflowError: string | null
  interactionMode: string
  importActionHint: string
}>()

// 来源标签缓存（/overlay-bounds 的 meta.source_label）
const overlaySymbology = useOverlaySymbologyStore()

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

const displayNodeProgress = computed(() =>
  filterDisplayableNodeProgress(props.jobLayer?.nodeProgress),
)

/** 工作流运行/排队/失败时：元数据 Tab 只保留任务进度，隐藏图层目录冗余元数据。 */
const simplifyMetaForActiveJob = computed(() => {
  if (!props.jobLayer) return false
  const status = props.jobLayer.status
  return status === 'running' || status === 'queued' || status === 'failed'
})

/** 变量角色代号 → 展示名（报告第七节：变量行要显示 SM / VOD / ω） */
const PRODUCT_ROLE_NAMES: Record<string, string> = {
  SM: '土壤水分',
  VOD: '植被光学厚度',
  OMEGA: '等效散射 ω',
}

/**
 * 「变量」行文案：只在识别到角色码（SM / VOD / OMEGA）时才非空，
 * 普通导入图层不占位、不显示「未提供」噪音。
 */
const productRoleText = computed(() => {
  const role = String(props.productRole ?? '')
    .trim()
    .toUpperCase()
  if (!role) return ''
  const name = PRODUCT_ROLE_NAMES[role]
  return name ? `${name}（${role}）` : role
})

/**
 * `20251201_20260201` → 跨度天数（含首尾）；单日键返回 1；解析失败返回 null。
 * 用来判断「这一个时间片到底是单日，还是一段合成块」。
 */
function blockSpanDays(raw: string): number | null {
  const key = raw.trim()
  const block = /^(\d{4})(\d{2})(\d{2})_(\d{4})(\d{2})(\d{2})$/.exec(key)
  const single = /^(\d{4})(\d{2})(\d{2})$/.exec(key)
  const toMs = (y: string, m: string, d: string) => Date.UTC(Number(y), Number(m) - 1, Number(d))
  if (block) {
    const [, y1, m1, d1, y2, m2, d2] = block
    const days = (toMs(y2, m2, d2) - toMs(y1, m1, d1)) / 86_400_000
    return Number.isFinite(days) ? Math.round(days) + 1 : null
  }
  if (single) return 1
  return null
}

/**
 * 原生步长的通俗说法。
 *
 * 只描述「多久一帧」，不断言是否为合成产品
 * （`1M` 也可能是月度快照，说成「月合成」会误导）。
 * ⚠ 若该图层只有**一个时间片且跨多天**（如 SMAP 的 61 天块），
 * `native_step` 写 `1d` 也不代表每天一帧——此时说「每日 1 帧」会误导，
 * 应直接说「单幅时间块」（外部测试报告 优先3）。
 */
const nativeStepText = computed(() => {
  const dl = props.displayLayer
  const timeCount = Number(dl.importedRasterTimeCount ?? 0)
  const spanDays = blockSpanDays(String(dl.importedRasterEffectiveTime ?? ''))
  if (timeCount === 1 && spanDays !== null && spanDays > 1) {
    return `单幅时间块（共 ${spanDays} 天，非逐日）`
  }
  const raw = String(dl.importedRasterNativeStep ?? '').trim()
  if (!raw) return ''
  const key = raw.toLowerCase()
  const hour = /^(\d+)h$/.exec(key)
  if (hour) return `每 ${hour[1]} 小时 1 帧`
  const day = /^(\d+)d$/.exec(key)
  if (day) return Number(day[1]) === 1 ? '每日 1 帧' : `每 ${day[1]} 天 1 帧`
  if (/^(\d+)m$/.test(key)) return '每月 1 帧'
  if (/^(\d+)yr$/.test(key)) return '每年 1 帧'
  return raw
})

/** 有效时刻：`20251201_20251231` 这类区间块展开成可读区间 */
const effectiveTimeText = computed(() => {
  const raw = String(props.displayLayer.importedRasterEffectiveTime ?? '').trim()
  if (!raw) return ''
  const block = /^(\d{4})(\d{2})(\d{2})_(\d{4})(\d{2})(\d{2})$/.exec(raw)
  if (!block) return raw
  const [, y1, m1, d1, y2, m2, d2] = block
  return `${y1}-${m1}-${d1} ~ ${y2}-${m2}-${d2}`
})

/**
 * 数据源：优先用后端来源标签（SMAP / 风云卫星）。
 *
 * 本地导入类图层的 displayLayer.sourceLabel 取的是文件名
 * （`source_20251201_20260201.tif`），对用户没有意义；/overlay-bounds 的
 * meta.source_label 才是人能看的来源，所以前者优先。
 */
const sourceText = computed(() => {
  const catalogId = String(props.displayLayer.catalogId || '')
  const fromMeta = overlaySymbology.getSourceLabel(catalogId)
  return fromMeta || props.displayLayer.sourceLabel || '—'
})

const layerMetadata = computed(() => {
  const dl = props.displayLayer
  const meta: { label: string; value: string }[] = [
    { label: '数据源', value: sourceText.value },
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
    :class="{ 'analysis-section--overview-compact': simplifyMetaForActiveJob }"
  >
    <div class="section-kicker">{{ ANALYSIS_COPY.overviewKicker }}</div>
    <h3>
      {{
        simplifyMetaForActiveJob
          ? workflowMeta.name || displayLayer.name
          : showCompactHero
            ? ANALYSIS_COPY.overviewTitleCompact
            : ANALYSIS_COPY.overviewTitleFull
      }}
    </h3>
    <p v-if="simplifyMetaForActiveJob">
      {{ workflowStageCopy || latestEventMessage || analysisSummary }}
    </p>
    <p v-else>{{ analysisSummary }}</p>
    <div class="overview-quick-actions">
      <AppButton
        v-if="!simplifyMetaForActiveJob && isRealtimeWeatherLayer && interactionMode !== 'select'"
        size="xs"
        variant="secondary"
        @click="enterInspectTools"
      >
        {{ ANALYSIS_COPY.toolsQuickInspect }}
      </AppButton>
      <AppButton
        v-if="!simplifyMetaForActiveJob && canRunWorkflow"
        size="xs"
        variant="secondary"
        @click="emit('setActiveTab', 'tools')"
      >
        {{ ANALYSIS_COPY.toolsQuickBuffer }}
      </AppButton>
      <AppButton
        v-if="!simplifyMetaForActiveJob && hasLayerStyleSection"
        size="xs"
        variant="secondary"
        @click="emit('setActiveTab', 'style')"
      >
        符号样式
      </AppButton>
    </div>
  </section>

  <!-- ── 导入图层 ─────────────────────────────────────────────────── -->
  <section
    v-if="!simplifyMetaForActiveJob && (displayLayer.isImported || displayLayer.isImportedRaster)"
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
        <dd>{{ displayLayer.importedRasterSourceCrs || '未提供' }}</dd>
      </div>
      <div v-if="displayLayer.isImportedRaster && nativeStepText">
        <dt>{{ ANALYSIS_COPY.metaNativeStep }}</dt>
        <dd>{{ nativeStepText }}</dd>
      </div>
      <div v-if="displayLayer.isImportedRaster && effectiveTimeText">
        <dt>{{ ANALYSIS_COPY.metaEffectiveTime }}</dt>
        <dd>{{ effectiveTimeText }}</dd>
      </div>
      <div v-if="displayLayer.isImportedRaster && (displayLayer.importedRasterTimeCount ?? 0) > 0">
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
          {{ formatBounds(displayLayer.importedBounds ?? displayLayer.importedRasterBounds) }}
        </dd>
      </div>
      <div v-if="displayLayer.isImportedRaster && productRoleText">
        <dt>{{ ANALYSIS_COPY.metaVariable }}</dt>
        <dd>{{ productRoleText }}</dd>
      </div>
      <div>
        <dt>{{ ANALYSIS_COPY.metaSource }}</dt>
        <dd>{{ displayLayer.sourceLabel }}</dd>
      </div>
    </dl>
    <div v-if="displayLayer.isImported" class="imported-export-row">
      <AppButton
        size="xs"
        variant="ghost"
        @click="
          openDataWorkspace({
            tab: 'attributes',
            layerInstanceId: displayLayer.instanceId,
          })
        "
      >
        {{ DATA_COPY.openAttrTable }}
      </AppButton>
      <AppButton
        size="xs"
        variant="ghost"
        @click="
          openDataWorkspace({
            tab: 'details',
            layerInstanceId: displayLayer.instanceId,
          })
        "
      >
        {{ DATA_COPY.openDetails }}
      </AppButton>
      <AppButton size="xs" variant="ghost" @click="emit('exportGeoJson')">
        {{ LAYERS_COPY.exportGeoJson }}
      </AppButton>
      <AppButton size="xs" variant="ghost" @click="emit('exportCsv')">
        {{ LAYERS_COPY.exportCsv }}
      </AppButton>
      <AppButton size="xs" variant="ghost" @click="emit('exportShp')">
        {{ LAYERS_COPY.exportShp }}
      </AppButton>
      <AppButton size="xs" variant="ghost" @click="emit('openExportPanel')">
        {{ LAYERS_COPY.openExportPanel }}
      </AppButton>
    </div>
    <div v-else-if="displayLayer.isImportedRaster" class="imported-export-row">
      <AppButton
        size="xs"
        variant="ghost"
        @click="
          openDataWorkspace({
            tab: 'details',
            layerInstanceId: displayLayer.instanceId,
          })
        "
      >
        {{ DATA_COPY.openDetails }}
      </AppButton>
      <AppButton size="xs" variant="ghost" @click="emit('exportRaster', 'tif')">
        {{ LAYERS_COPY.exportTif }}
      </AppButton>
      <AppButton size="xs" variant="ghost" @click="emit('exportRaster', 'nc')">
        {{ LAYERS_COPY.exportNc }}
      </AppButton>
      <AppButton size="xs" variant="ghost" @click="emit('exportRaster', 'mat')">
        {{ LAYERS_COPY.exportMat }}
      </AppButton>
      <AppButton size="xs" variant="ghost" @click="emit('exportRaster', 'png')">
        {{ LAYERS_COPY.exportPng }}
      </AppButton>
      <AppButton size="xs" variant="ghost" @click="emit('openExportPanel')">
        {{ LAYERS_COPY.openExportPanel }}
      </AppButton>
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
      <p v-if="workflowError" class="job-message job-message--error">{{ workflowError }}</p>
      <div v-if="displayNodeProgress.length" class="job-node-progress-section">
        <div v-for="np in displayNodeProgress" :key="np.nodeId" class="job-node-progress-item">
          <div class="job-node-progress-header">
            <span>{{ np.nodeLabel }}</span>
            <span v-if="np.terminalHint === 'skipped'" class="job-node-skipped">已跳过</span>
            <span>{{ np.progress }}%</span>
          </div>
          <div class="job-node-progress-bar">
            <div class="job-node-progress-fill" :style="{ width: `${np.progress}%` }"></div>
          </div>
          <p
            v-if="np.message && !nodeMessageRedundantWithDetail(np)"
            class="job-node-progress-message"
          >
            {{ np.message }}
          </p>
          <p
            v-if="np.detail && hasDownloadProgressDetail(np.detail)"
            class="job-node-progress-detail"
          >
            {{ formatDownloadProgressDetail(np.detail) }}
          </p>
          <p
            v-else-if="
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
      <ul v-if="jobEventNotes.length && !simplifyMetaForActiveJob" class="job-diagnostic-list">
        <li
          v-for="(note, idx) in jobEventNotes"
          :key="`job-note-${idx}`"
          class="job-diagnostic-item"
        >
          {{ note }}
        </li>
      </ul>
    </div>

    <div v-if="!simplifyMetaForActiveJob" class="job-steps">
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
    v-if="!simplifyMetaForActiveJob && jobLayer"
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

    <div v-if="displayNodeProgress.length" class="report-block">
      <h4>进度时间线</h4>
      <ul class="report-node-list">
        <li v-for="np in displayNodeProgress" :key="np.nodeId">
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
        <AppButton size="xs" variant="secondary" @click="emit('exportRaster', 'png')">
          PNG
        </AppButton>
        <AppButton size="xs" variant="secondary" @click="emit('exportRaster', 'tif')">
          GeoTIFF
        </AppButton>
      </div>
    </div>
  </section>

  <!-- ── 选中图层 ─────────────────────────────────────────────────── -->
  <section
    v-if="!simplifyMetaForActiveJob"
    v-show="true"
    :id="`layer-${displayLayer.instanceId || 'default'}`"
    class="analysis-section analysis-section--layer"
  >
    <div class="section-kicker">{{ ANALYSIS_COPY.selectedLayerKicker }}</div>
    <h3>{{ ANALYSIS_COPY.selectedLayerTitle }}</h3>
    <p>
      {{ displayLayer.name }}
      <span v-if="displayLayer.availabilityLabel"> · {{ displayLayer.availabilityLabel }}</span>
    </p>
    <p class="tools-empty-hint" style="margin-top: 0.35rem">透明度与符号请到「样式」Tab 调整。</p>
  </section>

  <!-- meta：主指标与洞察（去冗后只在此 Tab） -->
  <section
    v-if="displayLayer.instanceId && !showCompactHero && !simplifyMetaForActiveJob"
    v-show="true"
    class="hero-metric"
    :style="{ '--accent-color': displayLayer.accentColor }"
  >
    <span>{{ displayLayer.metricLabel }}</span>
    <strong>{{ displayLayer.metricValue }}</strong>
    <p>{{ displayLayer.trendLabel }}</p>
  </section>

  <div
    v-if="displayLayer.instanceId && !showCompactHero && !simplifyMetaForActiveJob"
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
    v-if="layerMetadata.length && displayLayer.instanceId && !simplifyMetaForActiveJob"
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
    v-if="displayLayer.trendLabel && displayLayer.instanceId && !simplifyMetaForActiveJob"
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
