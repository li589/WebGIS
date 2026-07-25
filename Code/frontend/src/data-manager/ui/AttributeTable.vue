<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import {
  addLayerField,
  batchSetFeatureAttribute,
  deleteLayerField,
  fetchImportedLayerFeatures,
  fetchImportedLayerMeta,
  patchFeatureAttribute,
  renameImportedLayerField,
} from '../core/api'
import {
  attrCellTitle,
  describeSourceEncoding,
  formatAttrCell,
  sanitizeFieldName,
  sanitizeSafeText,
} from '../core/attr-display'
import {
  dataWorkspaceHighlight,
  dataWorkspaceLayerId,
  dataWorkspaceMaximized,
  dataWorkspaceSelection,
  openDataWorkspace,
  showToast,
} from '../core/workspace-store'
import { useLayersStore } from '../../stores/layers'
import { DATA_COPY } from '../../ui-copy'

const layersStore = useLayersStore()

const pageSize = 80
const offset = ref(0)
const total = ref(0)
const features = ref<GeoJSON.Feature[]>([])
const absIndexes = ref<number[]>([])
const schemaFields = ref<string[]>([])
const encodingBadge = ref('')
const loading = ref(false)
const error = ref('')
const filterField = ref('')
const filterContains = ref('')
const whereExpr = ref('')
const sortField = ref('')
const sortDesc = ref(false)
const renameFrom = ref('')
const renameTo = ref('')
const newFieldName = ref('')
const selectedAbs = ref<Set<number>>(new Set())
const lastClickedAbs = ref<number | null>(null)
const editing = ref<{ absIndex: number; field: string; value: string } | null>(null)
const batchField = ref('')
const batchValue = ref('')
const tableBodyEl = ref<HTMLElement | null>(null)
const colWidths = ref<Record<string, number>>({})
const ctxMenu = ref<{ x: number; y: number; abs: number; field: string; value: unknown } | null>(
  null,
)

const importedVectors = computed(() =>
  layersStore.activeLayers.filter((l) => l.importedVector?.backendLayerId),
)

const selectedLayer = computed(() => {
  const id = dataWorkspaceLayerId.value
  if (!id) return importedVectors.value[0] ?? null
  return importedVectors.value.find((l) => l.instanceId === id) ?? importedVectors.value[0] ?? null
})

const backendId = computed(() => selectedLayer.value?.importedVector?.backendLayerId ?? null)

const columns = computed(() =>
  schemaFields.value.length
    ? schemaFields.value
    : (() => {
        const keys = new Set<string>()
        for (const f of features.value) {
          for (const k of Object.keys(f.properties || {})) keys.add(k)
        }
        return Array.from(keys)
      })(),
)

const page = computed(() => Math.floor(offset.value / pageSize) + 1)
const pageCount = computed(() => Math.max(1, Math.ceil(total.value / pageSize)))

/** 当前页全部行（分页已限制在 80，避免用 table 假高度做虚拟列表） */
const rows = computed(() =>
  features.value.map((feat, local) => ({
    feat,
    local,
    abs: absIndexes.value[local] ?? offset.value + local,
  })),
)

watch(
  () => selectedLayer.value?.instanceId,
  (id) => {
    if (id) dataWorkspaceLayerId.value = id
    offset.value = 0
    const hl = dataWorkspaceHighlight.value
    if (hl && hl.instanceId === id && hl.featureIndex != null) {
      // 地图点选已写入高亮：换层时保留并落到对应行
      selectedAbs.value = new Set([hl.featureIndex])
      lastClickedAbs.value = hl.featureIndex
      const targetOffset = Math.floor(hl.featureIndex / pageSize) * pageSize
      offset.value = targetOffset
    } else {
      selectedAbs.value = new Set()
      lastClickedAbs.value = null
      dataWorkspaceHighlight.value = null
      dataWorkspaceSelection.value = null
    }
    void loadMetaAndRows()
  },
  { immediate: true },
)

