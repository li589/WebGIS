<script setup lang="ts">
/**
 * GldasNc4ToMatForm.vue
 *
 * download/gldas_nc4_to_mat 节点专用参数表单。
 */
import { computed, onMounted, reactive, watch } from 'vue'
import type { LGraphNodeClass } from '../litegraph-setup'
import { type FormErrors, syncFormFromNode, validateRequired } from './utils'
import {
  fillPathFieldsFromSystemSettings,
  loadSystemPathDefaults,
} from '../../../composables/system-settings-fill'
import { fieldMapForNodeType } from '../../../composables/node-form-system-settings-map'
import { WORKFLOW_COPY } from '../../../ui-copy/workflow'

const NODE_TYPE = 'download/gldas_nc4_to_mat'
const PATH_FIELD_MAP = fieldMapForNodeType(NODE_TYPE)

const props = defineProps<{
  node: LGraphNodeClass | null
  readonly?: boolean
}>()

const emit = defineEmits<{
  'update-property': [key: string, value: unknown]
}>()

const DEFAULTS = {
  input_dir: '',
  output_dir: '',
  ancillary_mat: '',
  dry_run: false,
  skip_existing: true,
  max_files: '',
}

const form = reactive<{ [k: string]: unknown }>({ ...DEFAULTS })
const errors = reactive<FormErrors>({})
const errorCount = computed(() => Object.keys(errors).length)

function validateForm() {
  const e: FormErrors = {}
  let r = validateRequired(form.input_dir, '输入目录')
  if (r) e.input_dir = r
  r = validateRequired(form.output_dir, '输出目录')
  if (r) e.output_dir = r
  for (const k of Object.keys(errors)) delete errors[k]
  Object.assign(errors, e)
}

function resync() {
  syncFormFromNode(form, props.node, DEFAULTS)
  validateForm()
}

watch(() => props.node, resync, { immediate: true })

onMounted(async () => {
  try {
    const defaults = await loadSystemPathDefaults()
    const filled = fillPathFieldsFromSystemSettings(form, defaults, PATH_FIELD_MAP, {
      onlyEmpty: true,
    })
    for (const key of filled) emit('update-property', key, form[key])
    validateForm()
  } catch {
    // ignore settings fetch failures
  }
})

async function applySystemSettings(overwrite = true) {
  const defaults = await loadSystemPathDefaults(true)
  const filled = fillPathFieldsFromSystemSettings(form, defaults, PATH_FIELD_MAP, { overwrite })
  for (const key of filled) emit('update-property', key, form[key])
  validateForm()
}

function update(key: string, value: unknown) {
  form[key] = value
  validateForm()
  emit('update-property', key, value)
}
</script>

<template>
  <div class="node-form">
    <div class="form-row">
      <label class="form-label">
        输入目录 input_dir
        <button
          v-if="!readonly"
          type="button"
          class="sys-fill-btn"
          :title="WORKFLOW_COPY.useSystemSettings"
          @click="applySystemSettings(true)"
        >
          {{ WORKFLOW_COPY.useSystemSettings }}
        </button>
      </label>
      <input
        type="text"
        class="form-input"
        :value="String(form.input_dir ?? '')"
        placeholder="GLDAS_Download 目录"
        :readonly="readonly"
        @input="update('input_dir', ($event.target as HTMLInputElement).value)"
      />
      <span v-if="errors.input_dir" class="field-error">{{ errors.input_dir }}</span>
    </div>

    <div class="form-row">
      <label class="form-label">输出目录 output_dir</label>
      <input
        type="text"
        class="form-input"
        :value="String(form.output_dir ?? '')"
        placeholder="GLDAS .mat 输出目录"
        :readonly="readonly"
        @input="update('output_dir', ($event.target as HTMLInputElement).value)"
      />
      <span v-if="errors.output_dir" class="field-error">{{ errors.output_dir }}</span>
    </div>

    <div class="form-row">
      <label class="form-label">辅助网格 ancillary_mat（可选）</label>
      <input
        type="text"
        class="form-input"
        :value="String(form.ancillary_mat ?? '')"
        placeholder="默认使用 anc_root/IGBP_9km_12.mat"
        :readonly="readonly"
        @input="update('ancillary_mat', ($event.target as HTMLInputElement).value)"
      />
    </div>

    <div class="form-row">
      <label class="form-label">max_files（可选）</label>
      <input
        type="number"
        class="form-input"
        :value="form.max_files === '' || form.max_files == null ? '' : Number(form.max_files)"
        placeholder="联调节流"
        :readonly="readonly"
        @input="
          update(
            'max_files',
            ($event.target as HTMLInputElement).value
              ? Number(($event.target as HTMLInputElement).value)
              : null,
          )
        "
      />
    </div>

    <div class="form-row form-row-check">
      <label class="form-check">
        <input
          type="checkbox"
          :checked="Boolean(form.skip_existing)"
          :disabled="readonly"
          @change="update('skip_existing', ($event.target as HTMLInputElement).checked)"
        />
        skip_existing（跳过已存在 .mat）
      </label>
    </div>

    <div class="form-row form-row-check">
      <label class="form-check">
        <input
          type="checkbox"
          :checked="Boolean(form.dry_run)"
          :disabled="readonly"
          @change="update('dry_run', ($event.target as HTMLInputElement).checked)"
        />
        dry_run（仅统计，不写文件）
      </label>
    </div>

    <div class="form-summary" :class="{ valid: errorCount === 0, invalid: errorCount > 0 }">
      <template v-if="errorCount === 0">✓ 表单校验通过</template>
      <template v-else>⚠ 请修正 {{ errorCount }} 处错误</template>
    </div>
  </div>
</template>

<style scoped>
.node-form {
  display: flex;
  flex-direction: column;
  gap: 0.1rem;
}

.form-row {
  display: flex;
  flex-direction: column;
  gap: 0.18rem;
  margin-bottom: 0.42rem;
}

.form-row-check {
  margin-top: 0.1rem;
}

.form-check {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  font-size: 0.56rem;
  color: #d8e6f5;
}

.form-label {
  font-size: 0.56rem;
  color: #6e8ba0;
  font-weight: 500;
}

.form-input {
  width: 100%;
  padding: 0.32rem 0.42rem;
  border: 1px solid rgba(136, 192, 255, 0.14);
  border-radius: 0.36rem;
  background: rgba(4, 12, 23, 0.6);
  color: #d8e6f5;
  font: inherit;
  font-size: 0.6rem;
  box-sizing: border-box;
}

.form-input:focus {
  outline: none;
  border-color: rgba(90, 213, 255, 0.4);
}

.form-input:read-only {
  background: rgba(4, 12, 23, 0.3);
  color: #6e8ba0;
  cursor: default;
}

.field-error {
  font-size: 0.52rem;
  color: #ff7b7b;
  margin-top: 0.06rem;
  line-height: 1.3;
}

.form-summary {
  margin-top: 0.32rem;
  padding: 0.3rem 0.52rem;
  border-radius: 0.36rem;
  font-size: 0.56rem;
  text-align: center;
  border: 1px solid transparent;
}

.form-summary.valid {
  background: rgba(114, 255, 207, 0.08);
  color: #72ffcf;
  border-color: rgba(114, 255, 207, 0.22);
}

.form-summary.invalid {
  background: rgba(255, 123, 123, 0.08);
  color: #ff7b7b;
  border-color: rgba(255, 123, 123, 0.22);
}
</style>
