<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useLogStore } from '../../stores/log'
import { fetchCrsOptions } from '../../services/data-import'
import { transformPoint, type CRSOption } from '@/services/crs'

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
/** handleConfirm 中转换失败的行数（per-row try/catch 容错） */
const failedCount = ref(0)

const CRS_OPTIONS = ref<CRSOption[]>([])

// 拉取后端 13 项 CRS 选项（含 GCJ02/BD09/4258/6933/3034 等）
onMounted(async () => {
  try {
    const data = await fetchCrsOptions()
    CRS_OPTIONS.value = data.items
  } catch (err) {
    console.warn('[CsvImport] fetchCrsOptions 失败，下拉列表为空', err)
  }
})

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
    const xGuess = cols.find((_c, i) => xCandidates.includes(lowerCols[i]))
    const yGuess = cols.find((_c, i) => yCandidates.includes(lowerCols[i]))
    xCol.value = xGuess ?? cols[0]
    yCol.value = yGuess ?? cols[1] ?? cols[0]
  } catch (err) {
    parseError.value = err instanceof Error ? err.message : String(err)
  }
}

watch(() => props.file, () => { void parseCsv() }, { immediate: true })

// 同步点转换：调 services/crs 的 transformPoint（proj4 静态 import，加密系走 gcj-bd.ts）
function _convertPoint(x: number, y: number): [number, number] {
  return transformPoint(x, y, crs.value, 'EPSG:4326')
}

// 预览转换后的坐标（transformPoint 同步，用 computed 即可）
const previewCoords = computed<Array<[number, number] | null>>(() => {
  if (!xCol.value || !yCol.value) return []
  return previewRows.value.map((row) => {
    const x = parseFloat(row[xCol.value])
    const y = parseFloat(row[yCol.value])
    if (!Number.isFinite(x) || !Number.isFinite(y)) return null
    if (crs.value === 'EPSG:4326') return [x, y]
    try {
      return _convertPoint(x, y)
    } catch {
      return [x, y]
    }
  })
})

const canConfirm = computed(() => !!xCol.value && !!yCol.value && allRows.value.length > 0 && !parseError.value && !converting.value)

async function handleConfirm() {
  if (!canConfirm.value) return
  converting.value = true
  failedCount.value = 0
  try {
    const features: GeoJSON.Feature[] = []
    for (let i = 0; i < allRows.value.length; i++) {
      const row = allRows.value[i]
      const x = parseFloat(row[xCol.value])
      const y = parseFloat(row[yCol.value])
      if (!Number.isFinite(x) || !Number.isFinite(y)) continue
      let coord: [number, number]
      if (crs.value === 'EPSG:4326') {
        coord = [x, y]
      } else {
        // per-row 容错：单行 proj4 异常不杀死整批导入，跳过该行并计数
        // 与 previewCoords computed 的 try/catch + fallback 行为一致
        try {
          coord = _convertPoint(x, y)
        } catch (err) {
          failedCount.value++
          if (failedCount.value === 1) {
            // 只记录第一行失败的详细信息（避免日志爆炸）
            console.warn(`[CsvImport] 第 ${i + 1} 行转换失败:`, err, { x, y, crs: crs.value })
          }
          continue
        }
      }
      features.push({
        type: 'Feature',
        geometry: { type: 'Point', coordinates: coord },
        properties: { ...row },
      })
      // 每 500 行 yield 一次，避免大 CSV 阻塞 UI
      if (i > 0 && i % 500 === 0) await Promise.resolve()
    }

    const geojson: GeoJSON.FeatureCollection = {
      type: 'FeatureCollection',
      features,
    }

    const name = props.file.name.replace(/\.csv$/i, '')
    emit('confirm', geojson, name)
    const detailParts = [`点数: ${features.length}`, `坐标系: ${crs.value}`]
    if (failedCount.value > 0) detailParts.push(`跳过失败行: ${failedCount.value}`)
    logStore.logOperation('import-csv-success', `CSV 导入成功: ${name}`, detailParts.join(', '))
    if (failedCount.value > 0) {
      logStore.logOperation(
        'import-csv-warn',
        `CSV 部分行转换失败: ${name}`,
        `跳过 ${failedCount.value} 行（CRS: ${crs.value} 转换异常），已导入 ${features.length} 个点`,
      )
    }
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
              <option v-for="opt in CRS_OPTIONS" :key="opt.code" :value="opt.code">{{ opt.label }}</option>
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
                <td class="coord-cell">{{ formatCoord(previewCoords[i] ?? null) }}</td>
                <td v-for="col in columns.filter(c => c !== xCol && c !== yCol).slice(0, 3)" :key="col">{{ row[col] }}</td>
              </tr>
            </tbody>
          </table>
        </div>

        <div class="info-row">
          <span>共 {{ allRows.length }} 行数据</span>
          <span v-if="crs !== 'EPSG:4326'" class="convert-hint">将从 {{ crs }} 转换为 WGS84</span>
          <span v-if="failedCount > 0" class="failed-hint">⚠ {{ failedCount }} 行转换失败已跳过</span>
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
.failed-hint { color: #ffb070; }

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
