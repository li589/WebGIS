<script setup lang="ts">
/**
 * WorkflowInspector.vue
 *
 * 属性检查器：显示并编辑选中节点的属性。
 * 系统预设工作流为只读，不可编辑。
 *
 * 增强：参数分组（基础/高级/数据源）、默认值对比、数组编辑器、tooltip、单位徽章。
 */
import { computed, watch, ref, reactive } from 'vue'
import { Diamond, Lock, Info, X, AlertTriangle } from 'lucide-vue-next'
import { useWorkflowDefinitionsStore } from '../../stores/workflow-definitions'
import type { LGraphNodeClass, INodeInputSlot, INodeOutputSlot } from './litegraph-setup'
import { getPortColor, getPortTypeLabel, suggestConnectorsForPortType } from './litegraph-setup'
import { buildPortTooltip } from './port-tooltip'
import { paramDisplayLabel } from './display-labels'
import ParamField from './ParamField.vue'
import BboxInputField from './BboxInputField.vue'
import DownloadNodeForm from './node-forms/DownloadNodeForm.vue'
import type { ValidationIssue } from '../../composables/workflow-validator'

const props = defineProps<{
  selectedNode: LGraphNodeClass | null
  readonly?: boolean
  validationIssues?: ValidationIssue[]
}>()

const emit = defineEmits<{
  updateProperty: [key: string, value: unknown]
  updateTitle: [title: string]
}>()

const store = useWorkflowDefinitionsStore()

// 本地副本，避免直接修改 prop
const localTitle = ref('')
const localProperties = ref<Record<string, unknown>>({})
// 原始属性（用于默认值对比）：节点首次加载时的快照
const originalProperties = ref<Record<string, unknown>>({})
// 数组编辑器输入缓冲：{ [paramKey]: string }
const arrayInputBuffer = reactive<Record<string, string>>({})

watch(
  () => props.selectedNode,
  (node) => {
    if (!node) {
      localTitle.value = ''
      localProperties.value = {}
      originalProperties.value = {}
      return
    }
    localTitle.value = node.title ?? ''
    // 深拷贝 properties 以避免直接修改
    localProperties.value = { ...(node.properties ?? {}) }
    // 保存原始值副本用于默认值对比
    originalProperties.value = { ...(node.properties ?? {}) }
    // 清空数组输入缓冲
    for (const k of Object.keys(arrayInputBuffer)) {
      delete arrayInputBuffer[k]
    }
  },
  { immediate: true },
)

const nodeInputs = computed<INodeInputSlot[]>(() => props.selectedNode?.inputs ?? [])
const nodeOutputs = computed<INodeOutputSlot[]>(() => props.selectedNode?.outputs ?? [])

// 从节点模板中查找当前节点的描述和参数信息
const nodeTemplate = computed(() => {
  const nodeType = props.selectedNode?.type
  if (!nodeType) return null
  return store.nodeTemplates.find((t) => t.type === nodeType) ?? null
})

const nodeDescription = computed(() => nodeTemplate.value?.description ?? '')

// 下载节点（download/*）走专用参数表单，替代通用 ParamField 列表
const isDownloadNode = computed(() => (props.selectedNode?.type ?? '').startsWith('download/'))
const nodeEngine = computed(() => {
  const type = props.selectedNode?.type ?? ''
  const engine =
    nodeTemplate.value?.engine ??
    (type.startsWith('module/') || type.startsWith('python_provider/')
      ? 'python_provider'
      : type.startsWith('weather/')
        ? 'weather'
        : type.startsWith('gee/')
          ? 'gee'
          : 'common')
  if (engine === 'weather') return '天气引擎'
  if (engine === 'python_provider') return 'Python 处理器'
  if (engine === 'gee') return 'GEE'
  return '通用'
})

const nodeEngineIcon = computed(() => {
  const type = props.selectedNode?.type ?? ''
  const engine =
    nodeTemplate.value?.engine ??
    (type.startsWith('module/') || type.startsWith('python_provider/')
      ? 'python_provider'
      : type.startsWith('weather/')
        ? 'weather'
        : type.startsWith('gee/')
          ? 'gee'
          : 'common')
  if (engine === 'weather') return '☀'
  if (engine === 'python_provider') return '⚡'
  if (engine === 'gee') return '🌍'
  return '◈'
})

// 参数信息（从模板获取，含说明）
const templateParams = computed(() => nodeTemplate.value?.params ?? [])

// 参数元信息映射（key -> param meta），用于按 key 快速查找
const templateParamMap = computed(() => {
  const m: Record<string, (typeof templateParams.value)[number]> = {}
  for (const p of templateParams.value) m[p.key] = p
  return m
})

