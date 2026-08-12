<script setup lang="ts">
/**
 * WorkflowTimerEditorForm.vue — 定时器新建/编辑表单字段（主从详情或对话框复用）
 */
import { DATE_TEMPLATES } from '../../services/workflow-timer-api'
import type { TriggerType } from '../../services/workflow-timer-api'
import { AlertTriangle, XCircle } from '../ui/icons'
import AppSelect from '../ui/AppSelect.vue'

defineProps<{
  model: {
    timer_id: string
    workflow_id: string
    name: string
    trigger_type: TriggerType
    cron_expr: string
    interval_seconds: number
    event_type: string
    enabled: boolean
    payload_overrides_json: string
  }
  workflowOptions: Array<{ workflow_id: string; name: string }>
  workflowLocked: boolean
  cronPresets: Array<{ label: string; expr: string; description: string }>
  cronPreviewTimes: string[]
  cronPreviewError: string | null
  cronPreviewLoading: boolean
  showDateTemplates: boolean
  editorError: string | null
  editorSaving: boolean
  formatTime: (iso: string | null) => string
}>()

const emit = defineEmits<{
  'update:model': [value: Record<string, unknown>]
  'update:showDateTemplates': [value: boolean]
  applyCronPreset: [expr: string]
  insertDateTemplate: [template: string]
  save: []
  cancel: []
}>()

function patch(key: string, value: unknown) {
  emit('update:model', { [key]: value })
}
</script>

<template>
  <div class="timer-editor-form">
    <div class="form-row">
      <label class="form-label">工作流 *</label>
      <AppSelect
        :model-value="model.workflow_id"
        :disabled="workflowLocked"
        placeholder="请选择工作流"
        :options="
          workflowOptions.map((s) => ({
            label: `${s.name} (${s.workflow_id})`,
            value: s.workflow_id,
          }))
        "
        @change="(val: string) => patch('workflow_id', val)"
      />
    </div>
    <div class="form-row">
      <label class="form-label">名称 *</label>
      <input
        class="form-input"
        type="text"
        :value="model.name"
        placeholder="例如：每天 8 点运行"
        @input="patch('name', ($event.target as HTMLInputElement).value)"
      />
    </div>
    <div class="form-row">
      <label class="form-label">触发类型</label>
      <div class="radio-group">
        <label class="radio-label">
          <input
            type="radio"
            value="cron"
            :checked="model.trigger_type === 'cron'"
            @change="patch('trigger_type', 'cron')"
          />
          <span>Cron 表达式</span>
        </label>
        <label class="radio-label">
          <input
            type="radio"
            value="interval"
            :checked="model.trigger_type === 'interval'"
            @change="patch('trigger_type', 'interval')"
          />
          <span>固定间隔</span>
        </label>
        <label class="radio-label">
          <input
            type="radio"
            value="event"
            :checked="model.trigger_type === 'event'"
            @change="patch('trigger_type', 'event')"
          />
          <span>事件触发</span>
        </label>
      </div>
    </div>
    <div v-if="model.trigger_type === 'cron'" class="form-row">
      <label class="form-label">
        Cron 表达式 *
        <span class="form-hint"
          >（5 字段：分 时 日 月 周；墙钟为北京时间，例如 "0 8 * * *" = 每天 08:00 北京）</span
        >
      </label>
      <div class="cron-presets">
        <button
          v-for="preset in cronPresets"
          :key="preset.expr"
          class="cron-preset-btn"
          type="button"
          :title="preset.description"
          @click="emit('applyCronPreset', preset.expr)"
        >
          {{ preset.label }}
        </button>
      </div>
      <input
        class="form-input mono"
        type="text"
        :value="model.cron_expr"
        placeholder="0 8 * * *"
        @input="patch('cron_expr', ($event.target as HTMLInputElement).value)"
      />
      <div v-if="cronPreviewError" class="cron-preview-error">
        <AlertTriangle :size="14" aria-hidden="true" /> {{ cronPreviewError }}
      </div>
      <div v-else-if="cronPreviewTimes.length > 0" class="cron-preview">
        <span class="cron-preview-label">{{ cronPreviewLoading ? '计算中...' : '下次触发:' }}</span>
        <div class="cron-preview-times">
          <code v-for="(t, i) in cronPreviewTimes" :key="i" class="cron-time-item">
            {{ formatTime(t) }}
          </code>
        </div>
      </div>
    </div>
    <div v-else-if="model.trigger_type === 'interval'" class="form-row">
      <label class="form-label">
        间隔秒数 * <span class="form-hint">（>= 60，例如 3600 = 每小时）</span>
      </label>
      <input
        class="form-input"
        type="number"
        min="60"
        step="60"
        :value="model.interval_seconds"
        @input="patch('interval_seconds', Number(($event.target as HTMLInputElement).value))"
      />
    </div>
    <div v-else class="form-row">
      <label class="form-label">
        事件类型 *
        <span class="form-hint">（例如 "data_ready"，调用 /workflow-timers/events 触发）</span>
      </label>
      <input
        class="form-input"
        type="text"
        :value="model.event_type"
        placeholder="data_ready"
        @input="patch('event_type', ($event.target as HTMLInputElement).value)"
      />
    </div>
    <div class="form-row">
      <label class="form-label">
        Payload Overrides (JSON)
        <span class="form-hint">（可选，覆盖默认 WorkflowSubmitRequest 字段）</span>
      </label>
      <div class="date-templates-bar">
        <button
          class="date-templates-toggle"
          type="button"
          @click="emit('update:showDateTemplates', !showDateTemplates)"
        >
          {{ showDateTemplates ? '▼' : '▶' }} 动态日期模板
        </button>
        <div v-if="showDateTemplates" class="date-templates-list">
          <button
            v-for="tpl in DATE_TEMPLATES"
            :key="tpl.key"
            class="date-template-btn"
            type="button"
            :title="tpl.description"
            @click="emit('insertDateTemplate', tpl.key)"
          >
            {{ tpl.label }}
          </button>
        </div>
      </div>
      <textarea
        class="form-input mono textarea"
        rows="5"
        :value="model.payload_overrides_json"
        placeholder='{"parameters": {"start_date": "{{today}}", "end_date": "{{yesterday}}"}}'
        @input="patch('payload_overrides_json', ($event.target as HTMLTextAreaElement).value)"
      />
    </div>
    <div class="form-row">
      <label class="form-label">
        <input
          type="checkbox"
          :checked="model.enabled"
          @change="patch('enabled', ($event.target as HTMLInputElement).checked)"
        />
        立即
      </label>
    </div>
    <div v-if="editorError" class="dialog-error">
      <XCircle :size="14" aria-hidden="true" /> {{ editorError }}
    </div>
    <div class="dialog-actions">
      <button class="dialog-btn cancel" type="button" @click="emit('cancel')">取消</button>
      <button
        class="dialog-btn primary"
        type="button"
        :disabled="editorSaving"
        @click="emit('save')"
      >
        {{ editorSaving ? '保存中...' : '保存' }}
      </button>
    </div>
  </div>
