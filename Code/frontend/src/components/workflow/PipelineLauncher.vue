<script setup lang="ts">
/**
 * PipelineLauncher.vue
 *
 * 端到端流水线启动器对话框。
 * 从工作流定义 store 获取所有系统工作流，过滤 _meta.tags 包含 "pipeline" 的种子，
 * 以卡片形式展示。用户可选择流水线、配置日期参数后一键启动。
 *
 * 优化特性：
 * - 日期范围预设快捷按钮（今天、近7天、近30天、本月、上月）
 * - 流水线搜索过滤
 * - 启动状态反馈（成功/失败提示）
 * - 高级参数类型提示
 */
import { computed, ref, watch } from 'vue'
import { useWorkflowDefinitionsStore } from '../../stores/workflow-definitions'
import { fetchWorkflowDefinition } from '../../services/workflow-definition-api'
import type { WorkflowDefinition } from '../../services/workflow-definition-api'

/** 流水线卡片数据 */
interface PipelineCard {
  workflowId: string
  name: string
  description: string
  outputs: string[]
  algorithmParams: Record<string, unknown>
}

/** 日期范围预设 */
interface DatePreset {
  label: string
  getRange: () => { start: string; end: string }
}

const props = defineProps<{
  visible: boolean
}>()

const emit = defineEmits<{
  close: []
  launch: [workflowId: string, params: Record<string, unknown>]
}>()

const store = useWorkflowDefinitionsStore()

const pipelines = ref<PipelineCard[]>([])
const loading = ref(false)
const loadError = ref<string | null>(null)
/** 加载进度：已完成 / 总数（并行加载时显示 X/Y） */
const loadProgress = ref<{ done: number; total: number }>({ done: 0, total: 0 })

// 搜索
const searchQuery = ref('')

// 参数面板状态
const selectedPipeline = ref<PipelineCard | null>(null)
const showParams = ref(false)

// 日期输入（原生 input type="date" 使用 YYYY-MM-DD 格式）
const startDate = ref('')
const endDate = ref('')

// 日期范围校验错误提示（start_date > end_date 时阻止启动）
const dateError = ref('')

// 高级参数
const showAdvanced = ref(false)
const advancedParams = ref<Array<{ key: string; value: string }>>([])

// 启动反馈
const launchResult = ref<{ success: boolean; message: string; workflowId: string } | null>(null)

// ─── 日期格式转换 ───────────────────────────────────────────────────────────

/** YYYYMMDD → YYYY-MM-DD（原生 date input 格式） */
function yyyymmddToIso(yyyymmdd: string): string {
  if (!yyyymmdd || yyyymmdd.length !== 8) return ''
  return `${yyyymmdd.slice(0, 4)}-${yyyymmdd.slice(4, 6)}-${yyyymmdd.slice(6, 8)}`
}

/** YYYY-MM-DD → YYYYMMDD */
function isoToYyyymmdd(iso: string): string {
  if (!iso) return ''
  return iso.replace(/-/g, '')
}

/** 获取今天的 ISO 日期 */
function todayIso(): string {
  return new Date().toISOString().slice(0, 10)
}

/** 计算 N 天前的 ISO 日期 */
function daysAgoIso(days: number): string {
  const d = new Date()
  d.setDate(d.getDate() - days)
  return d.toISOString().slice(0, 10)
}

/** 获取本月1日的 ISO 日期 */
function monthStartIso(): string {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-01`
}

/** 获取上月1日的 ISO 日期 */
function lastMonthStartIso(): string {
  const d = new Date()
  d.setMonth(d.getMonth() - 1)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-01`
}

/** 获取上月末日的 ISO 日期 */
function lastMonthEndIso(): string {
  const d = new Date()
  d.setDate(0) // 上月最后一天
  return d.toISOString().slice(0, 10)
}

// ─── 日期预设 ───────────────────────────────────────────────────────────────