watch(dataWorkspaceHighlight, async (hl) => {
  if (!hl || !selectedLayer.value || hl.instanceId !== selectedLayer.value.instanceId) return
  if (hl.featureIndex == null) return
  const fi = hl.featureIndex
  const targetOffset = Math.floor(fi / pageSize) * pageSize
  if (offset.value !== targetOffset) {
    offset.value = targetOffset
    await load()
  }
  selectedAbs.value = new Set([fi])
  lastClickedAbs.value = fi
  await nextTick()
  const row = tableBodyEl.value?.querySelector(`tr[data-abs="${fi}"]`) as HTMLElement | null
  row?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
})

watch(dataWorkspaceMaximized, async () => {
  await nextTick()
  if (tableBodyEl.value) {
    // 触发重排以重新计算滚动区域（最大化切换后布局变化）
    void tableBodyEl.value.offsetHeight
  }
})

onMounted(() => {
  if (!dataWorkspaceLayerId.value && importedVectors.value[0]) {
    dataWorkspaceLayerId.value = importedVectors.value[0].instanceId
  }
})

async function loadMetaAndRows() {
  if (!backendId.value) {
    features.value = []
    total.value = 0
    schemaFields.value = []
    return
  }
  try {
    const meta = await fetchImportedLayerMeta(backendId.value)
    if (Array.isArray(meta.fields) && meta.fields.length) {
      schemaFields.value = meta.fields.map(String)
    }
    encodingBadge.value = describeSourceEncoding(meta) || DATA_COPY.attrEncodingUnknown
  } catch {
    encodingBadge.value = ''
  }
  await load()
}

function cellText(value: unknown): string {
  return formatAttrCell(value)
}

function cellTitle(value: unknown): string {
  return attrCellTitle(value)
}

async function load() {
  if (!backendId.value) {
    features.value = []
    total.value = 0
    return
  }
  loading.value = true
  error.value = ''
  try {
    const sort =
      sortField.value.trim() !== ''
        ? `${sortDesc.value ? '-' : ''}${sortField.value.trim()}`
        : undefined
    const whereParts: string[] = []
    if (filterField.value && filterContains.value) {
      whereParts.push(`${filterField.value} contains ${filterContains.value}`)
    }
    if (whereExpr.value.trim()) whereParts.push(whereExpr.value.trim())
    const res = await fetchImportedLayerFeatures(backendId.value, {
      limit: pageSize,
      offset: offset.value,
      sort,
      where: whereParts.length ? whereParts.join(';') : undefined,
    })
    features.value = res.features || []
    absIndexes.value = res.indexes ?? features.value.map((_, i) => offset.value + i)
    total.value = res.total ?? 0
    if (Array.isArray(res.fields) && res.fields.length) {
      schemaFields.value = res.fields
    }
    await nextTick()
    if (tableBodyEl.value) tableBodyEl.value.scrollTop = 0
    const hl = dataWorkspaceHighlight.value
    if (
      hl &&
      selectedLayer.value &&
      hl.instanceId === selectedLayer.value.instanceId &&
      hl.featureIndex != null
    ) {
      selectedAbs.value = new Set([hl.featureIndex])
      lastClickedAbs.value = hl.featureIndex
      await nextTick()
      const row = tableBodyEl.value?.querySelector(
        `tr[data-abs="${hl.featureIndex}"]`,
      ) as HTMLElement | null
      row?.scrollIntoView({ block: 'nearest' })
    }
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
    features.value = []
  } finally {
    loading.value = false
  }
}

function onSelectLayer(e: Event) {
  const v = (e.target as HTMLSelectElement).value
  dataWorkspaceLayerId.value = v || null
}

function prevPage() {
  if (offset.value <= 0) return
  offset.value = Math.max(0, offset.value - pageSize)
  void load()
}

function nextPage() {
  if (offset.value + pageSize >= total.value) return
  offset.value += pageSize
  void load()
}