</template>

<style scoped>
.timer-editor-form {
  display: flex;
  flex-direction: column;
  gap: 0.72rem;
  min-height: 0;
}

.form-row {
  display: flex;
  flex-direction: column;
  gap: 0.28rem;
}

.form-label {
  font-size: var(--font-size-caption);
  color: var(--text-primary);
  font-weight: 500;
}

.form-hint {
  font-weight: 400;
  color: var(--text-muted);
  font-size: var(--font-size-caption);
}

.form-input {
  padding: 0.4rem 0.5rem;
  border-radius: 0.35rem;
  border: 1px solid var(--border-strong);
  background: var(--surface-1);
  color: var(--text-strong);
  font-size: var(--font-size-caption);
}

.form-input.mono,
.mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
}

.form-input.textarea {
  resize: vertical;
  min-height: 5rem;
}

.radio-group {
  display: flex;
  flex-wrap: wrap;
  gap: 0.72rem;
}

.radio-label {
  display: flex;
  align-items: center;
  gap: 0.28rem;
  font-size: var(--font-size-caption);
  color: var(--text-primary);
  cursor: pointer;
}

.cron-presets {
  display: flex;
  flex-wrap: wrap;
  gap: 0.28rem;
}

.cron-preset-btn {
  padding: 0.22rem 0.45rem;
  border-radius: 0.28rem;
  border: 1px solid var(--border-accent);
  background: var(--surface-1);
  color: var(--accent);
  font-size: var(--font-size-caption);
  cursor: pointer;
}

.cron-preset-btn:hover {
  border-color: var(--border-strong);
  color: var(--text-strong);
}

.cron-preview {
  display: flex;
  flex-direction: column;
  gap: 0.28rem;
  margin-top: 0.2rem;
}

.cron-preview-label {
  font-size: var(--font-size-caption);
  color: var(--text-muted);
}

.cron-preview-times {
  display: flex;
  flex-direction: column;
  gap: 0.18rem;
}

.cron-time-item {
  font-size: var(--font-size-caption);
  color: var(--text-secondary);
}

.cron-preview-error {
  font-size: var(--font-size-caption);
  color: var(--danger);
}

.date-templates-bar {
  display: flex;
  flex-direction: column;
  gap: 0.28rem;
}

.date-templates-toggle {
  align-self: flex-start;
  border: none;
  background: transparent;
  color: var(--accent);
  font-size: var(--font-size-caption);
  cursor: pointer;
  padding: 0;
}

.date-templates-list {
  display: flex;
  flex-wrap: wrap;
  gap: 0.28rem;
}

.date-template-btn {
  padding: 0.18rem 0.4rem;
  border-radius: 0.25rem;
  border: 1px solid var(--border-strong);
  background: var(--surface-1);
  color: var(--accent);
  font-size: var(--font-size-caption);
  cursor: pointer;
}

.dialog-error {
  color: var(--danger);
  font-size: var(--font-size-caption);
}

.dialog-actions {
  display: flex;
  justify-content: flex-end;
  gap: 0.4rem;
  margin-top: 0.4rem;
}

.dialog-btn {
  padding: 0.38rem 0.72rem;
  border-radius: 0.35rem;
  border: 1px solid var(--border-strong);
  background: var(--surface-2);
  color: var(--text-primary);
  font-size: var(--font-size-caption);
  cursor: pointer;
}

.dialog-btn.primary {
  border-color: var(--border-strong);
  background: var(--surface-3);
  color: var(--text-strong);
}

.dialog-btn.cancel:hover,
.dialog-btn.primary:hover {
  filter: brightness(1.08);
}

.dialog-btn:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}
</style>