function getParamMeta(key: string) {
  return templateParamMap.value[key]
}

function getParamLabel(key: string): string {
  const meta = getParamMeta(key)
  return paramDisplayLabel(key, meta?.description)
}

function getParamHint(key: string): string {
  const param = getParamMeta(key)
  if (!param) return ''
  const parts: string[] = []
  if (param.type) parts.push(param.type)
  if (param.options?.length) parts.push(`选项: ${param.options.join(', ')}`)
  if (param.min != null && param.max != null) parts.push(`范围: ${param.min}~${param.max}`)
  return parts.join(' · ')
}

function getParamPlaceholder(key: string): string {
  const meta = getParamMeta(key)
  if (!meta) return ''
  if (meta.type === 'array') return '逗号分隔，如 A,B,C'
  return meta.description || ''
}

// 合成 tooltip 完整描述
function getParamTooltip(key: string): string {
  const meta = getParamMeta(key)
  if (!meta) return ''
  const parts: string[] = []
  if (meta.description) parts.push(meta.description)
  if (meta.unit) parts.push(`单位: ${meta.unit}`)
  if (meta.options?.length) parts.push(`可选: ${meta.options.join(', ')}`)
  if (meta.min != null && meta.max != null) parts.push(`范围: ${meta.min} ~ ${meta.max}`)
  if (meta.step != null) parts.push(`步长: ${meta.step}`)
  return parts.join('\n')
}

// ─── 参数分组 ────────────────────────────────────────────────────────────────
interface GroupedProperties {
  basic: Array<[string, unknown]>
  advanced: Array<[string, unknown]>
  datasource: Array<[string, unknown]>
  /** widget=bbox 聚合参数组：每个元素是 [anchorKey, bboxKeys] */
  bboxGroups: Array<{ anchorKey: string; bboxKeys: Record<string, string> }>
}

const DATASOURCE_KEYS = new Set(['dataset_key', 'path', 'pattern'])

/**
 * 计算 bbox 聚合参数组：当某个参数声明了 widget="bbox" + bbox_keys 时，
 * 将 bbox_keys 中涉及的 4 个 key 标记为"已聚合"，在分组时跳过独立渲染。
 */
const bboxAggregation = computed(() => {
  const groups: Array<{ anchorKey: string; bboxKeys: Record<string, string> }> = []
  const consumedKeys = new Set<string>()
  for (const p of templateParams.value) {
    if (p.widget === 'bbox' && p.bbox_keys) {
      const keys = p.bbox_keys
      groups.push({ anchorKey: p.key, bboxKeys: keys })
      for (const v of Object.values(keys)) {
        if (v) consumedKeys.add(v)
      }
    }
  }
  return { groups, consumedKeys }
})

const groupedProperties = computed<GroupedProperties>(() => {
  const result: GroupedProperties = {
    basic: [],
    advanced: [],
    datasource: [],
    bboxGroups: bboxAggregation.value.groups,
  }
  const consumed = bboxAggregation.value.consumedKeys
  for (const [key, value] of Object.entries(localProperties.value)) {
    if (consumed.has(key)) continue // 被 bbox 聚合的 key 跳过独立渲染
    const meta = getParamMeta(key)
    if (DATASOURCE_KEYS.has(key)) {
      result.datasource.push([key, value])
    } else if (meta?.type === 'array' || key.endsWith('_advanced')) {
      result.advanced.push([key, value])
    } else {
      result.basic.push([key, value])
    }
  }
  return result
})

/** 从 localProperties 中提取 bbox 聚合值 */
function getBboxValue(bboxKeys: Record<string, string>): Record<string, number> {
  const result: Record<string, number> = {}
  for (const [field, key] of Object.entries(bboxKeys)) {
    if (key) result[field] = Number(localProperties.value[key]) || 0
  }
  return result
}

/** 将 bbox 聚合值写回各独立 key */
function handleBboxChange(bboxKeys: Record<string, string>, value: Record<string, number>) {
  for (const [field, key] of Object.entries(bboxKeys)) {
    if (key) {
      localProperties.value[key] = value[field] ?? 0
      emit('updateProperty', key, value[field] ?? 0)
    }
  }
}

// ─── 默认值对比 ──────────────────────────────────────────────────────────────
/**
 * 浅层相等对比，避免对大对象使用 JSON.stringify 的性能开销。
 * - 基本类型：直接 ===
 * - 数组：长度对比 + 逐元素 ===
 * - 对象：keys 数量对比 + 逐 key 浅层递归对比
 * - 其他（函数/Symbol 等无法用 === 区分的引用类型）：fallback 到 JSON.stringify
 */
