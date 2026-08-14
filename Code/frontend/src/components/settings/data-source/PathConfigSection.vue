<script setup lang="ts">
/**
 * PathConfigSection — 细分路径配置卡。
 *
 * 数据根 / 产物根 / 静态下载缓存 / 通用缓存目录 / 下载源根。
 * 保存统一走扩展后的 PUT /config/data-source/paths；可选「保存并重启后端」
 * （复用 waitForBackendHealthy 流程），pending_restart 差异高亮。
 */

import { computed, reactive, ref, watch } from 'vue'
import { useSettingsStore } from '../../../stores/settings'
import {
  restartBackendService,
  updateDataSourcePaths,
  waitForBackendHealthy,
} from '../../../services/settings-api'

const settingsStore = useSettingsStore()

interface PathDraft {
  dataRoot: string
  outputRoot: string
  staticCacheRoot: string
  cacheDir: string
  downloadSourceRoot: string
}

const draft = reactive<PathDraft>({
  dataRoot: '',
  outputRoot: '',
  staticCacheRoot: '',
  cacheDir: '',
  downloadSourceRoot: '',
})

const saveBusy = ref(false)
const restartBusy = ref(false)
const statusMsg = ref('')
const errMsg = ref('')

const cfg = computed(() => settingsStore.dataSourceConfig)
const pendingRestart = computed(() => Boolean(cfg.value?.pending_restart))
const uiRestartEnabled = computed(() => cfg.value?.ui_restart_enabled !== false)

const envRows = computed(() => {
  const c = cfg.value
  if (!c) return [] as { label: string; value: string }[]
  return [
    { label: '进程生效数据根', value: c.data_root || '未配置' },
    { label: '进程生效产物根', value: c.output_root || '默认' },
    { label: '进程生效静态缓存', value: c.static_cache_root || '默认（数据根下）' },
    { label: '进程生效缓存目录', value: c.cache_dir || '默认' },
    { label: '进程生效下载源根', value: c.download_source_root || '默认' },
  ]
})

function syncDraft() {
  const c = cfg.value
  if (!c) return
  draft.dataRoot = c.env_data_root || c.data_root || ''
  draft.outputRoot = c.env_output_root || c.output_root || ''
  // 三个细分路径后端不回传 env 值：留空 = 保持现状（PUT 传 null 跳过）；
  // 生效值在下方只读行展示，占位符同步提示。
  draft.staticCacheRoot = ''
  draft.cacheDir = ''
  draft.downloadSourceRoot = ''
}

watch(cfg, syncDraft, { immediate: true })

async function savePaths(andRestart: boolean) {
  const root = draft.dataRoot.trim()
  if (!root) {
    errMsg.value = '请填写数据根目录（绝对路径）'
    return
  }
  if (andRestart) {
    if (!uiRestartEnabled.value) {
      errMsg.value = '当前环境禁止从前端重启后端（BACKEND_UI_RESTART_ENABLED）'
      return
    }
    if (
      !confirm(
        '将保存路径并重启 FastAPI + Celery Worker + Beat（Docker/前端不动）。期间 API 短暂不可用，确认继续？',
      )
    ) {
      return
    }
  }
  saveBusy.value = true
  restartBusy.value = andRestart
  errMsg.value = ''
  statusMsg.value = ''
  try {
    const result = await updateDataSourcePaths({
      data_root: root,
      output_root: draft.outputRoot.trim() || null,
      static_cache_root: draft.staticCacheRoot.trim() || null,
      cache_dir: draft.cacheDir.trim() || null,
      download_source_root: draft.downloadSourceRoot.trim() || null,
    })
    statusMsg.value = result.message
    await settingsStore.loadAll()
    syncDraft()
    if (andRestart) {
      statusMsg.value = '已调度后端重启，等待健康检查…'
      await restartBackendService({})
      const ok = await waitForBackendHealthy({ timeoutMs: 120_000 })
      if (!ok) {
        statusMsg.value = '重启已调度，但在超时内未恢复 /health；请检查 launch 日志'
      } else {
        statusMsg.value = '后端已恢复；正在刷新配置与图层就绪状态…'
        await settingsStore.loadAll()
        syncDraft()
        try {
          const { useLayersStore } = await import('../../../stores/layers')
          await useLayersStore().ensureRuntimeLayerCatalog(true)
        } catch {
          // catalog refresh is best-effort
        }
        statusMsg.value = '路径已生效，后端已重启完成'
      }
    }
  } catch (e) {
    errMsg.value = (e as Error).message
  } finally {
    saveBusy.value = false
    restartBusy.value = false
  }
}
</script>

