/**
 * useFileDrop — 地图区域文件拖放导入逻辑。
 *
 * 从 DashboardView.vue 提取：isFileDrag / onMapShellDragEnter / onMapShellDragOver /
 * onMapShellDragLeave / onMapShellDrop。
 */
import type { Ref } from 'vue'
import type { useDataImportFlow } from '../../data-manager/core/workspace-store'

export function useFileDrop(
  dataImportFlow: ReturnType<typeof useDataImportFlow>,
  workflowEditorOpen: Ref<boolean>,
  settingsOpen: Ref<boolean>,
  mapShellRef: Ref<HTMLElement | null>,
) {
  const { processFiles, dropActive, importing } = dataImportFlow

  function isFileDrag(e: DragEvent): boolean {
    return Array.from(e.dataTransfer?.types ?? []).includes('Files')
  }

  function onMapShellDragEnter(e: DragEvent) {
    if (workflowEditorOpen.value || settingsOpen.value || importing.value) return
    if (!isFileDrag(e)) return
    e.preventDefault()
    dropActive.value = true
  }

  function onMapShellDragOver(e: DragEvent) {
    if (workflowEditorOpen.value || settingsOpen.value || importing.value) return
    if (!isFileDrag(e)) return
    e.preventDefault()
    if (e.dataTransfer) e.dataTransfer.dropEffect = 'copy'
    dropActive.value = true
  }

  function onMapShellDragLeave(e: DragEvent) {
    const related = e.relatedTarget as Node | null
    if (related && mapShellRef.value?.contains(related)) return
    dropActive.value = false
  }

  async function onMapShellDrop(e: DragEvent) {
    dropActive.value = false
    if (workflowEditorOpen.value || settingsOpen.value || importing.value) return
    if (!isFileDrag(e)) return
    e.preventDefault()
    e.stopPropagation()
    await processFiles(e.dataTransfer?.files)
  }

  return {
    dropActive,
    onMapShellDragEnter,
    onMapShellDragOver,
    onMapShellDragLeave,
    onMapShellDrop,
  }
}
