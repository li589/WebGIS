<script setup lang="ts">
/**
 * DownloadNodeForm.vue
 *
 * 统一下载节点表单入口：根据 node.type 分发到专用子表单。
 *
 *   - download/ssh_sync           → SshSyncForm
 *   - download/http_open_data     → HttpOpenDataForm
 *   - download/cmr_search         → CmrSearchForm
 *   - download/cds_download       → CdsDownloadForm
 *   - download/nomads_grib_download → NomadsGribDownloadForm
 *   - download/cdse_download      → CdseDownloadForm
 *   - download/nsidc_smap_download → NsidcDownloadForm
 *   - download/gldas_download      → GldasDownloadForm
 *   - download/gldas_nc4_to_mat    → GldasNc4ToMatForm
 *   - download/fy_preprocess       → FyPreprocessForm
 *   - download/fy_download         → FyDownloadForm
 *
 * Props: node (LGraphNodeClass) / readonly (boolean)
 * Emits: update-property (key: string, value: unknown)
 */
import { computed } from 'vue'
import type { LGraphNodeClass } from '../litegraph-setup'
import SshSyncForm from './SshSyncForm.vue'
import HttpOpenDataForm from './HttpOpenDataForm.vue'
import CmrSearchForm from './CmrSearchForm.vue'
import CdsDownloadForm from './CdsDownloadForm.vue'
import NomadsGribDownloadForm from './NomadsGribDownloadForm.vue'
import CdseDownloadForm from './CdseDownloadForm.vue'
import NsidcDownloadForm from './NsidcDownloadForm.vue'
import GldasDownloadForm from './GldasDownloadForm.vue'
import GldasNc4ToMatForm from './GldasNc4ToMatForm.vue'
import FyPreprocessForm from './FyPreprocessForm.vue'
import FyDownloadForm from './FyDownloadForm.vue'

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
  'download/http_open_data': '门户数据下载',
  'download/cmr_search': 'CMR Granule 检索',
  'download/cds_download': 'CDS 再分析下载',
  'download/nomads_grib_download': 'NOMADS GRIB2 下载',
  'download/cdse_download': 'CDSE 产品下载',
  'download/nsidc_smap_download': 'NSIDC SMAP 下载',
  'download/gldas_download': 'GLDAS 在线下载',
  'download/gldas_nc4_to_mat': 'GLDAS nc4→mat',
  'download/fy_preprocess': 'FY 预处理',
  'download/fy_download': '风云卫星下载',
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

    <HttpOpenDataForm
      v-else-if="nodeType === 'download/http_open_data'"
      :node="node"
      :readonly="readonly"
      @update-property="forward"
    />

    <CmrSearchForm
      v-else-if="nodeType === 'download/cmr_search'"
      :node="node"
      :readonly="readonly"
      @update-property="forward"
    />

    <CdsDownloadForm
      v-else-if="nodeType === 'download/cds_download'"
      :node="node"
      :readonly="readonly"
      @update-property="forward"
    />

    <NomadsGribDownloadForm
      v-else-if="nodeType === 'download/nomads_grib_download'"
      :node="node"
      :readonly="readonly"
      @update-property="forward"
    />

    <CdseDownloadForm
      v-else-if="nodeType === 'download/cdse_download'"
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

    <FyDownloadForm
      v-else-if="nodeType === 'download/fy_download'"
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