const datePresets: DatePreset[] = [
  {
    label: '今天',
    getRange: () => ({ start: todayIso(), end: todayIso() }),
  },
  {
    label: '近7天',
    getRange: () => ({ start: daysAgoIso(7), end: todayIso() }),
  },
  {
    label: '近30天',
    getRange: () => ({ start: daysAgoIso(30), end: todayIso() }),
  },
  {
    label: '本月',
    getRange: () => ({ start: monthStartIso(), end: todayIso() }),
  },
  {
    label: '上月',
    getRange: () => ({ start: lastMonthStartIso(), end: lastMonthEndIso() }),
  },
]

function applyDatePreset(preset: DatePreset) {
  const range = preset.getRange()
  startDate.value = range.start
  endDate.value = range.end
  dateError.value = ''
}

// ─── 安全读取 _meta.tags ────────────────────────────────────────────────────

/** WorkflowDefinitionMeta 未声明 tags 字段，运行时后端会返回，安全读取 */
function readMetaTags(def: WorkflowDefinition): string[] {
  const meta = def._meta as unknown as Record<string, unknown>
  const tags = meta.tags
  return Array.isArray(tags) ? tags.filter((t): t is string => typeof t === 'string') : []
}

/** 安全读取 extra.outputs */
function readExtraOutputs(def: WorkflowDefinition): string[] {
  const outputs = def.extra?.outputs
  if (!Array.isArray(outputs)) return []
  return outputs.filter((t): t is string => typeof t === 'string')
}

/** 从工作流定义的 module 节点中提取 algorithm_params */
function extractAlgorithmParams(def: WorkflowDefinition): Record<string, unknown> {
  for (const node of def.nodes) {
    const nodeProps = node.properties as Record<string, unknown>
    if (
      nodeProps.algorithm_params &&
      typeof nodeProps.algorithm_params === 'object' &&
      !Array.isArray(nodeProps.algorithm_params)
    ) {
      return { ...(nodeProps.algorithm_params as Record<string, unknown>) }
    }
  }
  return {}
}

// ─── 搜索过滤 ───────────────────────────────────────────────────────────────

const filteredPipelines = computed(() => {
  if (!searchQuery.value.trim()) return pipelines.value
  const q = searchQuery.value.toLowerCase()
  return pipelines.value.filter(
    (p) =>
      p.name.toLowerCase().includes(q) ||
      p.description.toLowerCase().includes(q) ||
      p.workflowId.toLowerCase().includes(q),
  )
})

// ─── 加载流水线列表 ──────────────────────────────────────────────────────────

async function loadPipelines() {
  loading.value = true
  loadError.value = null
  pipelines.value = []
  searchQuery.value = ''
  launchResult.value = null
  try {
    // 确保 summaries 已加载
    if (store.summaries.length === 0) {
      await store.loadSummaries()
    }
    const systemWorkflows = store.systemWorkflows
    const total = systemWorkflows.length
    loadProgress.value = { done: 0, total }
    // 并行获取所有系统工作流定义；单个失败不影响其他（allSettled）
    let done = 0
    const defResults = await Promise.allSettled(
      systemWorkflows.map(async (summary) => {
        const def = await fetchWorkflowDefinition(summary.workflow_id)
        done++
        loadProgress.value = { done, total }
        return def
      }),
    )
    const cards: PipelineCard[] = []
    for (const result of defResults) {
      if (result.status !== 'fulfilled') continue
      const def = result.value
      const tags = readMetaTags(def)
      if (!tags.includes('pipeline')) continue
      cards.push({
        workflowId: def.workflow_id,
        name: def.name,
        description: def.description ?? '',
        outputs: readExtraOutputs(def),
        algorithmParams: extractAlgorithmParams(def),
      })
    }
    pipelines.value = cards
  } catch (err) {
    loadError.value = err instanceof Error ? err.message : String(err)
  } finally {
    loading.value = false
  }
}

// ─── 事件处理 ───────────────────────────────────────────────────────────────

