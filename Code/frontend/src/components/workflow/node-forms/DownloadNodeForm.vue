<script setup lang="ts">
/**
 * DownloadNodeForm.vue
 *
 * 统一下载节点表单入口：根据 node.type 分发到专用子表单。
 *
 *   - download/ssh_sync           → SshSyncForm
 *   - download/nsidc_smap_download → NsidcDownloadForm
 *   - download/gldas_download      → GldasDownloadForm
 *   - download/gldas_nc4_to_mat    → GldasNc4ToMatForm
 *   - download/fy_preprocess       → FyPreprocessForm
 *
 * Props: node (LGraphNodeClass) / readonly (boolean)
 * Emits: update-property (key: string, value: unknown)
 */
import { computed } from 'vue'
import type { LGraphNodeClass } from '../litegraph-setup'
import SshSyncForm from './SshSyncForm.vue'
import NsidcDownloadForm from './NsidcDownloadForm.vue'
import GldasDownloadForm from './GldasDownloadForm.vue'
import GldasNc4ToMatForm from './GldasNc4ToMatForm.vue'
import FyPreprocessForm from './FyPreprocessForm.vue'

const props = defineProps<{
  node: LGraphNodeClass | null
  readonly?: boolean
}>()

const emit = defineEmits<{
  'update-property': [key: string, value: unknown]
}>()

const nodeType = computed(() => props.node?.type ?? '')

const SUBFORM_LABELS: Record<string, string> = {
  'download/ssh_sync': 'SSH 同步',
  'download/nsidc_smap_download': 'NSIDC SMAP 下载',
  'download/gldas_download': 'GLDAS 在线下载',
  'download/gldas_nc4_to_mat': 'GLDAS nc4→mat',
  'download/fy_preprocess': 'FY 预处理',
}

const subLabel = computed(() => SUBFORM_LABELS[nodeType.value] ?? '')

function forward(key: string, value: unknown) {
  emit('update-property', key, value)
}
</script>

<template>
  <div class="download-node-form">
    <div v-if="subLabel" class="subform-badge">{{ subLabel }}</div>

    <SshSyncForm
      v-if="nodeType === 'download/ssh_sync'"
      :node="node"
      :readonly="readonly"
      @update-property="forward"
    />

    <NsidcDownloadForm
      v-else-if="nodeType === 'download/nsidc_smap_download'"
      :node="node"
      :readonly="readonly"
      @update-property="forward"
    />

    <GldasDownloadForm
      v-else-if="nodeType === 'download/gldas_download'"
      :node="node"
      :readonly="readonly"
      @update-property="forward"
    />

    <GldasNc4ToMatForm
      v-else-if="nodeType === 'download/gldas_nc4_to_mat'"
      :node="node"
      :readonly="readonly"
      @update-property="forward"
    />

    <FyPreprocessForm
      v-else-if="nodeType === 'download/fy_preprocess'"
      :node="node"
      :readonly="readonly"
      @update-property="forward"
    />

    <div v-else class="unsupported">未支持的下载节点类型：{{ nodeType || '—' }}</div>
  </div>
</template>

<style scoped>
.download-node-form {
  display: flex;
  flex-direction: column;
}

.subform-badge {
  display: inline-flex;
  align-items: center;
  align-self: flex-start;
  margin-bottom: 0.5rem;
  padding: 0.16rem 0.46rem;
  border-radius: 0.28rem;
  background: var(--accent-surface);
  border: 1px solid var(--border-accent);
  color: var(--accent);
  font-size: var(--font-size-caption);
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

.unsupported {
  padding: 0.62rem 0.52rem;
  border: 1px dashed rgba(255, 138, 138, 0.4);
  border-radius: 0.36rem;
  background: rgba(60, 20, 20, 0.2);
  color: var(--danger);
  font-size: var(--font-size-caption);
  line-height: 1.5;
}
</style>
