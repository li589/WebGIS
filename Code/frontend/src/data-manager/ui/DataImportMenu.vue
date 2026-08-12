<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { Table2, ChevronDown, ChevronUp, Menu, Info, RefreshCw } from '../../components/ui/icons'
import DataWorkspace from './DataWorkspace.vue'
import {
  dataWorkspaceOpen,
  openDataWorkspace,
  pendingOpenExport,
  pendingOpenImport,
  useDataImportFlow,
} from '../core/workspace-store'
import { DATA_COPY } from '../../ui-copy'
import { useAuthStore } from '../../stores/auth'

const authStore = useAuthStore()

const { importing, importMsg, importError, uploadProgress, processFiles } = useDataImportFlow()

const menuOpen = ref(false)
const triggerRef = ref<HTMLButtonElement | null>(null)
const dropdownPos = ref({ top: 0, left: 0 })

function toggleMenu() {
  if (!menuOpen.value && triggerRef.value) {
    const rect = triggerRef.value.getBoundingClientRect()
    dropdownPos.value = { top: rect.bottom + 4, left: rect.left }
  }
  menuOpen.value = !menuOpen.value
}

function closeMenu() {
  menuOpen.value = false
}

function openImport(tab: 'vector' | 'raster' | 'document' = 'vector', files?: File[]) {
  closeMenu()
  openDataWorkspace({ tab: 'import', importKind: tab, files })
}

function openExport() {
  closeMenu()
  openDataWorkspace({ tab: 'export' })
}

function openAttributesWorkspace() {
  closeMenu()
  openDataWorkspace({ tab: 'attributes' })
}

function openDetailsWorkspace() {
  closeMenu()
  openDataWorkspace({ tab: 'details' })
}

watch(pendingOpenImport, (req) => {
  if (!req) return
  openImport(req.tab, req.files)
  pendingOpenImport.value = null
})

watch(pendingOpenExport, (open) => {
  if (!open) return
  openExport()
  pendingOpenExport.value = false
})

function handleDocumentClick(e: MouseEvent) {
  if (!menuOpen.value) return
  const target = e.target as Node
  if (triggerRef.value && triggerRef.value.contains(target)) return
  const dropdown = document.querySelector('.import-dropdown')
  if (dropdown && dropdown.contains(target)) return
  closeMenu()
}

watch(menuOpen, (open) => {
  if (open) {
    document.addEventListener('click', handleDocumentClick, { capture: true })
  } else {
    document.removeEventListener('click', handleDocumentClick, { capture: true })
  }
})

onBeforeUnmount(() => {
  document.removeEventListener('click', handleDocumentClick, { capture: true })
})

defineExpose({ processFiles })

const progressLabel = computed(() =>
  uploadProgress.value == null ? null : `${Math.round(uploadProgress.value * 100)}%`,
)
</script>

<template>
  <div class="data-import-menu">
    <button
      ref="triggerRef"
      class="import-trigger"
      :class="{ active: menuOpen || dataWorkspaceOpen }"
      type="button"
      :disabled="!authStore.canWrite"
      :title="authStore.canWrite ? DATA_COPY.menuTitle : '只读账户无法导入/导出数据'"
      @click="toggleMenu"
    >
      <Table2 :size="14" class="btn-icon" aria-hidden="true" />
      <span class="btn-label">{{ DATA_COPY.menuLabel }}</span>
      <ChevronDown :size="14" class="caret" aria-hidden="true" />
    </button>

    <Teleport to="body">
      <div
        v-if="menuOpen"
        class="import-dropdown"
        :style="{ top: dropdownPos.top + 'px', left: dropdownPos.left + 'px' }"
        @click.stop
      >
        <button class="dropdown-item" type="button" @click="openImport('vector')">
          <ChevronUp :size="14" class="item-icon" aria-hidden="true" />
          <span class="item-body">
            <span class="item-title">{{ DATA_COPY.import }}</span>
            <span class="item-desc">矢量 / 栅格 / 文档 · 后端统一解析</span>
          </span>
        </button>
        <button class="dropdown-item" type="button" @click="openExport">
          <ChevronDown :size="14" class="item-icon" aria-hidden="true" />
          <span class="item-body">
            <span class="item-title">{{ DATA_COPY.export }}</span>
            <span class="item-desc">导出已导入图层</span>
          </span>
        </button>
        <button class="dropdown-item" type="button" @click="openAttributesWorkspace">
          <Menu :size="14" class="item-icon" aria-hidden="true" />
          <span class="item-body">
            <span class="item-title">{{ DATA_COPY.wsAttributes }}</span>
            <span class="item-desc">分页浏览与字段重命名</span>
          </span>
        </button>
        <button class="dropdown-item" type="button" @click="openDetailsWorkspace">
          <Info :size="14" class="item-icon" aria-hidden="true" />
          <span class="item-body">
            <span class="item-title">{{ DATA_COPY.wsDetails }}</span>
            <span class="item-desc">元数据 · 样式 · 删除</span>
          </span>
        </button>
        <p class="dropdown-hint">提示：也可直接把文件拖到地图上导入</p>
      </div>
    </Teleport>

    <Teleport to="body">
      <div v-if="importMsg" class="import-toast" :class="{ error: importError }" role="status">
        {{ importMsg }}
      </div>
    </Teleport>

    <div v-if="importing" class="import-spinner">
      <div class="spinner-card">
        <RefreshCw :size="20" class="spinning-icon" aria-hidden="true" />
        <span v-if="progressLabel" class="progress-text">{{ progressLabel }}</span>
      </div>
    </div>

    <DataWorkspace />
  </div>