function handleLaunchClick(card: PipelineCard) {
  selectedPipeline.value = card
  launchResult.value = null
  const params = card.algorithmParams

  // 初始化日期输入
  const sd = typeof params.start_date === 'string' ? params.start_date : ''
  const ed = typeof params.end_date === 'string' ? params.end_date : ''
  startDate.value = sd ? yyyymmddToIso(sd) : ''
  endDate.value = ed ? yyyymmddToIso(ed) : ''
  // 重置日期范围错误提示
  dateError.value = ''

  // 初始化高级参数（排除 start_date / end_date）
  advancedParams.value = []
  for (const [key, value] of Object.entries(params)) {
    if (key === 'start_date' || key === 'end_date') continue
    advancedParams.value.push({ key, value: String(value) })
  }

  showParams.value = true
}

function handleConfirmLaunch() {
  if (!selectedPipeline.value) return
  if (!startDate.value || !endDate.value) return

  // 日期范围校验：startDate <= endDate（YYYYMMDD 定长字符串可直接字典序比较）
  const sd = isoToYyyymmdd(startDate.value)
  const ed = isoToYyyymmdd(endDate.value)
  if (sd > ed) {
    dateError.value = '开始日期不能晚于结束日期'
    return
  }
  dateError.value = ''

  const params: Record<string, unknown> = {}
  // 高级参数
  for (const adv of advancedParams.value) {
    if (adv.key.trim()) {
      params[adv.key.trim()] = parseParamValue(adv.value)
    }
  }
  // 日期参数（YYYYMMDD 格式）
  params.start_date = sd
  params.end_date = ed

  emit('launch', selectedPipeline.value.workflowId, params)

  // 显示启动成功反馈
  launchResult.value = {
    success: true,
    message: `流水线 "${selectedPipeline.value.name}" 已提交，日期范围 ${sd} → ${ed}`,
    workflowId: selectedPipeline.value.workflowId,
  }

  // 延迟关闭，让用户看到反馈
  setTimeout(() => {
    showParams.value = false
    selectedPipeline.value = null
  }, 1500)
}

/** 尝试将字符串值解析为合适的类型 */
function parseParamValue(raw: string): unknown {
  const trimmed = raw.trim()
  if (trimmed === '') return ''
  if (trimmed === 'true') return true
  if (trimmed === 'false') return false
  const num = Number(trimmed)
  if (!isNaN(num) && trimmed !== '') return num
  return trimmed
}

function handleBack() {
  showParams.value = false
  selectedPipeline.value = null
  launchResult.value = null
}

function handleClose() {
  showParams.value = false
  selectedPipeline.value = null
  launchResult.value = null
  emit('close')
}

/** 快速启动（使用默认参数，跳过参数面板） */
function handleQuickLaunch(card: PipelineCard) {
  const params = { ...card.algorithmParams }
  emit('launch', card.workflowId, params)
  launchResult.value = {
    success: true,
    message: `流水线 "${card.name}" 已使用默认参数快速启动`,
    workflowId: card.workflowId,
  }
  setTimeout(() => {
    launchResult.value = null
  }, 2500)
}

// 对话框打开时加载流水线
watch(
  () => props.visible,
  (visible) => {
    if (visible) {
      void loadPipelines()
    } else {
      showParams.value = false
      selectedPipeline.value = null
      launchResult.value = null
    }
  },
  { immediate: true },
)
</script>

