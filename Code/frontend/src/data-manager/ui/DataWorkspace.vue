<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { X, Minimize2, Maximize2 } from '../../components/ui/icons'
import DataImportPanel from './DataImportPanel.vue'
import DataExportPanel from './DataExportPanel.vue'
import AttributeTable from './AttributeTable.vue'
import LayerDetails from './LayerDetails.vue'
import JobsPanel from './JobsPanel.vue'
import {
  closeDataWorkspace,
  dataWorkspaceHeight,
  dataWorkspaceImportKind,
  dataWorkspaceMaximized,
  dataWorkspaceOpen,
  dataWorkspaceSeedFiles,
  dataWorkspaceTab,
  importQuota,
  quotaLoading,
  reclaimQuota,
  refreshImportQuota,
  type DataWorkspaceTab,
} from '../core/workspace-store'
import { formatBytes } from '../core/api'
import { DATA_COPY } from '../../ui-copy'
import { useAuthStore } from '../../stores/auth'

const authStore = useAuthStore()

const demoTransferRestricted = computed(() => authStore.isDemo)

const tabs: Array<{ id: DataWorkspaceTab; label: string; restricted?: boolean }> = [
  { id: 'import', label: DATA_COPY.wsImport, restricted: true },
  { id: 'export', label: DATA_COPY.wsExport, restricted: true },
  { id: 'attributes', label: DATA_COPY.wsAttributes },
  { id: 'details', label: DATA_COPY.wsDetails },
  { id: 'jobs', label: DATA_COPY.wsJobs },
]

function isTabDisabled(tab: { restricted?: boolean }): boolean {
  return Boolean(tab.restricted && demoTransferRestricted.value)
}

const mountedTabs = ref<Set<DataWorkspaceTab>>(new Set(['import']))

const importPanelKey = computed(
  () =>
    `${dataWorkspaceImportKind.value}:${(dataWorkspaceSeedFiles.value ?? []).map((f) => f.name).join('|')}`,
)

const resizing = ref(false)
const startY = ref(0)
const startH = ref(0)

const panelStyle = computed(() => {
  if (dataWorkspaceMaximized.value) {
    return {
      top: '0',
      left: '0',
      right: '0',
      bottom: '0',
      width: 'auto',
      height: 'auto',
      borderRadius: '0',
    }
  }
  return { height: `${dataWorkspaceHeight.value}px` }
})

function setTab(id: DataWorkspaceTab) {
  dataWorkspaceTab.value = id
  mountedTabs.value = new Set([...mountedTabs.value, id])
}

function toggleMax() {
  dataWorkspaceMaximized.value = !dataWorkspaceMaximized.value
}

function onResizeStart(e: PointerEvent) {
  resizing.value = true
  startY.value = e.clientY
  startH.value = dataWorkspaceHeight.value
  ;(e.target as HTMLElement).setPointerCapture?.(e.pointerId)
}

function onResizeMove(e: PointerEvent) {
  if (!resizing.value) return
  const delta = startY.value - e.clientY
  dataWorkspaceHeight.value = Math.max(
    220,
    Math.min(window.innerHeight * 0.85, startH.value + delta),
  )
  dataWorkspaceMaximized.value = false
}

function onResizeEnd() {
  resizing.value = false
}

function onKey(e: KeyboardEvent) {
  if (e.key === 'Escape' && dataWorkspaceOpen.value) closeDataWorkspace()
}

watch(dataWorkspaceOpen, (open) => {
  if (open) {
    document.addEventListener('keydown', onKey)
    mountedTabs.value = new Set([...mountedTabs.value, dataWorkspaceTab.value])
  } else document.removeEventListener('keydown', onKey)
})

watch(dataWorkspaceTab, (tab) => {
  mountedTabs.value = new Set([...mountedTabs.value, tab])
})

onBeforeUnmount(() => {
  document.removeEventListener('keydown', onKey)
})

onMounted(() => {
  void refreshImportQuota()
})

const quotaPercent = computed(() =>
  importQuota.value ? Math.min(100, Math.round(importQuota.value.used_ratio * 100)) : 0,
)
const quotaWarn = computed(() => (importQuota.value?.used_ratio ?? 0) > 0.85)

const onReclaim = () => {
  void reclaimQuota()
}

const dragOver = ref(false)

function onDragOver(e: DragEvent) {
  if (!e.dataTransfer?.types?.includes('Files')) return
  e.preventDefault()
  dragOver.value = true
}

function onDragLeave(e: DragEvent) {
  // 只在离开整个面板时才取消高亮
  const rt = e.currentTarget as HTMLElement
  if (e.relatedTarget && rt.contains(e.relatedTarget as Node)) return
  dragOver.value = false
}

function onDrop(_e: DragEvent) {
  dragOver.value = false
}
</script>

