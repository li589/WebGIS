import { computed, ref, type ComputedRef } from 'vue'

import type { ActiveLayerDisplay } from '../../stores/layers/types'
import { useLayerWorkspace } from '../../stores/layers/selectors'
import { useLogStore } from '../../stores/log'
import { openDatedExportForLayer } from '../../data-manager/core/workspace-store'
import { exportLayer } from '../../data-manager/adapters/export'

/**
 * 导入 / 导出 + 提示 + 矢量样式 composable。
 *
 * 从 InfoPanel.vue 提取，集中管理导入图层的导出（GeoJSON / CSV / SHP / 栅格）
 * 以及导入矢量样式的 patch 逻辑。
 */
export function useImportExport(displayLayer: ComputedRef<ActiveLayerDisplay>) {
  const workspace = useLayerWorkspace()
  const logStore = useLogStore()

  // ── 导入操作提示 ──────────────────────────────────────────────────────────

  const importActionHint = ref('')
  let importHintTimer: number | null = null

  function flashImportHint(message: string) {
    importActionHint.value = message
    if (importHintTimer !== null) window.clearTimeout(importHintTimer)
    importHintTimer = window.setTimeout(() => {
      importActionHint.value = ''
      importHintTimer = null
    }, 3200)
  }

  // ── 导出 ──────────────────────────────────────────────────────────────────

  async function exportImportedGeoJson() {
    const id = displayLayer.value.instanceId
    if (!id) return
    const active = workspace.activeLayers.value.find((l) => l.instanceId === id)
    if (!active) return
    try {
      await exportLayer(active, 'geojson')
      flashImportHint('已导出 GeoJSON')
      logStore.logOperation('export-geojson', `导出 GeoJSON：${displayLayer.value.name || id}`)
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e)
      flashImportHint(`导出失败：${msg}`)
      logStore.logOperation('export-fail', '分析框导出 GeoJSON 失败', msg)
    }
  }

  async function exportImportedCsv() {
    const id = displayLayer.value.instanceId
    if (!id) return
    const active = workspace.activeLayers.value.find((l) => l.instanceId === id)
    if (!active) return
    try {
      await exportLayer(active, 'csv')
      flashImportHint('已导出 CSV')
      logStore.logOperation('export-csv', `导出 CSV：${displayLayer.value.name || id}`)
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e)
      flashImportHint(`导出失败：${msg}`)
      logStore.logOperation('export-fail', '分析框导出 CSV 失败', msg)
    }
  }

  async function exportImportedShp() {
    const id = displayLayer.value.instanceId
    if (!id) return
    const active = workspace.activeLayers.value.find((l) => l.instanceId === id)
    if (!active) return
    try {
      await exportLayer(active, 'shp-zip')
      flashImportHint('已导出 SHP')
      logStore.logOperation('export-shp', `导出 SHP：${displayLayer.value.name || id}`)
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e)
      flashImportHint(`导出失败：${msg}`)
      logStore.logOperation('export-fail', '分析框导出 SHP 失败', msg)
    }
  }

  function openExportPanelForDisplay() {
    const id = displayLayer.value.instanceId
    if (!id) return
    const active = workspace.activeLayers.value.find((l) => l.instanceId === id)
    if (!active) return
    const times = active.importedRaster?.timeList ?? []
    let time: string | null = null
    if (times.length) {
      const eff = active.importedRaster?.effectiveTimeLabel
      time =
        (eff && times.find((t) => eff === t || eff.startsWith(t))) ||
        times[times.length - 1] ||
        null
    }
    openDatedExportForLayer(id, time)
  }

  async function exportImportedRaster(format: 'png' | 'tif' | 'nc' | 'mat') {
    const id = displayLayer.value.instanceId
    if (!id) return
    const active = workspace.activeLayers.value.find((l) => l.instanceId === id)
    if (!active) return
    // 汇合到数据导出框（预选当前生效时刻）
    if (active.importedRaster) {
      const times = active.importedRaster.timeList ?? []
      let time: string | null = null
      if (times.length) {
        const eff = active.importedRaster.effectiveTimeLabel
        time =
          (eff && times.find((t) => eff === t || eff.startsWith(t))) ||
          times[times.length - 1] ||
          null
      }
      openDatedExportForLayer(id, time)
      logStore.logOperation(
        `export-open-${format}`,
        `打开导出：${displayLayer.value.name || id}${time ? ` @ ${time}` : ''}`,
      )
      return
    }
    try {
      await exportLayer(active, format)
      flashImportHint(format === 'png' ? '已导出 PNG' : '已导出 GeoTIFF')
      logStore.logOperation(
        `export-${format}`,
        `导出 ${format.toUpperCase()}：${displayLayer.value.name || id}`,
      )
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e)
      flashImportHint(`导出失败：${msg}`)
      logStore.logOperation('export-fail', `分析框导出 ${format.toUpperCase()} 失败`, msg)
    }
  }

  // ── 导入矢量样式 ──────────────────────────────────────────────────────────

  function patchImportedVectorStyle(
    patch: Partial<{ color: string; width: number; radius: number; fillOpacity: number }>,
  ) {
    const id = displayLayer.value.instanceId
    if (!id || !displayLayer.value.isImported) return
    workspace.setImportedVectorStyle(id, patch)
  }

  const importedVectorStyle = computed(() => displayLayer.value.importedVectorStyle ?? {})

  // ── 清理 ──────────────────────────────────────────────────────────────────

  function cleanupImportExport() {
    if (importHintTimer !== null) {
      window.clearTimeout(importHintTimer)
      importHintTimer = null
    }
  }

  return {
    importActionHint,
    flashImportHint,
    exportImportedGeoJson,
    exportImportedCsv,
    exportImportedShp,
    openExportPanelForDisplay,
    exportImportedRaster,
    patchImportedVectorStyle,
    importedVectorStyle,
    cleanupImportExport,
  }
}