<template>
  <div v-if="visible" class="pipeline-overlay" @click.self="handleClose">
    <div class="pipeline-dialog">
      <header class="pipeline-header">
        <div class="header-left">
          <span class="header-icon" aria-hidden="true">🚀</span>
          <div class="header-titles">
            <h3 class="dialog-title">
              {{ showParams ? '配置流水线参数' : '端到端流水线' }}
            </h3>
            <p v-if="showParams && selectedPipeline" class="dialog-subtitle">
              {{ selectedPipeline.name }}
            </p>
            <p v-else class="dialog-subtitle">选择一个流水线以启动端到端反演流程</p>
          </div>
        </div>
        <button class="close-btn" type="button" @click="handleClose" title="关闭">
          <span aria-hidden="true">✕</span>
        </button>
      </header>

      <!-- 启动反馈横幅 -->
      <div
        v-if="launchResult"
        class="launch-banner"
        :class="launchResult.success ? 'success' : 'error'"
      >
        <span aria-hidden="true">{{ launchResult.success ? '✓' : '✕' }}</span>
        <span>{{ launchResult.message }}</span>
      </div>

      <!-- 加载状态 -->
      <div v-if="loading" class="pipeline-body">
        <div class="loading-hint">
          正在加载流水线列表...<span v-if="loadProgress.total > 0" class="loading-progress"
            >（{{ loadProgress.done }}/{{ loadProgress.total }}）</span
          >
        </div>
      </div>

      <!-- 加载错误 -->
      <div v-else-if="loadError" class="pipeline-body">
        <div class="error-hint">
          <span aria-hidden="true">⚠</span>
          <span>加载失败: {{ loadError }}</span>
        </div>
      </div>

      <!-- 空状态 -->
      <div v-else-if="pipelines.length === 0 && !showParams" class="pipeline-body">
        <div class="empty-hint">未找到带 "pipeline" 标签的系统工作流</div>
      </div>

      <!-- 流水线卡片列表 -->
      <div v-else-if="!showParams" class="pipeline-body">
        <!-- 搜索栏 -->
        <div v-if="pipelines.length > 1" class="search-row">
          <input
            v-model="searchQuery"
            type="text"
            class="search-input"
            placeholder="搜索流水线名称、描述或 ID..."
          />
          <span class="search-count">{{ filteredPipelines.length }}/{{ pipelines.length }}</span>
        </div>

        <div v-for="card in filteredPipelines" :key="card.workflowId" class="pipeline-card">
          <div class="card-header">
            <span class="card-icon" aria-hidden="true">⚙</span>
            <h4 class="card-title">{{ card.name }}</h4>
          </div>
          <p class="card-desc">{{ card.description }}</p>
          <div v-if="card.outputs.length > 0" class="card-outputs">
            <span v-for="output in card.outputs" :key="output" class="output-tag">
              {{ output }}
            </span>
          </div>
          <div class="card-footer">
            <button
              class="quick-btn"
              type="button"
              title="使用默认参数快速启动"
              @click="handleQuickLaunch(card)"
            >
              快速启动
            </button>
            <button class="launch-btn" type="button" @click="handleLaunchClick(card)">
              <span>配置并启动</span>
              <span aria-hidden="true">→</span>
            </button>
          </div>
        </div>

        <!-- 搜索无结果 -->
        <div v-if="filteredPipelines.length === 0 && searchQuery" class="empty-hint">
          未找到匹配 "{{ searchQuery }}" 的流水线
        </div>
      </div>

      <!-- 参数配置面板 -->
      <div v-else class="pipeline-body">
        <div class="param-form">
          <!-- 日期范围预设 -->
          <div class="preset-row">
            <span class="preset-label">快捷选择</span>
            <div class="preset-buttons">
              <button
                v-for="preset in datePresets"
                :key="preset.label"
                class="preset-btn"
                type="button"
                @click="applyDatePreset(preset)"
              >
                {{ preset.label }}
              </button>
            </div>
          </div>

          <div class="date-row">
            <div class="form-row">
              <label class="form-label">开始日期</label>
              <input v-model="startDate" type="date" class="form-input date-input" />
            </div>
            <span class="date-separator">→</span>
            <div class="form-row">
              <label class="form-label">结束日期</label>
              <input v-model="endDate" type="date" class="form-input date-input" />
            </div>
          </div>

          <div class="format-hint">格式: YYYYMMDD（自动转换）</div>

          <!-- 日期范围校验错误 -->
          <div v-if="dateError" class="date-error">{{ dateError }}</div>

          <!-- 高级参数可折叠区域 -->
          <div v-if="advancedParams.length > 0" class="advanced-section">
            <button class="advanced-toggle" type="button" @click="showAdvanced = !showAdvanced">
              <span aria-hidden="true">{{ showAdvanced ? '▼' : '▶' }}</span>
              <span>高级参数 ({{ advancedParams.length }})</span>
            </button>
            <div v-if="showAdvanced" class="advanced-content">
              <div v-for="(adv, idx) in advancedParams" :key="idx" class="form-row compact">
                <label class="form-label">{{ adv.key }}</label>
                <input v-model="adv.value" type="text" class="form-input" :placeholder="adv.key" />
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- 底部操作栏 -->
      <footer class="pipeline-footer">
        <button v-if="showParams" class="action-btn cancel" type="button" @click="handleBack">
          返回
        </button>
        <button
          v-if="showParams"
          class="action-btn confirm"
          type="button"
          :disabled="!startDate || !endDate || !!launchResult"
          @click="handleConfirmLaunch"
        >
          确认启动
        </button>
        <button v-if="!showParams" class="action-btn cancel" type="button" @click="handleClose">
          关闭
        </button>
      </footer>
    </div>
  </div>
