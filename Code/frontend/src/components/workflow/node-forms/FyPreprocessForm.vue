<script setup lang="ts">
/**
 * FyPreprocessForm.vue
 *
 * download/fy_preprocess 节点专用参数表单。
 *
 * 字段：
 *   - satellite: FY3D / FY3B
 *   - input_dir / output_dir: 输入 / 输出目录
 *   - start_date / end_date: YYYYMMDD
 *   - orbit_mode: MWRID / MWRIA / Both
 *   - outfile_type: HDF5 / NetCDF / GTiff
 */
import { computed, onMounted, reactive, watch } from 'vue'
import type { LGraphNodeClass } from '../litegraph-setup'
import {
  type FormErrors,
  isoToYyyymmdd,
  syncFormFromNode,
  validateDateRange,
  validateRequired,
  yyyymmddToIso,
} from './utils'
import {
  fillPathFieldsFromSystemSettings,
  loadSystemPathDefaults,
} from '../../../composables/system-settings-fill'
import { fieldMapForNodeType } from '../../../composables/node-form-system-settings-map'
import { WORKFLOW_COPY } from '../../../ui-copy/workflow'

const NODE_TYPE = 'download/fy_preprocess'
const PATH_FIELD_MAP = fieldMapForNodeType(NODE_TYPE)

const props = defineProps<{
  node: LGraphNodeClass | null
  readonly?: boolean
}>()

const emit = defineEmits<{
  'update-property': [key: string, value: unknown]
}>()

const DEFAULTS = {
  satellite: 'FY3D',
  input_dir: '',
  output_dir: '',
  start_date: '',
  end_date: '',
  orbit_mode: 'MWRID',
  outfile_type: 'HDF5',
}

const form = reactive<{ [k: string]: unknown }>({ ...DEFAULTS })

// 表单校验错误集合（实时更新）
const errors = reactive<FormErrors>({})
const errorCount = computed(() => Object.keys(errors).length)

/**
 * 实时校验：satellite / input_dir / output_dir 非空 + 日期范围合法。
 * 结果写入 reactive errors，驱动模板中的字段错误提示与底部摘要。
 */
function validateForm() {
  const e: FormErrors = {}
  let r = validateRequired(form.satellite, '卫星')
  if (r) e.satellite = r
  r = validateRequired(form.input_dir, '输入目录')
  if (r) e.input_dir = r
  r = validateRequired(form.output_dir, '输出目录')
  if (r) e.output_dir = r
  r = validateDateRange(String(form.start_date ?? ''), String(form.end_date ?? ''))
  if (r) e.date_range = r
  // 先清空再赋值，确保响应式触发
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
    for (const key of filled) {
      emit('update-property', key, form[key])
    }
    validateForm()
  } catch {
    /* ignore settings fetch errors */
  }
})

async function applySystemSettings(overwrite = true) {
  const defaults = await loadSystemPathDefaults(true)
  const filled = fillPathFieldsFromSystemSettings(form, defaults, PATH_FIELD_MAP, { overwrite })
  for (const key of filled) {
    emit('update-property', key, form[key])
  }
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
    <!-- 卫星 -->
    <div class="form-row">
      <label class="form-label">卫星 satellite</label>
      <select
        class="form-input form-select"
        :value="String(form.satellite ?? 'FY3D')"
        :disabled="readonly"
        @change="update('satellite', ($event.target as HTMLSelectElement).value)"
      >
        <option value="FY3D">FY3D</option>
        <option value="FY3B">FY3B</option>
      </select>
      <span v-if="errors.satellite" class="field-error">{{ errors.satellite }}</span>
    </div>

    <!-- 轨道模式 -->
    <div class="form-row">
      <label class="form-label">轨道模式 orbit_mode</label>
      <select
        class="form-input form-select"
        :value="String(form.orbit_mode ?? 'MWRID')"
        :disabled="readonly"
        @change="update('orbit_mode', ($event.target as HTMLSelectElement).value)"
      >
        <option value="MWRID">MWRID</option>
        <option value="MWRIA">MWRIA</option>
        <option value="Both">Both</option>
      </select>
    </div>

    <!-- 输出文件类型 -->
    <div class="form-row">
      <label class="form-label">输出类型 outfile_type</label>
      <select
        class="form-input form-select"
        :value="String(form.outfile_type ?? 'HDF5')"
        :disabled="readonly"
        @change="update('outfile_type', ($event.target as HTMLSelectElement).value)"
      >
        <option value="HDF5">HDF5</option>
        <option value="NetCDF">NetCDF</option>
        <option value="GTiff">GTiff</option>
      </select>
    </div>

    <!-- 输入目录 -->
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
        placeholder="输入数据所在目录"
        :readonly="readonly"
        @input="update('input_dir', ($event.target as HTMLInputElement).value)"
      />
      <span v-if="errors.input_dir" class="field-error">{{ errors.input_dir }}</span>
    </div>

    <!-- 输出目录 -->
    <div class="form-row">
      <label class="form-label">输出目录 output_dir</label>
      <input
        type="text"
        class="form-input"
        :value="String(form.output_dir ?? '')"
        placeholder="预处理结果输出目录"
        :readonly="readonly"
        @input="update('output_dir', ($event.target as HTMLInputElement).value)"
      />
      <span v-if="errors.output_dir" class="field-error">{{ errors.output_dir }}</span>
    </div>

    <!-- 日期范围 -->
    <div class="form-row">
      <label class="form-label">起始日期 start_date</label>
      <input
        type="date"
        class="form-input"
        :value="yyyymmddToIso(form.start_date)"
        :readonly="readonly"
        @input="update('start_date', isoToYyyymmdd(($event.target as HTMLInputElement).value))"
      />
    </div>

    <div class="form-row">
      <label class="form-label">结束日期 end_date</label>
      <input
        type="date"
        class="form-input"
        :value="yyyymmddToIso(form.end_date)"
        :readonly="readonly"
        @input="update('end_date', isoToYyyymmdd(($event.target as HTMLInputElement).value))"
      />
      <span v-if="errors.date_range" class="field-error">{{ errors.date_range }}</span>
    </div>

    <!-- 校验状态摘要 -->
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

.form-select {
  appearance: none;
  cursor: pointer;
  background-image:
    linear-gradient(45deg, transparent 50%, #6e8ba0 50%),
    linear-gradient(135deg, #6e8ba0 50%, transparent 50%);
  background-position:
    calc(100% - 0.8rem) center,
    calc(100% - 0.5rem) center;
  background-size:
    0.3rem 0.3rem,
    0.3rem 0.3rem;
  background-repeat: no-repeat;
  padding-right: 1.6rem;
}

.form-select:disabled {
  opacity: 0.6;
  cursor: default;
}

/* 字段错误提示 */
.field-error {
  font-size: 0.52rem;
  color: #ff7b7b;
  margin-top: 0.06rem;
  line-height: 1.3;
}

/* 校验状态摘要 */
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

.sys-fill-btn {
  margin-left: 0.4rem;
  font-size: 0.5rem;
  padding: 0.1rem 0.35rem;
  border-radius: 0.25rem;
  border: 1px solid rgba(90, 213, 255, 0.35);
  background: rgba(90, 213, 255, 0.08);
  color: #88dfff;
  cursor: pointer;
}
</style>
