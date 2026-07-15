<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useLogStore } from '../../stores/log'

const props = defineProps<{
  file: File
}>()

const emit = defineEmits<{
  close: []
  confirm: [geojson: GeoJSON.FeatureCollection, name: string]
}>()

const logStore = useLogStore()

interface CsvRow {
  [key: string]: string
}

const columns = ref<string[]>([])
const previewRows = ref<CsvRow[]>([])
const allRows = ref<CsvRow[]>([])
const xCol = ref('')
const yCol = ref('')
const crs = ref('EPSG:4326')
const parseError = ref('')
const converting = ref(false)

const CRS_OPTIONS = [
  { value: 'EPSG:4326', label: 'EPSG:4326 (WGS84 经纬度)' },
  { value: 'EPSG:3857', label: 'EPSG:3857 (Web Mercator)' },
  { value: 'EPSG:32649', label: 'EPSG:32649 (UTM 49N)' },
  { value: 'EPSG:32650', label: 'EPSG:32650 (UTM 50N)' },
  { value: 'EPSG:4490', label: 'EPSG:4490 (CGCS2000)' },
  { value: 'EPSG:4527', label: 'EPSG:4527 (CGCS2000 / 3-degree Gauss 117E)' },
  { value: 'EPSG:4528', label: 'EPSG:4528 (CGCS2000 / 3-degree Gauss 120E)' },
  { value: 'EPSG:4529', label: 'EPSG:4529 (CGCS2000 / 3-degree Gauss 123E)' },
]

// 解析 CSV
async function parseCsv() {
  parseError.value = ''
  try {
    const Papa = (await import('papaparse')).default
    const text = await props.file.text()
    const result = Papa.parse<CsvRow>(text, {
      header: true,
      skipEmptyLines: true,
      dynamicTyping: false,
    })

    if (result.errors.length > 0) {
      console.warn('[CsvImport] Parse warnings:', result.errors)
    }

    const data = result.data
    if (!data || data.length === 0) {
      parseError.value = 'CSV 文件为空或无数据行'
      return
    }

    const cols = result.meta.fields ?? Object.keys(data[0])
    if (cols.length === 0) {
      parseError.value = '未能识别列名，请确认 CSV 第一行为表头'
      return
    }

    columns.value = cols
    previewRows.value = data.slice(0, 5)
    allRows.value = data

    // 自动猜测 XY 列（常见列名）
    const xCandidates = ['lng', 'lon', 'long', 'longitude', 'x', '经度', '东经']
    const yCandidates = ['lat', 'latitude', 'y', '纬度', '北纬']
    const lowerCols = cols.map((c) => c.toLowerCase())
    const xGuess = cols.find((c, i) => xCandidates.includes(lowerCols[i]))
    const yGuess = cols.find((c, i) => yCandidates.includes(lowerCols[i]))
    xCol.value = xGuess ?? cols[0]
    yCol.value = yGuess ?? cols[1] ?? cols[0]
  } catch (err) {
    parseError.value = err instanceof Error ? err.message : String(err)
  }
}

watch(() => props.file, () => { void parseCsv() }, { immediate: true })

let _proj4Lib: typeof import('proj4')['default'] | null = null
async function _ensureProj4() {
  if (!_proj4Lib) {
    _proj4Lib = (await import('proj4')).default
  }
  return _proj4Lib
}

async function _proj4Convert(x: number, y: number): Promise<[number, number]> {
  const proj4 = await _ensureProj4()
  return proj4(crs.value, 'EPSG:4326', [x, y])
}

// 预览转换后的坐标（proj4 转换是异步的，使用异步预览）
const previewCoordsAsync = ref<Array<[number, number] | null>>([])
watch([previewRows, xCol, yCol, crs], async () => {
  if (!xCol.value || !yCol.value) {
    previewCoordsAsync.value = []
    return
  }
  const results: Array<[number, number] | null> = []
  for (const row of previewRows.value) {
    const x = parseFloat(row[xCol.value])
    const y = parseFloat(row[yCol.value])
    if (!Number.isFinite(x) || !Number.isFinite(y)) {
      results.push(null)
      continue
    }
    if (crs.value === 'EPSG:4326') {
      results.push([x, y])
    } else {
      try {
        results.push(await _proj4Convert(x, y))
      } catch {
        results.push([x, y])
      }
    }
  }
  previewCoordsAsync.value = results
}, { immediate: true })

const canConfirm = computed(() => !!xCol.value && !!yCol.value && allRows.value.length > 0 && !parseError.value && !converting.value)