</template>

<style scoped>
.pipeline-overlay {
  position: fixed;
  inset: 0;
  z-index: 1200;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(2, 8, 18, 0.62);
  backdrop-filter: blur(4px);
  -webkit-backdrop-filter: blur(4px);
}

.pipeline-dialog {
  width: min(640px, 92vw);
  max-height: 86vh;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  border-radius: 0.9rem;
  border: 1px solid rgba(136, 192, 255, 0.22);
  background: linear-gradient(180deg, rgba(14, 24, 42, 0.96), rgba(8, 16, 30, 0.96));
  box-shadow: 0 20px 48px rgba(1, 8, 16, 0.5);
}

/* ── 头部 ──────────────────────────────────────────────────── */
.pipeline-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.72rem 0.86rem;
  border-bottom: 1px solid rgba(136, 192, 255, 0.12);
}

.header-left {
  display: flex;
  align-items: center;
  gap: 0.52rem;
}

.header-icon {
  font-size: 1rem;
}

.header-titles {
  display: flex;
  flex-direction: column;
  gap: 0.12rem;
}

.dialog-title {
  margin: 0;
  font-size: 0.82rem;
  color: #f0f7ff;
  font-weight: 600;
}

.dialog-subtitle {
  margin: 0;
  font-size: 0.58rem;
  color: #7f93a9;
}

.close-btn {
  padding: 0.32rem 0.46rem;
  border: 1px solid rgba(136, 192, 255, 0.14);
  border-radius: 0.42rem;
  background: transparent;
  color: #6e8ba0;
  cursor: pointer;
  font: inherit;
  font-size: 0.62rem;
  transition: all 0.16s ease;
}

.close-btn:hover {
  border-color: rgba(255, 120, 120, 0.36);
  color: #ff9b9b;
}

/* ── 启动反馈横幅 ────────────────────────────────────────────── */
.launch-banner {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  padding: 0.5rem 0.86rem;
  font-size: 0.62rem;
  font-weight: 500;
}

.launch-banner.success {
  background: rgba(40, 180, 90, 0.12);
  color: #9ff8cf;
  border-bottom: 1px solid rgba(40, 180, 90, 0.25);
}

.launch-banner.error {
  background: rgba(180, 40, 40, 0.12);
  color: #ff9b9b;
  border-bottom: 1px solid rgba(180, 40, 40, 0.25);
}

/* ── 主体 ──────────────────────────────────────────────────── */
.pipeline-body {
  flex: 1 1 auto;
  overflow-y: auto;
  padding: 0.72rem 0.86rem;
  display: flex;
  flex-direction: column;
  gap: 0.6rem;
}

.loading-hint,
.empty-hint,
.error-hint {
  text-align: center;
  padding: 2rem 1rem;
  font-size: 0.66rem;
  color: #7f93a9;
}

.error-hint {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.4rem;
  color: #ff9b9b;
}

/* ── 搜索栏 ────────────────────────────────────────────────── */
.search-row {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-bottom: 0.2rem;
}

.search-input {
  flex: 1;
  padding: 0.36rem 0.62rem;
  border-radius: 0.5rem;
  border: 1px solid rgba(136, 192, 255, 0.18);
  background: rgba(8, 18, 33, 0.6);
  color: #eaf3fb;
  font: inherit;
  font-size: 0.62rem;
  outline: none;
  transition: border-color 0.18s ease;
}