<template>
  <section class="form-card">
    <h4 class="card-title">
      路径配置
      <span v-if="pendingRestart" class="badge badge-warn" title="已写入 .env，待重启后端生效">
        待重启
      </span>
    </h4>
    <p class="card-hint">
      写入 <code>Code/backend/.env</code>（数据根必填；其余留空 = 沿用默认）。 当前进程生效值需重启
      FastAPI + Worker + Beat。
    </p>

    <div class="form-grid">
      <label class="span-2">
        <span>数据根目录 <em class="req">*</em></span>
        <input v-model="draft.dataRoot" placeholder="例如 I:\Geograph_DataSet" autocomplete="off" />
      </label>
      <label>
        <span>产物输出目录</span>
        <input
          v-model="draft.outputRoot"
          placeholder="留空 = {数据根}/ProjectOutput"
          autocomplete="off"
        />
      </label>
      <label>
        <span>静态下载缓存根</span>
        <input
          v-model="draft.staticCacheRoot"
          :placeholder="
            cfg?.static_cache_root ? `当前 ${cfg.static_cache_root}` : '默认（数据根下）'
          "
          autocomplete="off"
        />
      </label>
      <label>
        <span>通用缓存目录</span>
        <input
          v-model="draft.cacheDir"
          :placeholder="cfg?.cache_dir ? `当前 ${cfg.cache_dir}` : '默认'"
          autocomplete="off"
        />
      </label>
      <label>
        <span>下载源根目录</span>
        <input
          v-model="draft.downloadSourceRoot"
          :placeholder="cfg?.download_source_root ? `当前 ${cfg.download_source_root}` : '默认'"
          autocomplete="off"
        />
      </label>
    </div>

    <div class="env-grid">
      <div v-for="row in envRows" :key="row.label" class="env-row">
        <span class="env-label">{{ row.label }}</span>
        <span class="env-value" :title="row.value">{{ row.value }}</span>
      </div>
    </div>

    <p v-if="errMsg" class="form-error">{{ errMsg }}</p>
    <p v-if="statusMsg" class="form-status">{{ statusMsg }}</p>

    <div class="form-actions">
      <button
        type="button"
        class="btn"
        :disabled="saveBusy || restartBusy"
        @click="savePaths(false)"
      >
        保存路径
      </button>
      <button
        type="button"
        class="btn btn-primary"
        :disabled="saveBusy || restartBusy || !uiRestartEnabled"
        :title="uiRestartEnabled ? '' : 'BACKEND_UI_RESTART_ENABLED 未开启'"
        @click="savePaths(true)"
      >
        {{ restartBusy ? '重启中…' : '保存并重启后端' }}
      </button>
    </div>
  </section>
</template>

<style scoped src="../settings-form.css"></style>
<style scoped>
.card-title {
  margin: 0;
  color: var(--text-strong);
  font-size: var(--font-size-caption);
  font-weight: 600;
  display: flex;
  align-items: center;
  gap: 0.4rem;
}
.card-hint {
  margin: 0;
  color: var(--text-muted);
  font-size: var(--font-size-caption);
  line-height: 1.45;
}
.badge {
  padding: 0.06rem 0.32rem;
  border-radius: 0.24rem;
  font-size: var(--font-size-caption);
}
.badge-warn {
  background: var(--warning-surface);
  color: var(--accent-warm);
}
.req {
  color: var(--danger);
  font-style: normal;
}
.env-grid {
  display: flex;
  flex-direction: column;
  gap: 0.28rem;
}
.env-row {
  display: grid;
  grid-template-columns: 8.5rem 1fr;
  gap: 0.5rem;
  font-size: var(--font-size-caption);
  align-items: center;
}
.env-label {
  color: var(--text-muted);
}
.env-value {
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.form-status {
  margin: 0.4rem 0 0;
  color: var(--success);
  font-size: var(--font-size-caption);
}
</style>
