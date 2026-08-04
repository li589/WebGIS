/**
 * 数据工作台全局状态：导入/导出/属性表/详情入口与拖放分流。
 */
import { ref, shallowRef } from 'vue'
import { useLogStore } from '../../stores/log'
import { classifyDataFile, type DataImportKind } from './api'

const importing = ref(false)
const importMsg = ref('')
const importError = ref(false)
const uploadProgress = ref<number | null>(null)
const dropActive = ref(false)

/** 最近作业进度（批导入/导出） */
export const dataJobs = ref<
  Array<{
    id: string
    kind: string
    status: string
    progress: number
    message?: string
  }>
>([])

export type ImportPanelTab = 'vector' | 'raster' | 'document'
export type DataWorkspaceTab = 'import' | 'export' | 'attributes' | 'details' | 'jobs'

export const pendingOpenImport = shallowRef<{
  tab: ImportPanelTab
  files: File[]
} | null>(null)

/** 混合拖放：按类型拆批的待处理队列 */
export const pendingImportBatches = shallowRef<Array<{ tab: ImportPanelTab; files: File[] }>>([])

export const pendingOpenExport = ref(false)

export const dataWorkspaceOpen = ref(false)
export const dataWorkspaceTab = ref<DataWorkspaceTab>('import')
export const dataWorkspaceImportKind = ref<ImportPanelTab>('vector')
export const dataWorkspaceLayerId = ref<string | null>(null)
/** 导出面板预选时间切片（如 20251227_20251231） */
export const dataWorkspaceExportTime = ref<string | null>(null)
export const dataWorkspaceHeight = ref(340)
export const dataWorkspaceMaximized = ref(false)
export const dataWorkspaceSeedFiles = shallowRef<File[] | undefined>(undefined)
/** 属性表选中要素 → 地图高亮 */
export const dataWorkspaceHighlight = shallowRef<{
  instanceId: string
  feature: GeoJSON.Feature
  featureIndex?: number
} | null>(null)

/** 属性表多选高亮 */
export const dataWorkspaceSelection = shallowRef<{
  instanceId: string
  featureIds: Array<string | number>
} | null>(null)

let toastTimer: ReturnType<typeof setTimeout> | null = null

export function showToast(message: string, isError = false, ms = 4200) {
  importMsg.value = message
  importError.value = isError
  if (toastTimer) clearTimeout(toastTimer)
  toastTimer = setTimeout(() => {
    importMsg.value = ''
    importError.value = false
    toastTimer = null
  }, ms)
}

function tabForKind(kind: DataImportKind): ImportPanelTab | null {
  if (kind === 'vector') return 'vector'
  if (kind === 'raster') return 'raster'
  if (kind === 'document') return 'document'
  return null
}

export function setUploadProgress(value: number | null) {
  uploadProgress.value = value
  importing.value = value != null && value < 1
}

export function openDataWorkspace(opts?: {
  tab?: DataWorkspaceTab
  importKind?: ImportPanelTab
  layerInstanceId?: string | null
  files?: File[]
  /** 打开导出页时预选时刻 */
  exportTime?: string | null
}) {
  if (opts?.tab) dataWorkspaceTab.value = opts.tab
  if (opts?.importKind) dataWorkspaceImportKind.value = opts.importKind
  if (opts?.layerInstanceId !== undefined) {
    dataWorkspaceLayerId.value = opts.layerInstanceId
  }
  if (opts?.files) dataWorkspaceSeedFiles.value = opts.files
  if (opts?.exportTime !== undefined) {
    dataWorkspaceExportTime.value = opts.exportTime
  } else if (opts?.tab === 'export' && opts.exportTime === undefined) {
    // 显式打开导出但未带时刻时保留已有预选；纯打开不强制清空
  }
  dataWorkspaceOpen.value = true
}

/** 侧栏/分析框汇合：打开数据导出并预选图层 + 生效时刻 */
export function openDatedExportForLayer(layerInstanceId: string, time?: string | null) {
  dataWorkspaceExportTime.value = time ?? null
  openDataWorkspace({ tab: 'export', layerInstanceId, exportTime: time ?? null })
}

export function closeDataWorkspace() {
  dataWorkspaceOpen.value = false
  dataWorkspaceSeedFiles.value = undefined
  dataWorkspaceHighlight.value = null
  dataWorkspaceSelection.value = null
  dataWorkspaceExportTime.value = null
}

export function useDataImportFlow() {
  const logStore = useLogStore()

  async function processFiles(fileList: FileList | File[] | null | undefined) {
    const files = Array.from(fileList ?? []).filter(Boolean)
    if (!files.length) return

    const byTab: Record<ImportPanelTab, File[]> = {
      vector: [],
      raster: [],
      document: [],
    }
    for (const file of files) {
      const kind = classifyDataFile(file)
      const tab = tabForKind(kind)
      if (!tab) {
        showToast(`跳过不支持的文件: ${file.name}`, true)
        logStore.logOperation('import-skip', `跳过: ${file.name}`, 'unsupported')
        continue
      }
      byTab[tab].push(file)
    }

    const batches: Array<{ tab: ImportPanelTab; files: File[] }> = []
    const order: ImportPanelTab[] = ['document', 'raster', 'vector']
    for (const tab of order) {
      if (byTab[tab].length) batches.push({ tab, files: byTab[tab] })
    }
    if (!batches.length) return

    pendingImportBatches.value = batches.slice(1)
    pendingOpenImport.value = batches[0]
    // 打开第一批；其余由菜单/面板消费 pendingImportBatches
    openDataWorkspace({
      tab: 'import',
      importKind: batches[0].tab,
      files: batches[0].files,
    })
  }

  return {
    csvFile: ref<File | null>(null),
    importing,
    importMsg,
    importError,
    uploadProgress,
    dropActive,
    pendingRasterConfirm: ref(null),
    pendingOpenImport,
    pendingOpenExport,
    pendingImportBatches,
    dataWorkspaceOpen,
    dataWorkspaceTab,
    dataJobs,
    showToast,
    setUploadProgress,
    processFiles,
    openDataWorkspace,
    closeDataWorkspace,
  }
}