<template>
  <Teleport to="body">
    <aside
      v-if="dataWorkspaceOpen"
      class="data-workspace"
      :class="{ maximized: dataWorkspaceMaximized, resizing, 'drag-over': dragOver }"
      :style="panelStyle"
      role="dialog"
      aria-modal="false"
      :aria-label="DATA_COPY.workspaceTitle"
      @dragover="onDragOver"
      @dragleave="onDragLeave"
      @drop="onDrop"
    >
      <div
        class="resize-handle"
        title="拖动调整高度"
        @pointerdown="onResizeStart"
        @pointermove="onResizeMove"
        @pointerup="onResizeEnd"
        @pointercancel="onResizeEnd"
      />
      <header class="ws-header">
        <div class="ws-title-block">
          <span class="ws-title">{{ DATA_COPY.workspaceTitle }}</span>
          <span class="ws-sub">{{ DATA_COPY.workspaceSub }}</span>
        </div>
        <nav class="ws-tabs" role="tablist">
          <button
            v-for="t in tabs"
            :key="t.id"
            type="button"
            class="ws-tab"
            :class="{ active: dataWorkspaceTab === t.id }"
            role="tab"
            :disabled="isTabDisabled(t)"
            :title="isTabDisabled(t) ? '演示账户数据传输受限' : undefined"
            @click="setTab(t.id)"
          >
            {{ t.label }}
          </button>
        </nav>
        <div class="ws-actions">
          <button class="icon-btn" type="button" :title="DATA_COPY.maximize" @click="toggleMax">
            <component
              :is="dataWorkspaceMaximized ? Minimize2 : Maximize2"
              :size="14"
              aria-hidden="true"
            />
          </button>
          <button
            class="icon-btn"
            type="button"
            :title="DATA_COPY.close"
            @click="closeDataWorkspace"
          >
            <X :size="14" aria-hidden="true" />
          </button>
        </div>
      </header>

      <div v-if="importQuota" class="quota-bar">
        <div class="quota-track">
          <div
            class="quota-fill"
            :class="{ warn: quotaWarn }"
            :style="{ width: `${quotaPercent}%` }"
          />
        </div>
        <span class="quota-text">
          {{ formatBytes(importQuota.used_bytes) }} / {{ formatBytes(importQuota.limit_bytes) }}
          <button
            v-if="importQuota.ephemeral_bytes > 0"
            class="link-btn"
            type="button"
            :disabled="quotaLoading"
            @click="onReclaim"
          >
            回收 {{ formatBytes(importQuota.ephemeral_bytes) }}
          </button>
        </span>
      </div>

      <div v-if="demoTransferRestricted" class="demo-banner" role="alert">
        <span class="demo-banner-icon">!</span>
        <span class="demo-banner-text">
          演示账户的数据导入/导出功能受限。如需上传或下载数据，请联系管理员开通权限或升级为标准用户。
        </span>
      </div>

      <div class="ws-body">
        <div v-show="dataWorkspaceTab === 'import'" class="ws-pane">
          <DataImportPanel
            v-if="mountedTabs.has('import')"
            :key="importPanelKey"
            embedded
            :initial-tab="dataWorkspaceImportKind"
            :initial-files="dataWorkspaceSeedFiles"
            @close="closeDataWorkspace"
          />
        </div>
        <div v-show="dataWorkspaceTab === 'export'" class="ws-pane">
          <DataExportPanel v-if="mountedTabs.has('export')" embedded @close="closeDataWorkspace" />
        </div>
        <div v-show="dataWorkspaceTab === 'attributes'" class="ws-pane ws-pane-fill">
          <AttributeTable v-if="mountedTabs.has('attributes')" />
        </div>
        <div v-show="dataWorkspaceTab === 'details'" class="ws-pane ws-pane-fill">
          <LayerDetails v-if="mountedTabs.has('details')" />
        </div>
        <div v-show="dataWorkspaceTab === 'jobs'" class="ws-pane ws-pane-fill">
          <JobsPanel v-if="mountedTabs.has('jobs')" />
        </div>
      </div>
    </aside>
  </Teleport>
</template>