function toggleRow(abs: number, feat: GeoJSON.Feature, ev: MouseEvent) {
  ctxMenu.value = null
  const next = new Set(selectedAbs.value)
  if (ev.shiftKey && lastClickedAbs.value != null) {
    const lo = Math.min(lastClickedAbs.value, abs)
    const hi = Math.max(lastClickedAbs.value, abs)
    for (const a of absIndexes.value) {
      if (a >= lo && a <= hi) next.add(a)
    }
  } else if (ev.ctrlKey || ev.metaKey) {
    if (next.has(abs)) next.delete(abs)
    else next.add(abs)
    lastClickedAbs.value = abs
  } else {
    next.clear()
    next.add(abs)
    lastClickedAbs.value = abs
  }
  selectedAbs.value = next
  syncSelectionHighlight(feat)
}

function selectAllOnPage() {
  const next = new Set(selectedAbs.value)
  for (const a of absIndexes.value) next.add(a)
  selectedAbs.value = next
  if (absIndexes.value.length) lastClickedAbs.value = absIndexes.value[0]!
  syncSelectionHighlight()
}

function clearSelection() {
  selectedAbs.value = new Set()
  lastClickedAbs.value = null
  dataWorkspaceHighlight.value = null
  dataWorkspaceSelection.value = null
  ctxMenu.value = null
}

