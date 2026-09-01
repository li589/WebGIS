<script setup lang="ts">
/**
 * 单个分析工具的参数子页：页头（返回 + 工具信息）+ 参数表单 + 运行控制。
 * 表单值/校验状态由父级持有（跨页面往返保留输入）。
 */
import { computed } from 'vue'
import type { AnalysisToolDescriptor } from '../../../services/analysis-api'
import {
  CLIP_BBOX_FIELD_KEYS,
  fieldHintFor,
  formatMapBBoxSummary,
  numericRangeLabel,
  type ToolRunContext,
  runDisabledReasonFor,
  canRunTool,
} from './tool-page-model'
import AppButton from '../../ui/AppButton.vue'
import PageBackButton from './PageBackButton.vue'

const props = defineProps<{
  tool: AnalysisToolDescriptor
  formValues: Record<string, unknown>
  formErrors: Record<string, string>
  runContext: ToolRunContext
  runPhase: string
  runPhaseLabel: string
  runMessage: string
  importedVectorOptions: { id: string; label: string }[]
  mapBBox: { west: number; south: number; east: number; north: number } | null
}>()

const emit = defineEmits<{
  back: []
  run: []
  cancel: []
  setField: [key: string, value: unknown]
}>()

const visibleFields = computed(() => {
  if (props.tool.tool_id !== 'gis.clip' || !props.runContext.hasMapBBox) {
    return props.tool.param_schema
  }
  return props.tool.param_schema.filter((field) => !CLIP_BBOX_FIELD_KEYS.has(field.key))
})

const clipBboxSummary = computed(() => {
  if (props.tool.tool_id !== 'gis.clip' || !props.mapBBox) return ''
  return formatMapBBoxSummary(props.mapBBox)
})

function isRunning(phase: string): boolean {
  return phase === 'running' || phase === 'submitting' || phase === 'queued'
}

function onFieldInput(key: string, evt: Event): void {
  const target = evt.target as HTMLInputElement | HTMLSelectElement
  emit('setField', key, target.value)
}

function onNumberFieldInput(key: string, evt: Event): void {
  const raw = (evt.target as HTMLInputElement).value
  if (raw === '') {
    emit('setField', key, '')
    return
  }
  const num = Number(raw)
  emit('setField', key, Number.isFinite(num) ? num : raw)
}
</script>

