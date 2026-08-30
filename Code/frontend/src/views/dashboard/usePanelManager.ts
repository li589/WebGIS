/**
 * usePanelManager — 全屏面板（截图/设置/工作流状态/日志/工作流编辑器）的
 * 开关状态、异步加载跟踪与风场动画暂停协调。
 *
 * 从 DashboardView.vue 提取。
 */
import { onMounted, onBeforeUnmount, ref, watch, type Ref } from 'vue'
import type { useUiLoadingStore } from '../../stores/ui-loading'
import type MapCanvas from '../../components/MapCanvas.vue'

export function usePanelManager(
  uiLoading: ReturnType<typeof useUiLoadingStore>,
  mapCanvasRef: Ref<InstanceType<typeof MapCanvas> | null>,
) {
  const screenshotOpen = ref(false)
  const workflowStatusOpen = ref(false)
  const logOpen = ref(false)
  const settingsOpen = ref(false)
  const workflowEditorOpen = ref(false)
  const workflowEditorRef = ref<{
    notifyRunOutcome?: (ok: boolean, message?: string) => void
    applyBoundMainTimeline?: (range: { start_at: string; end_at: string }) => number
  } | null>(null)
  const analysisPanelRef = ref<{ showPanel: () => void } | null>(null)

  // 异步组件首次加载跟踪：仅首次打开时显示 loading
  const _loadedAsyncPanels = new Set<string>()

  watch(settingsOpen, (open) => {
    if (open && !_loadedAsyncPanels.has('settings')) {
      _loadedAsyncPanels.add('settings')
      uiLoading.showImmediate('加载设置面板...', 'compact')
    }
  })

  watch(workflowEditorOpen, (open) => {
    if (open && !_loadedAsyncPanels.has('workflow-editor')) {
      _loadedAsyncPanels.add('workflow-editor')
      uiLoading.showImmediate('加载工作流编辑器...', 'compact')
    }
  })

  /** 全屏面板盖住地图时暂停风场 RAF */
  watch([workflowEditorOpen, settingsOpen], ([workflowOpen, settingsPanelOpen]) => {
    mapCanvasRef.value?.setWindAnimationPaused?.(workflowOpen || settingsPanelOpen)
  })

  // ── GPU 性能检测：暂停/恢复所有性能消耗项 ─────────────────────────
  function handlePerfTestStart() {
    mapCanvasRef.value?.setWindAnimationPaused?.(true)
  }
  function handlePerfTestEnd() {
    // 恢复至面板状态决定的原值
    mapCanvasRef.value?.setWindAnimationPaused?.(workflowEditorOpen.value || settingsOpen.value)
  }
  onMounted(() => {
    window.addEventListener('cgda:perf-test-start', handlePerfTestStart)
    window.addEventListener('cgda:perf-test-end', handlePerfTestEnd)
  })
  onBeforeUnmount(() => {
    window.removeEventListener('cgda:perf-test-start', handlePerfTestStart)
    window.removeEventListener('cgda:perf-test-end', handlePerfTestEnd)
  })

  // ── 开/关 handler ──────────────────────────────────────────────────────

  function handleOpenScreenshot() {
    screenshotOpen.value = true
  }
  function handleCloseScreenshot() {
    screenshotOpen.value = false
  }
  function handleOpenSettings() {
    settingsOpen.value = true
  }
  function handleCloseSettings() {
    settingsOpen.value = false
  }
  function handleOpenWorkflowStatus() {
    workflowStatusOpen.value = true
  }
  function handleCloseWorkflowStatus() {
    workflowStatusOpen.value = false
  }
  function handleOpenWorkflowEditor() {
    workflowEditorOpen.value = true
  }
  function handleCloseWorkflowEditor() {
    workflowEditorOpen.value = false
  }

  return {
    screenshotOpen,
    workflowStatusOpen,
    logOpen,
    settingsOpen,
    workflowEditorOpen,
    workflowEditorRef,
    analysisPanelRef,
    handleOpenScreenshot,
    handleCloseScreenshot,
    handleOpenSettings,
    handleCloseSettings,
    handleOpenWorkflowStatus,
    handleCloseWorkflowStatus,
    handleOpenWorkflowEditor,
    handleCloseWorkflowEditor,
  }
}