function shallowEqual(a: unknown, b: unknown): boolean {
  // 同引用或同基本类型值直接命中（含 null === null、undefined === undefined）
  if (a === b) return true
  // 走到这里说明引用不同；若任一为 null/undefined 或非对象类型，则必不相等
  if (a === null || b === null || typeof a !== 'object' || typeof b !== 'object') {
    return false
  }
  const aIsArray = Array.isArray(a)
  const bIsArray = Array.isArray(b)
  // 数组：长度对比 + 逐元素 ===（元素不递归，保持浅层语义）
  if (aIsArray || bIsArray) {
    if (!aIsArray || !bIsArray) return false
    const arrA = a as unknown[]
    const arrB = b as unknown[]
    if (arrA.length !== arrB.length) return false
    for (let i = 0; i < arrA.length; i++) {
      if (arrA[i] !== arrB[i]) return false
    }
    return true
  }
  // 普通对象：keys 数量对比 + 逐 key 浅层递归对比
  const objA = a as Record<string, unknown>
  const objB = b as Record<string, unknown>
  const keysA = Object.keys(objA)
  const keysB = Object.keys(objB)
  if (keysA.length !== keysB.length) return false
  for (const key of keysA) {
    if (!Object.prototype.hasOwnProperty.call(objB, key)) return false
    if (!shallowEqual(objA[key], objB[key])) return false
  }
  return true
}

function isModified(key: string): boolean {
  const current = localProperties.value[key]
  const original = originalProperties.value[key]
  // 浅层 key-by-key 对比，避免大参数对象的 JSON.stringify 开销
  return !shallowEqual(current, original)
}

function resetToOriginal(key: string) {
  const original = originalProperties.value[key]
  localProperties.value[key] = JSON.parse(JSON.stringify(original))
  // 清除验证错误
  delete validationErrors.value[key]
  emit('updateProperty', key, localProperties.value[key])
}

// ─── 数组编辑器 ──────────────────────────────────────────────────────────────
function parseArrayValue(value: unknown): string[] {
  if (Array.isArray(value)) return value.map(String)
  if (typeof value === 'string' && value.trim()) {
    return value
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean)
  }
  return []
}

function addArrayItem(key: string, event: KeyboardEvent) {
  const input = event.target as HTMLInputElement
  const item = input.value.trim()
  if (!item) return
  const current = parseArrayValue(localProperties.value[key])
  if (current.includes(item)) {
    // 已存在，不重复添加
    arrayInputBuffer[key] = ''
    return
  }
  current.push(item)
  localProperties.value[key] = current
  arrayInputBuffer[key] = ''
  emit('updateProperty', key, current)
}

function removeArrayItem(key: string, idx: number) {
  const current = parseArrayValue(localProperties.value[key])
  if (idx < 0 || idx >= current.length) return
  current.splice(idx, 1)
  localProperties.value[key] = current
  emit('updateProperty', key, current)
}

// ─── 参数验证 ────────────────────────────────────────────────────────────────
// 参数验证：返回错误提示字符串，无错误返回 null
function validateParam(key: string, value: unknown): string | null {
  const meta = getParamMeta(key)
  if (!meta) return null
  // number 范围验证
  if (meta.type === 'number' && typeof value === 'number') {
    if (meta.min != null && value < meta.min) return `最小值 ${meta.min}`
    if (meta.max != null && value > meta.max) return `最大值 ${meta.max}`
  }
  // 特定参数物理范围验证
  if (key === 'freq_ghz' && typeof value === 'number' && (value < 0.1 || value > 40)) {
    return '频率范围 0.1-40 GHz'
  }
  if (
    (key === 'west' || key === 'east') &&
    typeof value === 'number' &&
    (value < -180 || value > 180)
  ) {
    return '经度范围 -180~180'
  }
  if (
    (key === 'south' || key === 'north') &&
    typeof value === 'number' &&
    (value < -90 || value > 90)
  ) {
    return '纬度范围 -90~90'
  }
  return null
}

const validationErrors = ref<Record<string, string>>({})

function buildInspectorPortTitle(
  name: string,
  type: string,
  direction: 'input' | 'output',
): string {
  const fromTpl =
    direction === 'input'
      ? nodeTemplate.value?.inputs?.find((p) => p.name === name)?.description
      : nodeTemplate.value?.outputs?.find((p) => p.name === name)?.description
  const model = buildPortTooltip({
    direction,
    name,
    type,
    description: fromTpl || getParamMeta(name)?.description,
    suggestTitles: suggestConnectorsForPortType(type).map(
      (t) => store.nodeTemplates.find((n) => n.type === t)?.title ?? t,
    ),
  })
  return [model.typeLabel, model.body, ...model.tips].filter(Boolean).join('\n')
}

