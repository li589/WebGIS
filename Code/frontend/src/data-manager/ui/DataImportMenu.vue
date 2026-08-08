<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
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
      <span class="btn-icon" aria-hidden="true">◫</span>
      <span class="btn-label">{{ DATA_COPY.menuLabel }}</span>
      <span class="caret" aria-hidden="true">▾</span>
    </button>

    <Teleport to="body">
      <div
        v-if="menuOpen"
        class="import-dropdown"
        :style="{ top: dropdownPos.top + 'px', left: dropdownPos.left + 'px' }"
        @click.stop
      >
        <button class="dropdown-item" type="button" @click="openImport('vector')">
          <span class="item-icon" aria-hidden="true">⬆</span>
          <span class="item-body">
            <span class="item-title">{{ DATA_COPY.import }}</span>
            <span class="item-desc">矢量 / 栅格 / 文档 · 后端统一解析</span>
          </span>
        </button>
        <button class="dropdown-item" type="button" @click="openExport">
          <span class="item-icon" aria-hidden="true">⬇</span>
          <span class="item-body">
            <span class="item-title">{{ DATA_COPY.export }}</span>
            <span class="item-desc">导出已导入图层</span>
          </span>
        </button>
        <button class="dropdown-item" type="button" @click="openAttributesWorkspace">
          <span class="item-icon" aria-hidden="true">☰</span>
          <span class="item-body">
            <span class="item-title">{{ DATA_COPY.wsAttributes }}</span>
            <span class="item-desc">分页浏览与字段重命名</span>
          </span>
        </button>
        <button class="dropdown-item" type="button" @click="openDetailsWorkspace">
          <span class="item-icon" aria-hidden="true">ℹ</span>
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
        <span class="spinning-icon" aria-hidden="true">↻</span>
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
  gap: 0.24rem;
  border: 1px solid rgba(136, 192, 255, 0.1);
  border-radius: 0.5rem;
  padding: 0.3rem 0.46rem;
  background: rgba(4, 12, 23, 0.6);
  color: #9fb6cc;
  cursor: pointer;
  font: inherit;
  font-size: 0.62rem;
  font-weight: 500;
  white-space: nowrap;
  transition:
    border-color 0.18s ease,
    color 0.18s ease,
    background 0.18s ease;
}

.import-trigger:hover {
  border-color: rgba(90, 213, 255, 0.3);
  color: #5ad5ff;
  background: rgba(10, 132, 255, 0.12);
}

.import-trigger.active {
  border-color: rgba(90, 213, 255, 0.4);
  color: #5ad5ff;
  background: rgba(10, 132, 255, 0.2);
  box-shadow: inset 0 0 0 1px rgba(90, 213, 255, 0.16);
}

.btn-icon {
  font-size: 0.72rem;
  opacity: 0.9;
}
.btn-label {
  font-size: 0.6rem;
}
.caret {
  font-size: 0.52rem;
  opacity: 0.6;
}

.import-spinner {
  position: fixed;
  inset: 0;
  z-index: 200;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(4, 10, 18, 0.4);
  pointer-events: none;
}

.spinner-card {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.4rem;
  padding: 0.8rem 1rem;
  border-radius: 0.6rem;
  background: rgba(8, 18, 33, 0.92);
  border: 1px solid rgba(90, 213, 255, 0.25);
}

.spinning-icon {
  font-size: 1.6rem;
  color: #5ad5ff;
  animation: spin 0.8s linear infinite;
}

.progress-text {
  font-size: 0.68rem;
  color: #a8e8ff;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}
</style>

<style>
/* Teleport 到 body，不能用 scoped */
.import-dropdown {
  position: fixed;
  z-index: 9999;
  display: flex;
  flex-direction: column;
  gap: 0.1rem;
  padding: 0.3rem;
  border-radius: 0.6rem;
  background: rgba(8, 18, 33, 0.96);
  border: 1px solid rgba(136, 192, 255, 0.16);
  box-shadow: 0 12px 36px rgba(1, 8, 16, 0.4);
  min-width: 12.5rem;
}

.import-dropdown .dropdown-item {
  display: flex;
  align-items: center;
  gap: 0.42rem;
  padding: 0.42rem 0.5rem;
  border: none;
  border-radius: 0.42rem;
  background: transparent;
  color: #9fb6cc;
  cursor: pointer;
  font: inherit;
  text-align: left;
  transition:
    background 0.16s ease,
    color 0.16s ease;
}

.import-dropdown .dropdown-item:hover {
  background: rgba(136, 192, 255, 0.1);
  color: #d8e6f5;
}

.import-dropdown .item-icon {
  font-size: 0.8rem;
  flex: none;
}
.import-dropdown .item-body {
  display: flex;
  flex-direction: column;
  gap: 0.08rem;
  min-width: 0;
}
.import-dropdown .item-title {
  font-size: 0.62rem;
  font-weight: 500;
}
.import-dropdown .item-desc {
  font-size: 0.52rem;
  color: #5a7080;
}
.import-dropdown .dropdown-hint {
  margin: 0.2rem 0.35rem 0.15rem;
  padding-top: 0.28rem;
  border-top: 1px solid rgba(136, 192, 255, 0.1);
  font-size: 0.5rem;
  color: #5a7080;
  line-height: 1.35;
}

.import-toast {
  position: fixed;
  top: 4.2rem;
  left: 50%;
  transform: translateX(-50%);
  z-index: 10020;
  max-width: min(36rem, calc(100vw - 2rem));
  padding: 0.42rem 0.72rem;
  border-radius: 0.48rem;
  background: rgba(10, 132, 255, 0.22);
  border: 1px solid rgba(90, 213, 255, 0.35);
  color: #a8e8ff;
  font-size: 0.62rem;
  line-height: 1.4;
  pointer-events: none;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.35);
}

.import-toast.error {
  background: rgba(255, 77, 77, 0.18);
  border-color: rgba(255, 100, 100, 0.35);
  color: #ffb0b0;
}
</style>