</template>

<style scoped>
.data-import-menu {
  position: relative;
  display: inline-flex;
  align-items: center;
}

.import-trigger {
  position: relative;
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  height: 30px;
  padding: 0 var(--space-3);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-md);
  background: var(--surface-sunken);
  color: var(--text-secondary);
  cursor: pointer;
  font-family: inherit;
  font-size: var(--font-size-caption);
  font-weight: var(--font-weight-medium);
  white-space: nowrap;
  transition:
    background-color var(--motion-fast) var(--ease-standard),
    border-color var(--motion-fast) var(--ease-standard),
    color var(--motion-fast) var(--ease-standard),
    box-shadow var(--motion-fast) var(--ease-standard);
}

.import-trigger:hover:not(:disabled) {
  background: var(--surface-hover);
  border-color: var(--border-strong);
  color: var(--accent);
  box-shadow: var(--elevation-1);
}

.import-trigger.active {
  background: var(--accent-surface);
  border-color: var(--border-accent);
  color: var(--accent);
  box-shadow: inset 0 0 0 1px var(--border-accent);
}

.import-trigger:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.import-trigger:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}

.btn-icon {
  font-size: 14px;
  opacity: 0.9;
  line-height: 1;
}
.btn-label {
  font-size: var(--font-size-caption);
  line-height: 1;
}
.caret {
  font-size: var(--font-size-caption);
  opacity: 0.6;
  line-height: 1;
}

.import-spinner {
  position: fixed;
  inset: 0;
  z-index: 200;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--surface-raised);
  pointer-events: auto;
}

.spinner-card {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.4rem;
  padding: 0.8rem 1rem;
  border-radius: 0.6rem;
  background: var(--surface-1);
  border: 1px solid var(--border-accent);
}

.spinning-icon {
  font-size: 1.6rem;
  color: var(--accent);
  animation: spin 0.8s linear infinite;
}

.progress-text {
  font-size: var(--font-size-caption);
  color: var(--accent);
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}
</style>

<style>
/* Teleport 到 body，不能用 scoped，使用设计 token 保持一致性 */
.import-dropdown {
  position: fixed;
  z-index: 9999;
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 6px;
  border-radius: 10px;
  background: var(--surface-2);
  border: 1px solid var(--accent-surface);
  box-shadow: 0 12px 36px rgba(1, 8, 16, 0.45);
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
  min-width: 14rem;
}

.import-dropdown .dropdown-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  font: inherit;
  text-align: left;
  transition:
    background 0.15s ease,
    color 0.15s ease;
}

.import-dropdown .dropdown-item:hover {
  background: var(--accent-surface);
  color: var(--text-primary);
}

.import-dropdown .item-icon {
  font-size: 14px;
  color: var(--accent);
  flex: none;
  opacity: 0.8;
}
.import-dropdown .item-body {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}
.import-dropdown .item-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-primary);
}
.import-dropdown .item-desc {
  font-size: 12px;
  color: var(--text-muted);
  line-height: 1.4;
}
.import-dropdown .dropdown-hint {
  margin: 4px 8px 2px;
  padding-top: 8px;
  border-top: 1px solid var(--accent-surface);
  font-size: 12px;
  color: var(--text-faint);
  line-height: 1.4;
}

.import-toast {
  position: fixed;
  top: 4.5rem;
  left: 50%;
  transform: translateX(-50%);
  z-index: 10020;
  max-width: min(36rem, calc(100vw - 2rem));
  padding: 8px 16px;
  border-radius: 6px;
  background: var(--accent-surface);
  border: 1px solid var(--accent-border);
  color: var(--accent);
  font-size: 12px;
  font-weight: 500;
  line-height: 1.4;
  pointer-events: none;
  box-shadow: 0 8px 24px var(--surface-sunken);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
}

.import-toast.error {
  background: var(--danger-surface);
  border-color: var(--danger-border);
  color: var(--danger);
}
</style>