function handlePropertyChange(key: string, value: unknown) {
  const err = validateParam(key, value)
  if (err) validationErrors.value[key] = err
  else delete validationErrors.value[key]
  localProperties.value[key] = value
  emit('updateProperty', key, value)
}

function handleTitleChange() {
  if (localTitle.value.trim() && localTitle.value !== props.selectedNode?.title) {
    emit('updateTitle', localTitle.value.trim())
  }
}
</script>

<template>
  <div class="inspector">
    <div class="inspector-header">
      <span class="header-title">属性</span>
    </div>

    <div v-if="!selectedNode" class="inspector-empty">
      <Diamond :size="20" class="empty-icon" aria-hidden="true" />
      <span class="empty-text">未选中节点</span>
      <span class="empty-hint">在画布上点击节点查看属性</span>
    </div>

    <div v-else class="inspector-content">
      <!-- 节点描述 -->
      <div v-if="nodeDescription" class="node-description">
        <div class="desc-header">
          <span class="desc-engine-icon" aria-hidden="true">{{ nodeEngineIcon }}</span>
          <span class="desc-engine">{{ nodeEngine }}</span>
        </div>
        <p class="desc-text">{{ nodeDescription }}</p>
      </div>

      <!-- 运行前校验问题 -->
      <div v-if="validationIssues && validationIssues.length > 0" class="node-validation-issues">
        <div
          v-for="(issue, idx) in validationIssues"
          :key="idx"
          class="validation-issue"
          :class="issue.severity"
        >
          <X v-if="issue.severity === 'error'" :size="14" class="issue-icon" aria-hidden="true" />
          <AlertTriangle v-else :size="14" class="issue-icon" aria-hidden="true" />
          <span class="issue-message">{{ issue.message }}</span>
        </div>
      </div>

      <!-- 基本信息 -->
      <section class="inspector-section">
        <h3 class="section-title">基本信息</h3>

        <div class="form-row">
          <label class="form-label">标题</label>
          <input
            v-model="localTitle"
            type="text"
            class="form-input"
            :readonly="readonly"
            @blur="handleTitleChange"
            @keydown.enter="handleTitleChange"
          />
        </div>

        <div class="form-row">
          <label class="form-label">类型</label>
          <input
            :value="selectedNode.type ?? ''"
            type="text"
            class="form-input readonly"
            readonly
          />
        </div>

        <div class="form-row">
          <label class="form-label">ID</label>
          <input :value="selectedNode.id" type="text" class="form-input readonly" readonly />
        </div>

        <div class="form-row">
          <label class="form-label">位置</label>
          <div class="form-pair">
            <input
              :value="selectedNode.pos?.[0] ?? 0"
              type="number"
              class="form-input readonly"
              readonly
            />
            <input
              :value="selectedNode.pos?.[1] ?? 0"
              type="number"
              class="form-input readonly"
              readonly
            />
          </div>
        </div>
      </section>

      <!-- 输入端口：详细说明请在画布上悬停连接点查看 -->
      <section v-if="nodeInputs.length" class="inspector-section">
        <h3 class="section-title">输入端口 ({{ nodeInputs.length }})</h3>
        <p class="ports-hint">在画布上把鼠标移到连接点上，可查看详细说明与推荐连线。</p>
        <div class="port-list">
          <div
            v-for="(input, idx) in nodeInputs"
            :key="`in-${idx}`"
            class="port-item"
            :title="buildInspectorPortTitle(input.name, String(input.type), 'input')"
          >
            <span
              class="port-color-dot"
              :style="{ background: getPortColor(String(input.type)) }"
            ></span>
            <span class="port-name">{{ input.name }}</span>
            <span class="port-type">{{ getPortTypeLabel(String(input.type)) }}</span>
            <span class="port-status" :class="{ connected: input.link !== null }">
              {{ input.link !== null ? '已连接' : '未连接' }}
            </span>
          </div>
        </div>
      </section>

      <!-- 输出端口 -->
      <section v-if="nodeOutputs.length" class="inspector-section">
        <h3 class="section-title">输出端口 ({{ nodeOutputs.length }})</h3>
        <div class="port-list">
          <div
            v-for="(output, idx) in nodeOutputs"
            :key="`out-${idx}`"
            class="port-item"
            :title="buildInspectorPortTitle(output.name, String(output.type), 'output')"
          >
            <span
              class="port-color-dot"
              :style="{ background: getPortColor(String(output.type)) }"
            ></span>
            <span class="port-name">{{ output.name }}</span>
            <span class="port-type">{{ getPortTypeLabel(String(output.type)) }}</span>
            <span
              class="port-status"
              :class="{ connected: output.links && output.links.length > 0 }"
            >
              {{
                output.links && output.links.length > 0 ? `${output.links.length} 连接` : '未连接'
              }}
            </span>
          </div>
        </div>
      </section>

      <!-- 下载节点专用参数表单：替代通用 ParamField 列表 -->
      <section v-if="isDownloadNode" class="inspector-section">
        <h3 class="section-title">下载参数</h3>
        <DownloadNodeForm
          :node="selectedNode"
          :readonly="readonly"
          @update-property="handlePropertyChange"
        />
      </section>

      <!-- 属性：按分组显示 -->
      <section v-else-if="Object.keys(localProperties).length" class="inspector-section">
        <h3 class="section-title">自定义属性</h3>

        <!-- 数据源参数 -->
        <div v-if="groupedProperties.datasource.length" class="param-group">
          <h4 class="param-group-title">数据源</h4>
          <div class="property-list">
            <div v-for="[key, value] in groupedProperties.datasource" :key="key" class="form-row">
              <label class="form-label">
                <span class="param-label-text" :class="{ modified: isModified(key) }">
                  {{ getParamLabel(key)
                  }}<span v-if="isModified(key)" class="modified-mark">*</span>
                </span>
                <span v-if="getParamHint(key)" class="param-hint">{{ getParamHint(key) }}</span>
                <Info :size="14" class="param-info-icon" :title="getParamTooltip(key)" />
                <span v-if="getParamMeta(key)?.unit" class="param-unit-badge">{{
                  getParamMeta(key)?.unit
                }}</span>
                <button
                  v-if="isModified(key) && !readonly"
                  class="reset-btn"
                  type="button"
                  title="重置为初始值"
                  @click="resetToOriginal(key)"
                >
                  ↺
                </button>
              </label>

              <ParamField
                :param-key="key"
                :value="value"
                :meta="getParamMeta(key)"
                :readonly="readonly"
                :error="Boolean(validationErrors[key])"
                :placeholder="getParamPlaceholder(key)"
                :array-buffer="arrayInputBuffer[key]"
                @change="handlePropertyChange(key, $event)"
                @update:array-buffer="arrayInputBuffer[key] = $event"
                @add-array="addArrayItem(key, $event)"
                @remove-array="removeArrayItem(key, $event)"
              />

              <!-- 验证错误提示 -->
              <span v-if="validationErrors[key]" class="param-error">
                {{ validationErrors[key] }}
              </span>
            </div>
          </div>
        </div>

        <!-- bbox 聚合参数组 -->
        <div v-if="groupedProperties.bboxGroups.length" class="param-group">
          <h4 class="param-group-title">空间范围</h4>
          <div class="property-list">
            <div
              v-for="(grp, idx) in groupedProperties.bboxGroups"
              :key="`bbox-${idx}`"
              class="form-row"
            >
              <label class="form-label">
                <span class="param-label-text">{{ grp.anchorKey }}</span>
                <Info :size="14" class="param-info-icon" title="西/南/东/北四至范围，可使用预设快捷选择" />
              </label>
              <BboxInputField
                :model-value="getBboxValue(grp.bboxKeys)"
                :readonly="readonly"
                :field-keys="grp.bboxKeys"
                @update:model-value="handleBboxChange(grp.bboxKeys, $event)"
              />
            </div>
          </div>
        </div>

        <!-- 基础参数 -->
        <div v-if="groupedProperties.basic.length" class="param-group">
          <h4 class="param-group-title">基础参数</h4>
          <div class="property-list">
            <div v-for="[key, value] in groupedProperties.basic" :key="key" class="form-row">
              <label class="form-label">
                <span class="param-label-text" :class="{ modified: isModified(key) }">
                  {{ getParamLabel(key)
                  }}<span v-if="isModified(key)" class="modified-mark">*</span>
                </span>
                <span v-if="getParamHint(key)" class="param-hint">{{ getParamHint(key) }}</span>
                <Info :size="14" class="param-info-icon" :title="getParamTooltip(key)" />
                <span v-if="getParamMeta(key)?.unit" class="param-unit-badge">{{
                  getParamMeta(key)?.unit
                }}</span>
                <button
                  v-if="isModified(key) && !readonly"
                  class="reset-btn"
                  type="button"
                  title="重置为初始值"
                  @click="resetToOriginal(key)"
                >
                  ↺
                </button>
              </label>

              <ParamField
                :param-key="key"
                :value="value"
                :meta="getParamMeta(key)"
                :readonly="readonly"
                :error="Boolean(validationErrors[key])"
                :placeholder="getParamPlaceholder(key)"
                :array-buffer="arrayInputBuffer[key]"
                @change="handlePropertyChange(key, $event)"
                @update:array-buffer="arrayInputBuffer[key] = $event"
                @add-array="addArrayItem(key, $event)"
                @remove-array="removeArrayItem(key, $event)"
              />

              <span v-if="validationErrors[key]" class="param-error">
                {{ validationErrors[key] }}
              </span>
            </div>
          </div>
        </div>

        <!-- 高级参数 -->
        <div v-if="groupedProperties.advanced.length" class="param-group">
          <h4 class="param-group-title">高级参数</h4>
          <div class="property-list">
            <div v-for="[key, value] in groupedProperties.advanced" :key="key" class="form-row">
              <label class="form-label">
                <span class="param-label-text" :class="{ modified: isModified(key) }">
                  {{ getParamLabel(key)
                  }}<span v-if="isModified(key)" class="modified-mark">*</span>
                </span>
                <span v-if="getParamHint(key)" class="param-hint">{{ getParamHint(key) }}</span>
                <Info :size="14" class="param-info-icon" :title="getParamTooltip(key)" />
                <span v-if="getParamMeta(key)?.unit" class="param-unit-badge">{{
                  getParamMeta(key)?.unit
                }}</span>
                <button
                  v-if="isModified(key) && !readonly"
                  class="reset-btn"
                  type="button"
                  title="重置为初始值"
                  @click="resetToOriginal(key)"
                >
                  ↺
                </button>
              </label>

              <ParamField
                :param-key="key"
                :value="value"
                :meta="getParamMeta(key)"
                :readonly="readonly"
                :error="Boolean(validationErrors[key])"
                :placeholder="getParamPlaceholder(key)"
                :array-buffer="arrayInputBuffer[key]"
                @change="handlePropertyChange(key, $event)"
                @update:array-buffer="arrayInputBuffer[key] = $event"
                @add-array="addArrayItem(key, $event)"
                @remove-array="removeArrayItem(key, $event)"
              />

              <span v-if="validationErrors[key]" class="param-error">
                {{ validationErrors[key] }}
              </span>
            </div>
          </div>
        </div>
      </section>

      <div v-if="readonly" class="readonly-hint">
        <Lock :size="14" aria-hidden="true" />
        <span>系统预设工作流为只读</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.inspector {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: rgba(8, 17, 31, 0.72);
  color: #c4d6e8;
}