async function handleConfirm() {
  if (!canConfirm.value) return
  converting.value = true
  try {
    const features: GeoJSON.Feature[] = []
    for (const row of allRows.value) {
      const x = parseFloat(row[xCol.value])
      const y = parseFloat(row[yCol.value])
      if (!Number.isFinite(x) || !Number.isFinite(y)) continue
      let coord: [number, number]
      if (crs.value === 'EPSG:4326') {
        coord = [x, y]
      } else {
        coord = await _proj4Convert(x, y)
      }
      features.push({
        type: 'Feature',
        geometry: { type: 'Point', coordinates: coord },
        properties: { ...row },
      })
    }

    const geojson: GeoJSON.FeatureCollection = {
      type: 'FeatureCollection',
      features,
    }

    const name = props.file.name.replace(/\.csv$/i, '')
    emit('confirm', geojson, name)
    logStore.logOperation('import-csv-success', `CSV 导入成功: ${name}`, `点数: ${features.length}, 坐标系: ${crs.value}`)
  } catch (err) {
    logStore.logOperation('import-csv-fail', `CSV 导入失败: ${props.file.name}`, err instanceof Error ? err.message : String(err))
  } finally {
    converting.value = false
  }
}

function formatCoord(c: [number, number] | null): string {
  if (!c) return '—'
  return `${c[0].toFixed(4)}, ${c[1].toFixed(4)}`
}
</script>