.search-input:focus {
  border-color: rgba(255, 184, 77, 0.4);
}

.search-input::placeholder {
  color: #5a6f85;
}

.search-count {
  font-size: 0.56rem;
  color: #6e8ba0;
  flex: none;
}

/* ── 流水线卡片 ────────────────────────────────────────────── */
.pipeline-card {
  padding: 0.72rem 0.82rem;
  border-radius: 0.62rem;
  border: 1px solid rgba(136, 192, 255, 0.14);
  background: rgba(8, 17, 31, 0.72);
  transition:
    border-color 0.18s ease,
    background 0.18s ease;
}

.pipeline-card:hover {
  border-color: rgba(90, 213, 255, 0.32);
  background: rgba(12, 28, 48, 0.72);
}

.card-header {
  display: flex;
  align-items: center;
  gap: 0.42rem;
  margin-bottom: 0.36rem;
}

.card-icon {
  font-size: 0.72rem;
  color: #5ad5ff;
}

.card-title {
  margin: 0;
  font-size: 0.72rem;
  color: #eaf3fb;
  font-weight: 600;
}

.card-desc {
  margin: 0 0 0.52rem;
  font-size: 0.58rem;
  color: #8aa0b6;
  line-height: 1.5;
}

.card-outputs {
  display: flex;
  flex-wrap: wrap;
  gap: 0.32rem;
  margin-bottom: 0.52rem;
}

.output-tag {
  padding: 0.16rem 0.52rem;
  border-radius: 0.32rem;
  border: 1px solid rgba(120, 255, 160, 0.3);
  background: rgba(40, 180, 90, 0.12);
  color: #9ff8cf;
  font-size: 0.56rem;
  font-weight: 600;
  letter-spacing: 0.02em;
}

.card-footer {
  display: flex;
  justify-content: flex-end;
  gap: 0.4rem;
}

.quick-btn {
  padding: 0.36rem 0.62rem;
  border-radius: 0.52rem;
  border: 1px solid rgba(136, 192, 255, 0.2);
  background: rgba(8, 18, 33, 0.6);
  color: #bfd3e6;
  font: inherit;
  font-size: 0.6rem;
  cursor: pointer;
  transition:
    border-color 0.18s ease,
    background 0.18s ease,
    color 0.18s ease;
}

.quick-btn:hover {
  border-color: rgba(136, 192, 255, 0.4);
  background: rgba(16, 32, 54, 0.8);
  color: #eaf3fb;
}

.launch-btn {
  display: inline-flex;
  align-items: center;
  gap: 0.32rem;
  padding: 0.36rem 0.78rem;
  border-radius: 0.52rem;
  border: 1px solid rgba(255, 184, 77, 0.36);
  background: rgba(255, 184, 77, 0.14);
  color: #ffd38a;
  font: inherit;
  font-size: 0.62rem;
  font-weight: 500;
  cursor: pointer;
  transition:
    border-color 0.18s ease,
    background 0.18s ease,
    color 0.18s ease;
}

.launch-btn:hover {
  border-color: rgba(255, 184, 77, 0.56);
  background: rgba(255, 184, 77, 0.22);
  color: #fff0d4;
}

/* ── 参数表单 ──────────────────────────────────────────────── */
.param-form {
  display: flex;
  flex-direction: column;
  gap: 0.62rem;
}