.inspector-header {
  padding: 0.62rem 0.72rem;
  border-bottom: 1px solid rgba(136, 192, 255, 0.1);
  font-size: var(--font-size-caption);
  font-weight: 600;
  color: var(--text-primary);
}

.inspector-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 0.36rem;
  padding: 2.2rem 1rem;
  color: var(--text-disabled);
  text-align: center;
}

.empty-icon {
  font-size: 1.8rem;
  opacity: 0.4;
}

.empty-text {
  font-size: var(--font-size-caption);
  color: var(--text-faint);
}

.empty-hint {
  font-size: var(--font-size-caption);
  color: #4a5a6a;
}

.inspector-content {
  flex: 1;
  overflow-y: auto;
  padding: 0.42rem 0.62rem;
  scrollbar-width: thin;
  scrollbar-color: rgba(90, 180, 255, 0.28) transparent;
}

.inspector-content::-webkit-scrollbar {
  width: 4px;
}

.inspector-content::-webkit-scrollbar-track {
  background: transparent;
}

.inspector-content::-webkit-scrollbar-thumb {
  background: rgba(90, 180, 255, 0.26);
  border-radius: 3px;
}

.inspector-content::-webkit-scrollbar-thumb:hover {
  background: rgba(90, 180, 255, 0.45);
}