<style scoped>
.data-workspace {
  position: fixed;
  left: 0.75rem;
  right: 0.75rem;
  bottom: 0.55rem;
  z-index: 10030;
  display: flex;
  flex-direction: column;
  min-height: 0;
  border-radius: 0.75rem 0.75rem 0.55rem 0.55rem;
  background: var(--surface-2);
  border: 1px solid var(--border-default);
  box-shadow: 0 18px 48px rgba(1, 8, 16, 0.5);
  color: var(--text-primary);
  overflow: hidden;
  transition:
    border-color 0.2s ease,
    box-shadow 0.2s ease;
}
.data-workspace.drag-over {
  border-color: var(--accent);
  box-shadow:
    0 18px 48px rgba(1, 8, 16, 0.5),
    0 0 0 2px var(--accent-border);
}
.data-workspace.maximized {
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  border-radius: 0;
  z-index: 10080;
}
.resize-handle {
  height: 0.42rem;
  cursor: ns-resize;
  flex: none;
  background: linear-gradient(180deg, var(--accent-surface), transparent);
}
.ws-header {
  display: flex;
  align-items: center;
  gap: 0.65rem;
  flex-shrink: 0;
  padding: 0.45rem 0.7rem 0.4rem;
  border-bottom: 1px solid var(--border-subtle);
}
.ws-title-block {
  display: flex;
  flex-direction: column;
  gap: 0.05rem;
  min-width: 5.5rem;
}
.ws-title {
  font-size: var(--font-size-caption);
  font-weight: 600;
}
.ws-sub {
  font-size: var(--font-size-caption);
  color: var(--text-faint);
}
.ws-tabs {
  display: flex;
  flex: 1 1 auto;
  gap: 0.28rem;
  min-width: 0;
  overflow: auto;
  scrollbar-width: thin;
  scrollbar-color: var(--border-strong) transparent;
}
.ws-tabs::-webkit-scrollbar {
  height: 4px;
}
.ws-tabs::-webkit-scrollbar-thumb {
  background: var(--border-strong);
  border-radius: 999px;
}
.ws-tab {
  border: 1px solid var(--border-default);
  border-radius: 0.4rem;
  padding: 0.28rem 0.58rem;
  background: var(--surface-sunken);
  color: var(--text-secondary);
  cursor: pointer;
  font: inherit;
  font-size: var(--font-size-caption);
  white-space: nowrap;
}
.ws-tab.active {
  color: var(--accent);
  border-color: var(--border-strong);
  background: var(--accent-surface);
}
.ws-tab:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
.ws-tab:disabled:hover {
  background: var(--surface-sunken);
  color: var(--text-secondary);
  border-color: var(--border-default);
}
.demo-banner {
  flex: none;
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.4rem 0.7rem;
  background: var(--warning-surface, rgba(255, 193, 7, 0.12));
  border-bottom: 1px solid var(--warning-border, rgba(255, 193, 7, 0.3));
  font-size: var(--font-size-caption);
  color: var(--warning, #f0a020);
}
.demo-banner-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 1.1rem;
  height: 1.1rem;
  border-radius: 50%;
  background: var(--warning, #f0a020);
  color: var(--surface-1, #fff);
  font-weight: 700;
  font-size: 0.7rem;
  flex: none;
}
.demo-banner-text {
  line-height: 1.4;
}
.ws-actions {
  display: flex;
  gap: 0.28rem;
  margin-left: auto;
}
.icon-btn {
  width: 1.65rem;
  height: 1.65rem;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 1px solid var(--border-strong);
  border-radius: 0.36rem;
  background: var(--surface-1);
  color: var(--text-primary);
  cursor: pointer;
  font-size: var(--font-size-caption);
  line-height: 1;
}
.icon-btn:hover {
  border-color: var(--border-strong);
  color: var(--accent);
}
.ws-body {
  flex: 1 1 auto;
  min-height: 0;
  overflow: hidden;
  padding: 0.55rem 0.75rem 0.7rem;
  display: flex;
  flex-direction: column;
}
.quota-bar {
  flex: none;
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.3rem 0.7rem;
  border-bottom: 1px solid var(--border-subtle);
  font-size: var(--font-size-caption);
  color: var(--text-muted);
}
.quota-track {
  flex: 1;
  height: 0.24rem;
  border-radius: 999px;
  background: var(--border-default);
  overflow: hidden;
}
.quota-fill {
  height: 100%;
  border-radius: 999px;
  background: linear-gradient(90deg, var(--accent), var(--accent));
  transition: width 0.3s ease;
}
.quota-fill.warn {
  background: linear-gradient(90deg, var(--warning), var(--warning));
}
.quota-text {
  white-space: nowrap;
  display: flex;
  align-items: center;
  gap: 0.4rem;
}
.link-btn {
  border: none;
  background: transparent;
  color: var(--accent);
  font: inherit;
  font-size: var(--font-size-caption);
  cursor: pointer;
  padding: 0;
}
.link-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.ws-pane {
  flex: 1 1 auto;
  min-height: 0;
  overflow: auto;
  scrollbar-width: thin;
  scrollbar-color: var(--border-strong) transparent;
}
.ws-pane-fill {
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.ws-pane-fill > :deep(*) {
  flex: 1 1 auto;
  min-height: 0;
}
.ws-pane::-webkit-scrollbar {
  width: 4px;
  height: 4px;
}
.ws-pane::-webkit-scrollbar-thumb {
  background: var(--border-strong);
  border-radius: 999px;
}
</style>