/* 日期预设 */
.preset-row {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.preset-label {
  font-size: 0.58rem;
  color: #6e8ba0;
  flex: none;
}

.preset-buttons {
  display: flex;
  flex-wrap: wrap;
  gap: 0.32rem;
}

.preset-btn {
  padding: 0.24rem 0.56rem;
  border-radius: 999px;
  border: 1px solid rgba(90, 213, 255, 0.25);
  background: rgba(10, 132, 255, 0.08);
  color: #5ad5ff;
  font: inherit;
  font-size: 0.56rem;
  cursor: pointer;
  transition:
    border-color 0.16s ease,
    background 0.16s ease;
}

.preset-btn:hover {
  border-color: rgba(90, 213, 255, 0.5);
  background: rgba(10, 132, 255, 0.18);
}

/* 日期并排 */
.date-row {
  display: flex;
  align-items: flex-end;
  gap: 0.5rem;
}

.date-row .form-row {
  flex: 1;
}

.date-separator {
  font-size: 0.72rem;
  color: #6e8ba0;
  padding-bottom: 0.4rem;
  flex: none;
}

.form-row {
  display: flex;
  flex-direction: column;
  gap: 0.22rem;
}

.form-row.compact {
  gap: 0.16rem;
}

.form-label {
  font-size: 0.58rem;
  color: #9eb3c8;
  font-weight: 500;
}

.form-input {
  padding: 0.4rem 0.52rem;
  border-radius: 0.5rem;
  border: 1px solid rgba(136, 192, 255, 0.18);
  background: rgba(8, 18, 33, 0.6);
  color: #eaf3fb;
  font: inherit;
  font-size: 0.62rem;
  outline: none;
  transition: border-color 0.18s ease;
}

.form-input:focus {
  border-color: rgba(255, 184, 77, 0.4);
}

.form-input::placeholder {
  color: #5a6f85;
}

.date-input {
  color-scheme: dark;
}

.format-hint {
  font-size: 0.52rem;
  color: #5a7080;
  margin-top: -0.2rem;
}

/* ── 高级参数折叠区 ────────────────────────────────────────── */
.advanced-section {
  margin-top: 0.32rem;
  border-top: 1px solid rgba(136, 192, 255, 0.1);
  padding-top: 0.52rem;
}

.advanced-toggle {
  display: flex;
  align-items: center;
  gap: 0.36rem;
  padding: 0;
  border: none;
  background: transparent;
  color: #8aa0b6;
  font: inherit;
  font-size: 0.6rem;
  cursor: pointer;
  transition: color 0.16s ease;
}

.advanced-toggle:hover {
  color: #c4d6e8;
}

.advanced-content {
  margin-top: 0.52rem;
  display: flex;
  flex-direction: column;
  gap: 0.52rem;
  padding: 0.52rem;
  border-radius: 0.52rem;
  background: rgba(4, 12, 23, 0.4);
  border: 1px solid rgba(136, 192, 255, 0.08);
}

/* ── 底部操作栏 ────────────────────────────────────────────── */
.pipeline-footer {
  display: flex;
  justify-content: flex-end;
  gap: 0.4rem;
  padding: 0.5rem 0.86rem 0.62rem;
  border-top: 1px solid rgba(136, 192, 255, 0.12);
}

.action-btn {
  padding: 0.4rem 0.78rem;
  border-radius: 999px;
  border: 1px solid rgba(136, 192, 255, 0.2);
  background: rgba(8, 18, 33, 0.6);
  color: #bfd3e6;
  font: inherit;
  font-size: 0.62rem;
  cursor: pointer;
  transition:
    border-color 0.18s ease,
    background 0.18s ease,
    color 0.18s ease;
}

.action-btn.cancel:hover {
  border-color: rgba(136, 192, 255, 0.36);
  color: #eaf3fb;
}

.action-btn.confirm {
  border-color: rgba(255, 184, 77, 0.36);
  background: rgba(255, 184, 77, 0.14);
  color: #ffd38a;
}

.action-btn.confirm:hover:not(:disabled) {
  border-color: rgba(255, 184, 77, 0.56);
  background: rgba(255, 184, 77, 0.22);
  color: #fff0d4;
}

.action-btn.confirm:disabled {
  opacity: 0.42;
  cursor: not-allowed;
}

/* 日期范围校验错误提示 */
.date-error {
  font-size: 0.56rem;
  color: #ff7b7b;
  padding: 0.3rem 0.52rem;
  border-radius: 0.5rem;
  border: 1px solid rgba(255, 123, 123, 0.25);
  background: rgba(255, 123, 123, 0.08);
}
</style>