/* 节点描述卡片 */
.node-description {
  margin-bottom: 0.62rem;
  padding: 0.52rem 0.62rem;
  border: 1px solid rgba(90, 213, 255, 0.14);
  border-radius: 0.42rem;
  background: rgba(10, 132, 255, 0.06);
}

.desc-header {
  display: flex;
  align-items: center;
  gap: 0.32rem;
  margin-bottom: 0.28rem;
}

.desc-engine-icon {
  font-size: var(--font-size-caption);
}

.desc-engine {
  font-size: var(--font-size-caption);
  font-weight: 600;
  color: var(--accent);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.desc-text {
  margin: 0;
  font-size: var(--font-size-caption);
  line-height: 1.4;
  color: var(--text-muted);
}

/* 运行前校验问题 */
.node-validation-issues {
  margin-bottom: 0.52rem;
  padding: 0.32rem 0.42rem;
  background: rgba(255, 107, 107, 0.08);
  border: 1px solid rgba(255, 107, 107, 0.25);
  border-radius: 4px;
}

.validation-issue {
  display: flex;
  align-items: flex-start;
  gap: 0.32rem;
  font-size: var(--font-size-caption);
  line-height: 1.4;
  padding: 0.12rem 0;
}

.validation-issue.warning {
  color: #e0a030;
}

.validation-issue.error {
  color: #ff6b6b;
}

.issue-icon {
  flex-shrink: 0;
  font-weight: 700;
  font-size: var(--font-size-caption);
}

.issue-message {
  flex: 1;
  min-width: 0;
  word-break: break-word;
}

/* 参数提示 */
.param-hint {
  display: block;
  margin-top: 0.1rem;
  font-size: var(--font-size-caption);
  font-weight: 400;
  color: var(--text-disabled);
  font-family: 'Consolas', 'Monaco', monospace;
}

/* 参数分组标题 */
.param-group {
  margin-bottom: 0.52rem;
}

.param-group-title {
  margin: 0 0 0.32rem;
  padding: 0.18rem 0.42rem;
  font-size: var(--font-size-caption);
  font-weight: 600;
  color: var(--text-faint);
  letter-spacing: 0.04em;
  text-transform: uppercase;
  border-left: 2px solid rgba(136, 192, 255, 0.3);
  background: rgba(136, 192, 255, 0.04);
}

/* 参数 label 容器：横向布局 */
.form-label {
  display: flex;
  align-items: center;
  gap: 0.28rem;
  font-size: var(--font-size-caption);
  color: var(--text-faint);
  font-weight: 500;
}

.param-label-text {
  flex: 1;
}

.param-label-text.modified {
  color: #ffd38a;
}

.modified-mark {
  color: #ffb84d;
  margin-left: 0.18rem;
}

/* 参数信息图标 */
.param-info-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 0.92rem;
  height: 0.92rem;
  border-radius: 50%;
  background: rgba(136, 192, 255, 0.1);
  color: var(--accent-strong);
  font-size: var(--font-size-caption);
  cursor: help;
  flex: none;
}