function csvEscape(value: unknown): string {
  const s = value == null ? '' : String(value)
  if (/[",\r\n]/.test(s)) return `"${s.replace(/"/g, '""')}"`
  return s
}

async function copyText(text: string) {
  try {
    await navigator.clipboard.writeText(text)
    showToast(DATA_COPY.attrCopied, false, 2200)
  } catch {
    showToast(DATA_COPY.attrCopyFail, true, 2800)
  }
}

async function copySelectedCsv() {
  if (!selectedAbs.value.size) return
  const cols = columns.value
  const lines = [cols.join(',')]
  for (const row of rows.value) {
    if (!selectedAbs.value.has(row.abs)) continue
    lines.push(cols.map((c) => csvEscape(row.feat.properties?.[c])).join(','))
  }
  await copyText(lines.join('\n'))
}

function onCellContextMenu(ev: MouseEvent, abs: number, field: string, value: unknown) {
  ev.preventDefault()
  ctxMenu.value = { x: ev.clientX, y: ev.clientY, abs, field, value }
  if (!selectedAbs.value.has(abs)) {
    selectedAbs.value = new Set([abs])
    lastClickedAbs.value = abs
    const local = absIndexes.value.findIndex((a) => a === abs)
    const feat = local >= 0 ? features.value[local] : undefined
    if (feat) syncSelectionHighlight(feat)
  }
}

async function copyCellFromMenu() {
  if (!ctxMenu.value) return
  await copyText(cellText(ctxMenu.value.value))
  ctxMenu.value = null
}

function colStyle(field: string): Record<string, string> | undefined {
  const w = colWidths.value[field]
  if (!w) return undefined
  return { width: `${w}px`, minWidth: `${w}px`, maxWidth: `${w}px` }
}

function onColResizeStart(ev: PointerEvent, field: string) {
  ev.preventDefault()
  ev.stopPropagation()
  const startX = ev.clientX
  const startW = colWidths.value[field] ?? 140
  const target = ev.currentTarget as HTMLElement
  target.setPointerCapture?.(ev.pointerId)
  function onMove(e: PointerEvent) {
    const next = Math.max(72, Math.min(420, startW + (e.clientX - startX)))
    colWidths.value = { ...colWidths.value, [field]: next }
  }
  function onUp() {
    window.removeEventListener('pointermove', onMove)
    window.removeEventListener('pointerup', onUp)
  }
  window.addEventListener('pointermove', onMove)
  window.addEventListener('pointerup', onUp)
}

function syncSelectionHighlight(primary?: GeoJSON.Feature) {
  if (!selectedLayer.value) return
  const ids = Array.from(selectedAbs.value)
  dataWorkspaceSelection.value = {
    instanceId: selectedLayer.value.instanceId,
    featureIds: ids,
  }
  const feat =
    primary ||
    (() => {
      const local = absIndexes.value.findIndex((a) => a === ids[0])
      return local >= 0 ? features.value[local] : null
    })()
  if (feat && ids.length === 1) {
    dataWorkspaceHighlight.value = {
      instanceId: selectedLayer.value.instanceId,
      feature: feat,
      featureIndex: ids[0],
    }
  } else if (ids.length === 0) {
    dataWorkspaceHighlight.value = null
  } else if (feat) {
    dataWorkspaceHighlight.value = {
      instanceId: selectedLayer.value.instanceId,
      feature: feat,
      featureIndex: ids[0],
    }
  }
}

function zoomToSelected() {
  if (!selectedLayer.value || !selectedAbs.value.size) return
  const feats = features.value.filter((_, i) => selectedAbs.value.has(absIndexes.value[i] ?? -1))
  if (!feats.length) return
  dataWorkspaceHighlight.value = {
    instanceId: selectedLayer.value.instanceId,
    feature: feats[0]!,
    featureIndex: Array.from(selectedAbs.value)[0],
  }
  // 复用地图高亮；多要素时 fit 由 MapCanvas 对单要素已足够，后续可扩展
  openDataWorkspace({ tab: 'attributes', layerInstanceId: selectedLayer.value.instanceId })
}

function startEdit(abs: number, field: string, current: unknown) {
  const safe = sanitizeSafeText(current == null ? '' : String(current))
  editing.value = {
    absIndex: abs,
    field,
    // eslint-disable-next-line no-control-regex -- strip NUL bytes as fallback
    value: safe.ok ? safe.value : String(current ?? '').replace(/\u0000/g, ''),
  }
}

async function commitEdit() {
  if (!backendId.value || !editing.value) return
  const safe = sanitizeSafeText(editing.value.value)
  if (!safe.ok) {
    error.value = safe.error
    return
  }
  loading.value = true
  error.value = ''
  try {
    await patchFeatureAttribute(
      backendId.value,
      editing.value.absIndex,
      editing.value.field,
      safe.value,
    )
    editing.value = null
    await load()
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}

async function applyBatchSet() {
  if (!backendId.value || !batchField.value || !selectedAbs.value.size) return
  const safe = sanitizeSafeText(batchValue.value)
  if (!safe.ok) {
    error.value = safe.error
    return
  }
  loading.value = true
  error.value = ''
  try {
    await batchSetFeatureAttribute(
      backendId.value,
      Array.from(selectedAbs.value),
      batchField.value,
      safe.value,
    )
    batchValue.value = safe.value
    await load()
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}

async function doRename() {
  if (!backendId.value || !renameFrom.value) return
  const safeTo = sanitizeFieldName(renameTo.value)
  if (!safeTo.ok) {
    error.value = safeTo.error
    return
  }
  loading.value = true
  error.value = ''
  try {
    const result = await renameImportedLayerField(backendId.value, renameFrom.value, safeTo.value)
    if (result.preview_geojson && selectedLayer.value) {
      layersStore.updateImportedVectorGeojson(
        selectedLayer.value.instanceId,
        result.preview_geojson,
        {
          featureCount: result.feature_count,
        },
      )
    }
    renameFrom.value = ''
    renameTo.value = ''
    await loadMetaAndRows()
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}

async function doAddField() {
  if (!backendId.value) return
  const safeName = sanitizeFieldName(newFieldName.value)
  if (!safeName.ok) {
    error.value = safeName.error
    return
  }
  loading.value = true
  error.value = ''
  try {
    const res = await addLayerField(backendId.value, safeName.value)
    schemaFields.value = res.fields || []
    newFieldName.value = ''
    await load()
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}

async function doDeleteField(name: string) {
  if (!backendId.value || !name) return
  if (!confirm(`删除字段「${name}」？`)) return
  loading.value = true
  try {
    const res = await deleteLayerField(backendId.value, name)
    schemaFields.value = res.fields || []
    await load()
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}

function applyFilter() {
  const contains = sanitizeSafeText(filterContains.value, { maxLen: 200 })
  if (!contains.ok) {
    error.value = contains.error
    return
  }
  filterContains.value = contains.value
  const where = sanitizeSafeText(whereExpr.value, { maxLen: 500 })
  if (!where.ok) {
    error.value = where.error
    return
  }
  whereExpr.value = where.value
  offset.value = 0
  void load()
}

function toggleSort(field: string) {
  if (sortField.value === field) sortDesc.value = !sortDesc.value
  else {
    sortField.value = field
    sortDesc.value = false
  }
  offset.value = 0
  void load()
}
</script>

<template>
  <div class="attr-table">
    <div class="attr-toolbar">
      <label>
        {{ DATA_COPY.attrLayer }}
        <select :value="selectedLayer?.instanceId ?? ''" @change="onSelectLayer">
          <option v-if="!importedVectors.length" value="">{{ DATA_COPY.attrEmpty }}</option>
          <option v-for="l in importedVectors" :key="l.instanceId" :value="l.instanceId">
            {{ l.name }}
          </option>
        </select>
      </label>
      <label>
        {{ DATA_COPY.filterField }}
        <select v-model="filterField">
          <option value="">—</option>
          <option v-for="c in columns" :key="c" :value="c">{{ c }}</option>
        </select>
      </label>
      <label>
        {{ DATA_COPY.filterContains }}
        <input
          v-model="filterContains"
          type="text"
          maxlength="200"
          autocomplete="off"
          spellcheck="false"
          @keydown.enter="applyFilter"
        />
      </label>
      <label>
        {{ DATA_COPY.attrWhere }}
        <input
          v-model="whereExpr"
          type="text"
          maxlength="500"
          autocomplete="off"
          spellcheck="false"
          :placeholder="DATA_COPY.attrWherePh"
          @keydown.enter="applyFilter"
        />
      </label>
      <button
        class="ghost-btn"
        type="button"
        :disabled="loading || !backendId"
        @click="applyFilter"
      >
        {{ DATA_COPY.attrFilter }}
      </button>
      <button class="ghost-btn" type="button" :disabled="!selectedAbs.size" @click="zoomToSelected">
        {{ DATA_COPY.attrZoomSelected }}
      </button>
      <button
        class="ghost-btn"
        type="button"
        :disabled="!absIndexes.length"
        @click="selectAllOnPage"
      >
        {{ DATA_COPY.attrSelectPage }}
      </button>
      <button class="ghost-btn" type="button" :disabled="!selectedAbs.size" @click="clearSelection">
        {{ DATA_COPY.attrClearSel }}
      </button>
      <button
        class="ghost-btn accent-btn"
        type="button"
        :disabled="!selectedAbs.size"
        @click="copySelectedCsv"
      >
        {{ DATA_COPY.attrCopySelected }}
      </button>

      <span class="toolbar-sep" aria-hidden="true" />

      <label>
        {{ DATA_COPY.renameFrom }}
        <select v-model="renameFrom">
          <option value="">—</option>
          <option v-for="c in columns" :key="c" :value="c">{{ c }}</option>
        </select>
      </label>
      <label>
        {{ DATA_COPY.renameTo }}
        <input
          v-model="renameTo"
          type="text"
          maxlength="64"
          autocomplete="off"
          spellcheck="false"
          @keydown.enter="doRename"
        />
      </label>
      <button
        class="ghost-btn"
        type="button"
        :disabled="loading || !renameFrom || !renameTo"
        @click="doRename"
      >
        {{ DATA_COPY.attrRename }}
      </button>
      <label>
        {{ DATA_COPY.attrAddField }}
        <input
          v-model="newFieldName"
          type="text"
          maxlength="64"
          autocomplete="off"
          spellcheck="false"
          @keydown.enter="doAddField"
        />
      </label>
      <button
        class="ghost-btn"
        type="button"
        :disabled="loading || !newFieldName"
        @click="doAddField"
      >
        {{ DATA_COPY.attrAddFieldBtn }}
      </button>
      <label>
        {{ DATA_COPY.attrBatchField }}
        <select v-model="batchField">
          <option value="">—</option>
          <option v-for="c in columns" :key="c" :value="c">{{ c }}</option>
        </select>
      </label>
      <label>
        {{ DATA_COPY.attrBatchValue }}
        <input
          v-model="batchValue"
          type="text"
          maxlength="4000"
          autocomplete="off"
          spellcheck="false"
          @keydown.enter="applyBatchSet"
        />
      </label>
      <button
        class="ghost-btn"
        type="button"
        :disabled="loading || !batchField || !selectedAbs.size"
        @click="applyBatchSet"
      >
        {{ DATA_COPY.attrBatchSet }}
      </button>
    </div>

    <p v-if="error" class="err">{{ error }}</p>
    <p v-else-if="!importedVectors.length" class="empty">{{ DATA_COPY.attrEmpty }}</p>
    <template v-else>
      <p class="sel-hint">
        {{ DATA_COPY.attrSelected }}: {{ selectedAbs.size }} · {{ DATA_COPY.attrHintMulti }}
        <span v-if="encodingBadge" class="enc-badge" :title="encodingBadge">{{
          encodingBadge
        }}</span>
      </p>

      <div class="table-scroll" ref="tableBodyEl" @click="ctxMenu = null">
        <table>
          <thead>
            <tr>
              <th class="col-idx">#</th>
              <th v-for="c in columns" :key="c" :title="c" :style="colStyle(c)">
                <div class="th-inner">
                  <button type="button" class="th-btn" @click="toggleSort(c)">
                    {{ c }}
                    <span v-if="sortField === c" class="sort-mark">{{ sortDesc ? '↓' : '↑' }}</span>
                  </button>
                  <button
                    type="button"
                    class="del-field"
                    :title="DATA_COPY.attrDeleteField"
                    @click.stop="doDeleteField(c)"
                  >
                    ×
                  </button>
                  <span
                    class="col-resizer"
                    title="拖动调整列宽"
                    @pointerdown="onColResizeStart($event, c)"
                  />
                </div>
              </th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="(row, rowIdx) in rows"
              :key="row.abs"
              :data-abs="row.abs"
              :class="{ selected: selectedAbs.has(row.abs), zebra: rowIdx % 2 === 1 }"
              @click="toggleRow(row.abs, row.feat, $event)"
            >
              <td class="col-idx">{{ row.abs + 1 }}</td>
              <td
                v-for="c in columns"
                :key="c"
                class="cell-text"
                :style="colStyle(c)"
                :title="cellTitle(row.feat.properties?.[c])"
                lang="zh-CN"
                @dblclick.stop="startEdit(row.abs, c, row.feat.properties?.[c])"
                @contextmenu="onCellContextMenu($event, row.abs, c, row.feat.properties?.[c])"
              >
                <template v-if="editing && editing.absIndex === row.abs && editing.field === c">
                  <input
                    v-model="editing.value"
                    class="cell-edit"
                    lang="zh-CN"
                    maxlength="4000"
                    autocomplete="off"
                    spellcheck="false"
                    @keydown.enter="commitEdit"
                    @keydown.esc="editing = null"
                    @blur="commitEdit"
                  />
                </template>
                <template v-else>{{ cellText(row.feat.properties?.[c]) }}</template>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <div class="pager">
        <button
          class="ghost-btn"
          type="button"
          :disabled="offset <= 0 || loading"
          @click="prevPage"
        >
          {{ DATA_COPY.attrPrev }}
        </button>
        <span>{{ page }} / {{ pageCount }} · {{ total }} {{ DATA_COPY.attrRows }}</span>
        <button
          class="ghost-btn"
          type="button"
          :disabled="offset + pageSize >= total || loading"
          @click="nextPage"
        >
          {{ DATA_COPY.attrNext }}
        </button>
      </div>
    </template>

    <div
      v-if="ctxMenu"
      class="cell-ctx"
      :style="{ left: ctxMenu.x + 'px', top: ctxMenu.y + 'px' }"
      @click.stop
    >
      <button type="button" class="ctx-btn" @click="copyCellFromMenu">
        {{ DATA_COPY.attrCopyCell }}
      </button>
      <button type="button" class="ctx-btn" :disabled="!selectedAbs.size" @click="copySelectedCsv">
        {{ DATA_COPY.attrCopySelected }}
      </button>
    </div>
  </div>
</template>

<style scoped>
.attr-table {
  display: flex;
  flex-direction: column;
  gap: 0.45rem;
  min-height: 0;
  height: 100%;
  overflow: hidden;
  position: relative;
}
.attr-toolbar,
.pager,
.sel-hint {
  flex: none;
}
.attr-toolbar,
.pager {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  gap: 0.38rem 0.46rem;
}
.toolbar-sep {
  display: inline-block;
  align-self: stretch;
  width: 1px;
  min-height: 1.8rem;
  margin: 0 0.12rem;
  background: linear-gradient(180deg, transparent, rgba(136, 192, 255, 0.28), transparent);
}
label {
  display: flex;
  flex-direction: column;
  gap: 0.14rem;
  font-size: 0.6rem;
  letter-spacing: 0.02em;
  color: #8aa0b4;
}
input,
select {
  border: 1px solid rgba(136, 192, 255, 0.16);
  border-radius: 0.34rem;
  padding: 0.28rem 0.4rem;
  background: rgba(4, 12, 23, 0.72);
  color: #d8e6f5;
  font: inherit;
  font-size: 0.68rem;
  min-width: 6.2rem;
}
.ghost-btn {
  border: 1px solid rgba(136, 192, 255, 0.2);
  border-radius: 0.38rem;
  padding: 0.3rem 0.55rem;
  background: rgba(4, 12, 23, 0.55);
  color: #c5d8ea;
  font: inherit;
  font-size: 0.66rem;
  cursor: pointer;
  transition:
    background 0.15s ease,
    border-color 0.15s ease;
}
.ghost-btn:hover:not(:disabled) {
  background: rgba(20, 48, 78, 0.72);
  border-color: rgba(136, 192, 255, 0.35);
}
.ghost-btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}
.accent-btn {
  border-color: rgba(126, 224, 168, 0.35);
  color: #b8f0cf;
  background: rgba(20, 56, 40, 0.45);
}
.table-scroll {
  flex: 1 1 0;
  min-height: 0;
  overflow: auto;
  border: 1px solid rgba(136, 192, 255, 0.14);
  border-radius: 0.48rem;
  background:
    linear-gradient(180deg, rgba(12, 28, 46, 0.55), rgba(6, 14, 24, 0.35)), rgba(4, 10, 18, 0.55);
  box-shadow: inset 0 1px 0 rgba(160, 210, 255, 0.06);
  scrollbar-width: thin;
  scrollbar-color: rgba(90, 213, 255, 0.35) transparent;
}
.table-scroll::-webkit-scrollbar {
  width: 5px;
  height: 5px;
}
.table-scroll::-webkit-scrollbar-thumb {
  background: rgba(90, 213, 255, 0.35);
  border-radius: 999px;
}
table {
  border-collapse: separate;
  border-spacing: 0;
  width: max-content;
  min-width: 100%;
  font-size: 0.72rem;
  font-family:
    'Segoe UI', 'PingFang SC', 'Microsoft YaHei UI', 'Microsoft YaHei', 'Noto Sans CJK SC',
    'Noto Sans SC', 'Source Han Sans SC', 'WenQuanYi Micro Hei', system-ui, sans-serif;
}
th,
td {
  border-bottom: 1px solid rgba(136, 192, 255, 0.07);
  padding: 0.32rem 0.55rem;
  text-align: left;
  white-space: nowrap;
  max-width: 22rem;
  overflow: hidden;
  text-overflow: ellipsis;
  line-height: 1.45;
}
td.cell-text {
  max-width: 28rem;
  font-variant-east-asian: proportional-width;
}
td.col-idx,
th.col-idx {
  max-width: 3.2rem;
  color: #7a91a8;
  font-variant-numeric: tabular-nums;
  position: sticky;
  left: 0;
  z-index: 2;
  background: rgba(10, 20, 34, 0.96);
}
th {
  position: sticky;
  top: 0;
  background: linear-gradient(180deg, rgba(16, 34, 54, 0.98), rgba(10, 22, 38, 0.96));
  color: #9ec4e0;
  z-index: 3;
  font-size: 0.68rem;
  letter-spacing: 0.01em;
  border-bottom: 1px solid rgba(136, 192, 255, 0.18);
  box-shadow: 0 1px 0 rgba(0, 0, 0, 0.25);
}
th.col-idx {
  z-index: 4;
}
.th-inner {
  display: flex;
  align-items: center;
  gap: 0.15rem;
  position: relative;
  padding-right: 0.45rem;
}
.sort-mark {
  color: #7ee0a8;
  margin-left: 0.12rem;
}
.enc-badge {
  display: inline-block;
  margin-left: 0.45rem;
  padding: 0.1rem 0.4rem;
  border-radius: 999px;
  border: 1px solid rgba(90, 213, 255, 0.28);
  background: rgba(10, 40, 64, 0.65);
  color: #9fd8ff;
  font-size: 0.58rem;
  max-width: min(28rem, 55vw);
  overflow: hidden;
  text-overflow: ellipsis;
  vertical-align: middle;
}
.th-btn {
  border: 0;
  background: transparent;
  color: inherit;
  font: inherit;
  cursor: pointer;
  padding: 0;
}
.del-field {
  margin-left: 0.1rem;
  border: 0;
  background: transparent;
  color: #6a8094;
  cursor: pointer;
  font-size: 0.78rem;
  line-height: 1;
  opacity: 0.55;
}
.del-field:hover {
  opacity: 1;
  color: #ffb0b0;
}
.col-resizer {
  position: absolute;
  right: 0;
  top: 0;
  bottom: 0;
  width: 5px;
  cursor: col-resize;
  border-radius: 2px;
}
.col-resizer:hover {
  background: rgba(90, 213, 255, 0.35);
}
tr {
  cursor: pointer;
  transition: background 0.12s ease;
}
tr.zebra td {
  background: rgba(255, 255, 255, 0.015);
}
tr.zebra td.col-idx {
  background: rgba(12, 24, 40, 0.96);
}
tr:hover td {
  background: rgba(10, 132, 255, 0.1);
}
tr:hover td.col-idx {
  background: rgba(14, 40, 68, 0.96);
}
tr.selected td {
  background: rgba(255, 209, 102, 0.16);
}
tr.selected td.col-idx {
  background: rgba(64, 48, 18, 0.92);
  color: #ffd166;
  box-shadow: inset 3px 0 0 #ffd166;
}
.cell-edit {
  min-width: 4rem;
  width: 100%;
  font-family: inherit;
  font-size: inherit;
}
.pager {
  justify-content: space-between;
  font-size: 0.64rem;
  color: #8aa0b4;
}
.sel-hint,
.empty,
.err {
  margin: 0;
  font-size: 0.66rem;
}
.err {
  color: #ffb0b0;
}
.empty,
.sel-hint {
  color: #8aa0b4;
}
.cell-ctx {
  position: fixed;
  z-index: 80;
  min-width: 8.5rem;
  padding: 0.28rem;
  border-radius: 0.42rem;
  border: 1px solid rgba(136, 192, 255, 0.22);
  background: rgba(8, 18, 32, 0.96);
  box-shadow: 0 10px 28px rgba(0, 0, 0, 0.45);
  display: flex;
  flex-direction: column;
  gap: 0.12rem;
}
.ctx-btn {
  border: 0;
  border-radius: 0.3rem;
  padding: 0.35rem 0.55rem;
  background: transparent;
  color: #d0e4f6;
  font: inherit;
  font-size: 0.68rem;
  text-align: left;
  cursor: pointer;
}
.ctx-btn:hover:not(:disabled) {
  background: rgba(30, 80, 130, 0.45);
}
.ctx-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
</style>