<template>
  <div class="csv-dialog-overlay" @click.self="emit('close')">
    <div class="csv-dialog-panel">
      <div class="panel-header">
        <span class="panel-icon" aria-hidden="true">📊</span>
        <span>导入 CSV: {{ file.name }}</span>
        <button class="close-btn" @click="emit('close')" title="关闭">
          <span aria-hidden="true">✕</span>
        </button>
      </div>

      <div v-if="parseError" class="error-banner">
        ⚠ {{ parseError }}
      </div>

      <template v-else>
        <!-- 列选择 -->
        <div class="section-label">坐标列选择</div>
        <div class="col-row">
          <label class="col-field">
            <span class="col-label">X（经度）</span>
            <select v-model="xCol" class="col-select">
              <option v-for="col in columns" :key="col" :value="col">{{ col }}</option>
            </select>
          </label>
          <label class="col-field">
            <span class="col-label">Y（纬度）</span>
            <select v-model="yCol" class="col-select">
              <option v-for="col in columns" :key="col" :value="col">{{ col }}</option>
            </select>
          </label>
          <label class="col-field">
            <span class="col-label">坐标系</span>
            <select v-model="crs" class="col-select crs-select">
              <option v-for="opt in CRS_OPTIONS" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
            </select>
          </label>
        </div>

        <!-- 预览表 -->
        <div class="section-label">数据预览（前 5 行，转换后坐标）</div>
        <div class="preview-table-wrap">
          <table class="preview-table">
            <thead>
              <tr>
                <th>#</th>
                <th>{{ xCol }}</th>
                <th>{{ yCol }}</th>
                <th>转换后 (WGS84)</th>
                <th v-for="col in columns.filter(c => c !== xCol && c !== yCol).slice(0, 3)" :key="col">{{ col }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(row, i) in previewRows" :key="i">
                <td class="row-num">{{ i + 1 }}</td>
                <td>{{ row[xCol] }}</td>
                <td>{{ row[yCol] }}</td>
                <td class="coord-cell">{{ formatCoord(previewCoordsAsync[i] ?? null) }}</td>
                <td v-for="col in columns.filter(c => c !== xCol && c !== yCol).slice(0, 3)" :key="col">{{ row[col] }}</td>
              </tr>
            </tbody>
          </table>
        </div>

        <div class="info-row">
          <span>共 {{ allRows.length }} 行数据</span>
          <span v-if="crs !== 'EPSG:4326'" class="convert-hint">将从 {{ crs }} 转换为 WGS84</span>
        </div>

        <!-- 操作按钮 -->
        <div class="action-row">
          <button class="cancel-btn" @click="emit('close')">取消</button>
          <button class="confirm-btn" :disabled="!canConfirm" @click="handleConfirm">
            <span v-if="converting" class="spinning" aria-hidden="true">↻</span>
            {{ converting ? '转换中...' : `确认导入 (${allRows.length} 点)` }}
          </button>
        </div>
      </template>
    </div>
  </div>
</template>

<style scoped>
.csv-dialog-overlay {
  position: fixed;
  inset: 0;
  z-index: 999;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(4, 10, 18, 0.52);
}

.csv-dialog-panel {
  width: 32rem;
  max-width: 92vw;
  max-height: 86vh;
  display: flex;
  flex-direction: column;
  gap: 0.6rem;
  padding: 0.82rem;
  border-radius: 1rem;
  border: 1px solid rgba(136, 192, 255, 0.14);
  background: rgba(8, 17, 31, 0.96);
  box-shadow: 0 24px 60px rgba(1, 8, 16, 0.48);
  overflow: hidden;
}

.panel-header {
  display: flex;
  align-items: center;
  gap: 0.38rem;
  padding-bottom: 0.48rem;
  border-bottom: 1px solid rgba(136, 192, 255, 0.1);
  color: #e8f3fc;
  font-size: 0.72rem;
  font-weight: 600;
}

.panel-icon { font-size: 0.8rem; color: #5ad5ff; }

.close-btn {
  margin-left: auto;
  width: 1.4rem;
  height: 1.4rem;
  border: none;
  border-radius: 0.5rem;
  background: transparent;
  color: #6e8ba0;
  cursor: pointer;
  font-size: 0.7rem;
}
.close-btn:hover { background: rgba(136, 192, 255, 0.1); color: #d8e6f5; }

.section-label {
  color: #5a7080;
  font-size: 0.58rem;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}

.col-row {
  display: flex;
  gap: 0.52rem;
  flex-wrap: wrap;
}

.col-field {
  display: flex;
  flex-direction: column;
  gap: 0.22rem;
  flex: 1;
  min-width: 7rem;
}

.crs-select { flex: 1.4; }

.col-label {
  color: #8aa8bf;
  font-size: 0.56rem;
}

.col-select {
  padding: 0.32rem 0.42rem;
  border-radius: 0.42rem;
  border: 1px solid rgba(136, 192, 255, 0.16);
  background: rgba(4, 12, 23, 0.6);
  color: #d8e6f5;
  font: inherit;
  font-size: 0.62rem;
  cursor: pointer;
}

.col-select:focus {
  outline: none;
  border-color: rgba(90, 213, 255, 0.36);
}

.preview-table-wrap {
  overflow: auto;
  max-height: 14rem;
  border-radius: 0.5rem;
  border: 1px solid rgba(136, 192, 255, 0.1);
}

.preview-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.56rem;
}

.preview-table th {
  position: sticky;
  top: 0;
  padding: 0.32rem 0.42rem;
  background: rgba(12, 26, 44, 0.96);
  color: #88dfff;
  text-align: left;
  font-weight: 600;
  white-space: nowrap;
  border-bottom: 1px solid rgba(136, 192, 255, 0.14);
}

.preview-table td {
  padding: 0.26rem 0.42rem;
  color: #9fb6cc;
  border-bottom: 1px solid rgba(136, 192, 255, 0.06);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 7rem;
}

.preview-table tr:hover td { background: rgba(136, 192, 255, 0.04); }

.row-num { color: #5a7080; text-align: right; }
.coord-cell { color: #5ad5ff; font-variant-numeric: tabular-nums; }

.info-row {
  display: flex;
  gap: 0.8rem;
  color: #7f96ab;
  font-size: 0.56rem;
}

.convert-hint { color: #ffc878; }

.action-row {
  display: flex;
  gap: 0.52rem;
  justify-content: flex-end;
  padding-top: 0.32rem;
  border-top: 1px solid rgba(136, 192, 255, 0.08);
}

.cancel-btn {
  padding: 0.42rem 0.72rem;
  border: 1px solid rgba(136, 192, 255, 0.16);
  border-radius: 0.5rem;
  background: transparent;
  color: #9fb6cc;
  cursor: pointer;
  font: inherit;
  font-size: 0.64rem;
}
.cancel-btn:hover { background: rgba(136, 192, 255, 0.08); color: #d8e6f5; }

.confirm-btn {
  padding: 0.42rem 0.72rem;
  border: 1px solid rgba(90, 213, 255, 0.3);
  border-radius: 0.5rem;
  background: rgba(10, 132, 255, 0.28);
  color: #a8e8ff;
  cursor: pointer;
  font: inherit;
  font-size: 0.64rem;
  font-weight: 600;
}
.confirm-btn:hover:not(:disabled) { background: rgba(10, 132, 255, 0.48); color: #d0f0ff; }
.confirm-btn:disabled { opacity: 0.5; cursor: not-allowed; }

.spinning { display: inline-block; animation: spin 0.8s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }

.error-banner {
  padding: 0.52rem;
  border-radius: 0.5rem;
  background: rgba(255, 77, 77, 0.12);
  border: 1px solid rgba(255, 100, 100, 0.24);
  color: #ffb0b0;
  font-size: 0.62rem;
}
</style>