.param-info-icon:hover {
  background: rgba(90, 213, 255, 0.24);
  color: var(--accent);
}

/* 单位徽章 */
.param-unit-badge {
  display: inline-flex;
  align-items: center;
  padding: 0.04rem 0.32rem;
  border-radius: 0.24rem;
  background: rgba(90, 213, 255, 0.18);
  color: var(--accent);
  font-size: var(--font-size-caption);
  font-weight: 600;
  flex: none;
}

/* 重置按钮 */
.reset-btn {
  width: 1rem;
  height: 1rem;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 1px solid rgba(255, 184, 77, 0.3);
  border-radius: 0.32rem;
  background: transparent;
  color: #ffb84d;
  cursor: pointer;
  font-size: var(--font-size-caption);
  flex: none;
  transition: all 0.16s ease;
}

.reset-btn:hover {
  background: rgba(255, 184, 77, 0.16);
  color: #ffd38a;
}

.inspector-section {
  margin-bottom: 0.72rem;
  padding-bottom: 0.42rem;
  border-bottom: 1px solid rgba(136, 192, 255, 0.06);
}

.inspector-section:last-child {
  border-bottom: none;
}

.section-title {
  margin: 0 0 0.42rem;
  font-size: var(--font-size-caption);
  font-weight: 600;
  color: var(--accent-strong);
  letter-spacing: 0.02em;
}

.form-row {
  display: flex;
  flex-direction: column;
  gap: 0.18rem;
  margin-bottom: 0.42rem;
}

.form-input {
  padding: 0.32rem 0.42rem;
  border: 1px solid rgba(136, 192, 255, 0.14);
  border-radius: 0.36rem;
  background: var(--surface-raised);
  color: var(--text-primary);
  font: inherit;
  font-size: var(--font-size-caption);
}

.form-input.readonly {
  background: rgba(4, 12, 23, 0.3);
  color: var(--text-faint);
  cursor: default;
}

.form-input:focus {
  outline: none;
  border-color: rgba(90, 213, 255, 0.4);
}

.form-pair {
  display: flex;
  gap: 0.32rem;
}