<template>
  <div class="tool-page">
    <div class="tool-page-head">
      <PageBackButton @back="emit('back')" />
      <span class="tool-kicker">{{ tool.category }}</span>
      <h4 class="tool-title">{{ tool.title }}</h4>
      <p class="tool-note">{{ tool.description }}</p>
      <p v-if="!tool.enabled && tool.disabled_reason" class="tool-error">
        {{ tool.disabled_reason }}
      </p>
    </div>

    <div v-if="clipBboxSummary" class="bbox-summary">
      <span class="param-label">裁剪范围（当前视口）</span>
      <span class="bbox-summary-val">{{ clipBboxSummary }}</span>
    </div>

    <div class="param-grid">
      <label
        v-for="field in visibleFields"
        :key="field.key"
        class="param-row"
        :title="fieldHintFor(field, tool.tool_id)"
      >
        <span class="param-label">
          {{ field.title || field.key }}
          <em v-if="field.unit">（{{ field.unit }}）</em>
        </span>

        <select
          v-if="field.type === 'enum' && field.options?.length"
          :value="formValues[field.key]"
          class="param-input"
          @change="onFieldInput(field.key, $event)"
        >
          <option v-for="opt in field.options" :key="opt" :value="opt">{{ opt }}</option>
        </select>

        <input
          v-else-if="field.type === 'number' || field.type === 'integer'"
          :value="formValues[field.key]"
          type="number"
          class="param-input"
          :class="{ 'param-input--error': formErrors[field.key] }"
          :min="field.min ?? undefined"
          :max="field.max ?? undefined"
          @input="onNumberFieldInput(field.key, $event)"
        />

        <input
          v-else-if="field.key === 'zones_imported_vector_layer_id'"
          :value="formValues[field.key]"
          type="text"
          class="param-input"
          list="zones-vector-options"
          :class="{ 'param-input--error': formErrors[field.key] }"
          placeholder="从下拉选择已导入矢量层"
          @input="onFieldInput(field.key, $event)"
        />

        <input
          v-else
          :value="formValues[field.key]"
          type="text"
          class="param-input"
          :class="{ 'param-input--error': formErrors[field.key] }"
          :placeholder="fieldHintFor(field, tool.tool_id)"
          @input="onFieldInput(field.key, $event)"
        />

        <span v-if="formErrors[field.key]" class="param-error">{{ formErrors[field.key] }}</span>
        <span v-else-if="fieldHintFor(field, tool.tool_id)" class="param-hint">
          {{ fieldHintFor(field, tool.tool_id) }}
        </span>
        <span v-else-if="numericRangeLabel(field)" class="param-hint">
          {{ numericRangeLabel(field) }}
        </span>
      </label>

      <datalist id="zones-vector-options">
        <option v-for="opt in importedVectorOptions" :key="opt.id" :value="opt.id">
          {{ opt.label }}
        </option>
      </datalist>
    </div>

    <div class="run-row">
      <AppButton
        size="sm"
        variant="primary"
        :disabled="!canRunTool(tool, runContext)"
        @click="emit('run')"
      >
        运行
      </AppButton>
      <AppButton v-if="isRunning(runPhase)" size="sm" variant="secondary" @click="emit('cancel')">
        取消
      </AppButton>
      <span v-if="runPhaseLabel" class="run-phase">{{ runPhaseLabel }}</span>
    </div>

    <p
      v-if="runDisabledReasonFor(tool, runContext) && !canRunTool(tool, runContext)"
      class="tool-hint"
    >
      {{ runDisabledReasonFor(tool, runContext) }}
    </p>
    <p v-if="runMessage" class="tool-hint">{{ runMessage }}</p>
  </div>
</template>

<style scoped>
.tool-page-head {
  display: grid;
  gap: 0.15rem;
  margin-bottom: 0.5rem;
}

.tool-kicker {
  font-size: var(--font-size-caption);
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--text-secondary);
}

.tool-title {
  margin: 0;
  font-size: var(--font-size-body);
}

.tool-note,
.tool-hint {
  margin: 0.2rem 0 0;
  font-size: var(--font-size-caption);
  color: var(--text-secondary);
}

.tool-error {
  margin: 0.2rem 0 0;
  font-size: var(--font-size-caption);
  color: var(--danger, #b91c1c);
}

.bbox-summary {
  display: grid;
  gap: 0.15rem;
  margin-bottom: 0.45rem;
  padding: 0.35rem 0.45rem;
  border-radius: 0.45rem;
  border: 1px solid var(--border-default);
  background: var(--surface-base, transparent);
}

.bbox-summary-val {
  font-size: var(--font-size-caption);
  font-family: var(--font-mono, monospace);
  color: var(--text-secondary);
}

.param-grid {
  display: grid;
  gap: 0.45rem;
  margin-bottom: 0.4rem;
}

.param-row {
  display: grid;
  gap: 0.2rem;
}

.param-label {
  font-size: var(--font-size-caption);
  color: var(--text-secondary);
}

.param-input {
  width: 100%;
  border: 1px solid var(--border-default);
  border-radius: 0.4rem;
  padding: 0.28rem 0.4rem;
  background: var(--surface-base, transparent);
  color: inherit;
}

.param-input--error {
  border-color: var(--danger, #b91c1c);
}

.param-error {
  font-size: var(--font-size-caption);
  color: var(--danger, #b91c1c);
}

.param-hint {
  font-size: var(--font-size-caption);
  color: var(--text-muted);
}

.run-row {
  display: flex;
  align-items: center;
  gap: 0.45rem;
  margin-top: 0.55rem;
}

.run-phase {
  font-size: var(--font-size-caption);
  color: var(--text-secondary);
}
</style>
