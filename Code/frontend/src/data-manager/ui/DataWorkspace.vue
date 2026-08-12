<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
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
  type DataWorkspaceTab,
} from '../core/workspace-store'
import { DATA_COPY } from '../../ui-copy'

const tabs: Array<{ id: DataWorkspaceTab; label: string }> = [
  { id: 'import', label: DATA_COPY.wsImport },
  { id: 'export', label: DATA_COPY.wsExport },
  { id: 'attributes', label: DATA_COPY.wsAttributes },
  { id: 'details', label: DATA_COPY.wsDetails },
  { id: 'jobs', label: DATA_COPY.wsJobs },
]

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
</script>

<template>
  <Teleport to="body">
    <aside
      v-if="dataWorkspaceOpen"
      class="data-workspace"
      :class="{ maximized: dataWorkspaceMaximized, resizing }"
      :style="panelStyle"
      role="dialog"
      aria-modal="false"
      :aria-label="DATA_COPY.workspaceTitle"
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
            @click="setTab(t.id)"
          >
            {{ t.label }}
          </button>
        </nav>
        <div class="ws-actions">
          <button class="icon-btn" type="button" :title="DATA_COPY.maximize" @click="toggleMax">
            {{ dataWorkspaceMaximized ? '❐' : '□' }}
          </button>
          <button
            class="icon-btn"
            type="button"
            :title="DATA_COPY.close"
            @click="closeDataWorkspace"
          >
            ✕
          </button>
        </div>
      </header>

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
  background: rgba(8, 17, 31, 0.97);
  border: 1px solid rgba(136, 192, 255, 0.18);
  box-shadow: 0 18px 48px rgba(1, 8, 16, 0.5);
  color: var(--text-primary);
  overflow: hidden;
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
  background: linear-gradient(180deg, rgba(90, 213, 255, 0.18), transparent);
}
.ws-header {
  display: flex;
  align-items: center;
  gap: 0.65rem;
  flex-shrink: 0;
  padding: 0.45rem 0.7rem 0.4rem;
  border-bottom: 1px solid rgba(136, 192, 255, 0.1);
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
  color: #6a8094;
}
.ws-tabs {
  display: flex;
  flex: 1 1 auto;
  gap: 0.28rem;
  min-width: 0;
  overflow: auto;
  scrollbar-width: thin;
  scrollbar-color: rgba(90, 213, 255, 0.35) transparent;
}
.ws-tabs::-webkit-scrollbar {
  height: 4px;
}
.ws-tabs::-webkit-scrollbar-thumb {
  background: rgba(90, 213, 255, 0.35);
  border-radius: 999px;
}
.ws-tab {
  border: 1px solid rgba(136, 192, 255, 0.12);
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
  border-color: rgba(90, 213, 255, 0.35);
  background: rgba(10, 132, 255, 0.16);
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
  border: 1px solid rgba(136, 192, 255, 0.2);
  border-radius: 0.36rem;
  background: rgba(4, 12, 23, 0.7);
  color: var(--text-primary);
  cursor: pointer;
  font-size: var(--font-size-caption);
  line-height: 1;
}
.icon-btn:hover {
  border-color: rgba(90, 213, 255, 0.4);
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
.ws-pane {
  flex: 1 1 auto;
  min-height: 0;
  overflow: auto;
  scrollbar-width: thin;
  scrollbar-color: rgba(90, 213, 255, 0.35) transparent;
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
  background: rgba(90, 213, 255, 0.35);
  border-radius: 999px;
}
</style>