.form-pair .form-input {
  flex: 1;
}

.port-list,
.property-list {
  display: flex;
  flex-direction: column;
  gap: 0.18rem;
}

.ports-hint {
  margin: 0 0 0.4rem;
  font-size: var(--font-size-caption);
  line-height: 1.4;
  color: #7f96ad;
}

.port-item {
  display: flex;
  align-items: center;
  gap: 0.32rem;
  padding: 0.28rem 0.42rem;
  border: 1px solid rgba(136, 192, 255, 0.06);
  border-radius: 0.36rem;
  background: rgba(4, 12, 23, 0.3);
  font-size: var(--font-size-caption);
}

.port-name {
  flex: 1;
  color: var(--text-primary);
  font-weight: 500;
}

.port-type {
  color: var(--accent);
  font-family: 'Consolas', 'Monaco', monospace;
  font-size: var(--font-size-caption);
}

.port-status {
  padding: 0.04rem 0.28rem;
  border-radius: 0.24rem;
  background: rgba(136, 192, 255, 0.06);
  color: var(--text-faint);
  font-size: var(--font-size-caption);
}

.port-status.connected {
  background: rgba(114, 255, 207, 0.1);
  color: var(--success);
}

/* 端口类型颜色色块 */
.port-color-dot {
  display: inline-block;
  width: 0.5rem;
  height: 0.5rem;
  border-radius: 50%;
  flex-shrink: 0;
  border: 1px solid rgba(255, 255, 255, 0.2);
}

/* 验证错误状态 */
.form-input.error {
  border-color: rgba(255, 107, 107, 0.6);
  background: rgba(60, 20, 20, 0.3);
}

.param-error {
  font-size: var(--font-size-caption);
  color: #ff8a8a;
  margin-top: 0.08rem;
}

/* Toggle 开关样式 */
.toggle-switch {
  position: relative;
  display: inline-block;
  width: 2rem;
  height: 1rem;
  flex-shrink: 0;
}

.toggle-switch input {
  opacity: 0;
  width: 0;
  height: 0;
}

.toggle-slider {
  position: absolute;
  cursor: pointer;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(136, 192, 255, 0.15);
  border-radius: 1rem;
  transition: 0.2s;
}

.toggle-slider::before {
  position: absolute;
  content: '';
  height: 0.72rem;
  width: 0.72rem;
  left: 0.14rem;
  bottom: 0.14rem;
  background: var(--text-faint);
  border-radius: 50%;
  transition: 0.2s;
}

.toggle-switch input:checked + .toggle-slider {
  background: var(--accent-border);
}

.toggle-switch input:checked + .toggle-slider::before {
  transform: translateX(1rem);
  background: var(--accent);
}

.toggle-switch.disabled {
  opacity: 0.5;
  pointer-events: none;
}

/* 数组编辑器 */
.array-editor {
  display: flex;
  flex-wrap: wrap;
  gap: 0.22rem;
  padding: 0.32rem 0.42rem;
  border: 1px solid rgba(136, 192, 255, 0.14);
  border-radius: 0.36rem;
  background: var(--surface-raised);
  min-height: 2rem;
  align-items: center;
}

.array-chip {
  display: inline-flex;
  align-items: center;
  gap: 0.18rem;
  padding: 0.16rem 0.36rem;
  border-radius: 0.28rem;
  background: rgba(90, 213, 255, 0.18);
  color: var(--accent);
  font-size: var(--font-size-caption);
  font-weight: 500;
}

.chip-remove {
  width: 0.72rem;
  height: 0.72rem;
  display: flex;
  align-items: center;
  justify-content: center;
  border: none;
  background: transparent;
  color: var(--accent);
  cursor: pointer;
  font-size: var(--font-size-caption);
  line-height: 1;
  padding: 0;
  transition: color 0.12s ease;
}

.chip-remove:hover {
  color: #ff8a8a;
}

.array-input {
  flex: 1;
  min-width: 6rem;
  border: none;
  background: transparent;
  color: var(--text-primary);
  font: inherit;
  font-size: var(--font-size-caption);
  outline: none;
}

.array-input::placeholder {
  color: var(--text-disabled);
}

.readonly-hint {
  display: flex;
  align-items: center;
  gap: 0.36rem;
  margin-top: 0.62rem;
  padding: 0.42rem 0.52rem;
  border: 1px solid rgba(255, 180, 90, 0.2);
  border-radius: 0.42rem;
  background: rgba(90, 60, 20, 0.18);
  color: #ffd9a8;
  font-size: var(--font-size-caption);
}
</style>
