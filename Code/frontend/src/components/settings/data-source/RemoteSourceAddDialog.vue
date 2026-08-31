<script setup lang="ts">
/**
 * RemoteSourceAddDialog — 融合式「添加为可访问远程数据源」对话框（2026-08-25 改版）。
 *
 * 按源能力三形态（plan P1，替代旧的简单表单 + 独立在线检索入口）：
 * 1. searchable 门户：内嵌数据集检索（多选）——API 型自动带链接，无远端路径框；
 * 2. browsable 存储：内嵌 ProfileBrowserDialog 作目录选择器，选中回填路径（可手改）；
 * 3. 仅下载源：只有别名 + 「注册」。
 *
 * 按钮：
 * - 「注册」（常驻）：整源注册（access_mode='site_compatible'，数据可经工作流自动访问）；
 * - 「注册并添加到图层」（仅选了数据集时亮起）：注册 + 按门户→工作流映射自动
 *   提交下载/处理链，产物入图层库（P2；无映射站点隐藏）。
 *
 * 授权语义（用户决策 2026-08-25）：选数据集 = 一键上图的选择记录（不限制
 * 整源访问权）。
 */

import { computed, reactive, ref, watch } from 'vue'
import type {
  PortalCatalogEntry,
  PortalSearchDatasetItem,
  RemoteStorageProfile,
} from '../../../types/api-reexports'
import { searchPortal, registerAndAddRemoteSource } from '../../../services/settings-api'
import { useSettingsStore } from '../../../stores/settings'
import ProfileBrowserDialog from '../remote-storage/ProfileBrowserDialog.vue'
import { PORTAL_WORKFLOW_MAP } from './portal-workflow-map'

const props = defineProps<{
  visible: boolean
  /** 'portal' = 开放门户；'storage' = 存储源 */
  kind: 'portal' | 'storage'
  /** portal_id / profile_id */
  refId: string
  name: string
  /** 检索能力（门户） */
  searchable: boolean
  /** 浏览能力（存储源） */
  browsable: boolean
  /** 存储源协议（决定远端路径框形态） */
  protocol?: string | null
  /** 门户对象（检索用） */
  portal?: PortalCatalogEntry | null
  /** 存储源对象（浏览选择器用） */
  profile?: RemoteStorageProfile | null
}>()

const emit = defineEmits<{
  close: []
  registered: [alias: string]
  'registered-and-added': [alias: string, datasetKeys: string[]]
}>()

const settingsStore = useSettingsStore()

// ── 形态判定 ───────────────────────────────────────────────────────────────

const formKind = computed<'search' | 'browse' | 'plain'>(() => {
  if (props.kind === 'portal') return props.searchable ? 'search' : 'plain'
  return props.browsable ? 'browse' : 'plain'
})

/** 门户→工作流映射（P2）：有映射且（可检索选集 或 映射带默认数据集）才支持一键上图 */
const addLayerMapping = computed(() =>
  props.kind === 'portal' ? PORTAL_WORKFLOW_MAP[props.refId] : undefined,
)
const hasAddToLayerMap = computed(() => Boolean(addLayerMapping.value))
/** 一键上图可用：选了数据集，或映射带默认数据集（无需检索） */
const canAddToLayer = computed(
  () =>
    Boolean(addLayerMapping.value) &&
    (selectedCount.value > 0 || (addLayerMapping.value?.defaultDatasetKeys.length ?? 0) > 0),
)

// ── 注册表单（公共） ─────────────────────────────────────────────────────

const form = reactive({
  alias: '',
  remotePath: '',
})
const busy = ref<'register' | 'register-add' | ''>('')
const errorMsg = ref('')
const okMsg = ref('')

// ── 检索（门户形态） ──────────────────────────────────────────────────────

const searchState = reactive({
  query: '',
  searching: false,
  errorMsg: '',
  items: [] as PortalSearchDatasetItem[],
  count: 0,
})
const selectedKeys = ref(new Set<string>())

// 打开对话框（含首次挂载即 visible）时重置表单
watch(
  () => props.visible,
  (v) => {
    if (v) {
      form.alias = props.refId
      form.remotePath = ''
      errorMsg.value = ''
      okMsg.value = ''
      selectedKeys.value.clear()
      searchState.query = ''
      searchState.items = []
      searchState.errorMsg = ''
      searchState.count = 0
    }
  },
  { immediate: true },
)

async function runSearch() {
  if (!props.portal || !searchState.query.trim()) return
  searchState.searching = true
  searchState.errorMsg = ''
  try {
    const res = await searchPortal(props.portal.portal_id, searchState.query.trim())
    searchState.items = res.items ?? []
    searchState.count = res.count ?? 0
    if (!searchState.items.length) {
      searchState.errorMsg = '无结果（检查关键词，如 GLDAS、SMAP L4、Sentinel）'
    }
  } catch (e) {
    searchState.errorMsg = (e as Error).message
    searchState.items = []
  } finally {
    searchState.searching = false
  }
}

function toggleSelect(item: PortalSearchDatasetItem) {
  const key = item.dataset_key || item.title
  if (selectedKeys.value.has(key)) selectedKeys.value.delete(key)
  else selectedKeys.value.add(key)
  // 触发响应式更新（Set 原地变更）
  selectedKeys.value = new Set(selectedKeys.value)
}

function isSelected(item: PortalSearchDatasetItem): boolean {
  return selectedKeys.value.has(item.dataset_key || item.title)
}

const selectedCount = computed(() => selectedKeys.value.size)

// ── 目录选择（存储源形态） ────────────────────────────────────────────────

const browserVisible = ref(false)

function openBrowser() {
  browserVisible.value = true
}

function onBrowserPathChosen(path: string) {
  form.remotePath = path
  browserVisible.value = false
}

// ── 注册 ──────────────────────────────────────────────────────────────────

async function doRegister(addToLayer: boolean) {
  const alias = form.alias.trim()
  if (!alias) {
    errorMsg.value = '请填写别名 ID（唯一，供下载节点引用）'
    return
  }
  if (addToLayer && !canAddToLayer.value) return
  busy.value = addToLayer ? 'register-add' : 'register'
  errorMsg.value = ''
  okMsg.value = ''
  // 一键上图目标数据集：用户选集优先；不可检索门户用映射默认数据集
  const layerDatasetKeys =
    selectedCount.value > 0
      ? [...selectedKeys.value]
      : (addLayerMapping.value?.defaultDatasetKeys ?? [])
  try {
    if (addToLayer) {
      // 原子端点（2026-08-25 Wave 2）：注册 site_compatible + grants 记录
      // + 工作流编排提示（workflow_hint：节点类型/建议参数）一步完成。
      // Wave 3 接全自动「下载→预处理→入图层库」链（auto_chain_ready）。
      const resp = await registerAndAddRemoteSource({
        alias,
        kind: props.kind === 'portal' ? 'portal' : 'storage_profile',
        ref_id: props.refId,
        display_name: props.name,
        remote_path: form.remotePath.trim(),
        dataset_keys: layerDatasetKeys,
      })
      const hint = resp.workflow_hint
      emit('registered-and-added', alias, layerDatasetKeys)
      if (resp.run_id) {
        // 自动链已触发（Wave 3）：工作流后台执行「下载→预处理→烘焙→入图层库」
        okMsg.value = `${resp.auto_chain_message || '已自动提交图层工作流'}（运行 ID: ${resp.run_id.slice(0, 8)}…，可在「工作流」面板查看进度）`
      } else if (hint) {
        const paramPreview = Object.entries(hint.params ?? {})
          .slice(0, 4)
          .map(([k, v]) => `${k}=${String(v)}`)
          .join(' ')
        okMsg.value =
          resp.auto_chain_message ||
          `已注册并记录 ${layerDatasetKeys.length} 个数据集（${layerDatasetKeys.join('、')}）——到「工作流」添加 ${hint.node_type} 节点运行下载链即可上图（参数建议：${paramPreview}）`
      } else {
        okMsg.value = '已注册——数据可经工作流自动访问'
      }
      return
    }
    await settingsStore.saveRemoteSource(alias, {
      kind: props.kind === 'portal' ? 'portal' : 'storage_profile',
      ref_id: props.refId,
      remote_path: form.remotePath.trim(),
      display_name: props.name,
      cache_policy: 'standard',
      // 2026-08-25 决策：整源注册（兼容模式 legacy 弃用）
      access_mode: 'site_compatible',
      archived: false,
    })
    emit('registered', alias)
    okMsg.value = selectedCount.value
      ? `已注册；已选 ${selectedCount.value} 个数据集仅记录（可稍后一键上图）`
      : '已注册为整源——数据可经工作流自动访问'
    emit('close')
  } catch (e) {
    errorMsg.value = (e as Error).message
  } finally {
    busy.value = ''
  }
}
</script>

<template>
  <Teleport to="body">
    <div v-if="visible" class="rsa-overlay" @click.self="emit('close')">
      <div class="rsa-dialog" role="dialog" aria-modal="true">
        <div class="rsa-header">
          <span class="rsa-title">注册「{{ name }}」为可访问远程数据源</span>
          <button type="button" class="rsa-close" aria-label="关闭" @click="emit('close')">
            ×
          </button>
        </div>

        <div class="rsa-body">
          <!-- ── 形态 1：内嵌检索（门户） ── -->
          <template v-if="formKind === 'search'">
            <p class="rsa-hint">
              检索并勾选数据集后可「注册并添加到图层」；不选则注册整源——所有数据均可经工作流自动访问。
            </p>
            <div class="rsa-searchbar">
              <input
                v-model="searchState.query"
                placeholder="数据集关键词（如 GLDAS、SMAP L4、Sentinel-2）"
                @keyup.enter="runSearch"
              />
              <button
                type="button"
                class="btn primary"
                :disabled="searchState.searching"
                @click="runSearch"
              >
                {{ searchState.searching ? '检索中…' : '检索' }}
              </button>
            </div>
            <div class="rsa-list">
              <div v-if="searchState.errorMsg" class="rsa-state error">
                {{ searchState.errorMsg }}
              </div>
              <div v-else-if="!searchState.items.length" class="rsa-state">
                输入关键词检索数据集
              </div>
              <div v-else class="rsa-meta">
                共 {{ searchState.count }} 个数据集，展示前 {{ searchState.items.length }} 个
              </div>
              <div
                v-for="(row, i) in searchState.items"
                :key="i"
                class="rsa-row"
                :class="{ selected: isSelected(row) }"
                @click="toggleSelect(row)"
              >
                <input type="checkbox" :checked="isSelected(row)" @click.stop="toggleSelect(row)" />
                <div class="rsa-row-main">
                  <span class="rsa-row-title">{{ row.title || row.dataset_key }}</span>
                  <code class="rsa-row-id">{{ row.dataset_key }}</code>
                </div>
                <p v-if="row.description" class="rsa-row-desc">{{ row.description }}</p>
                <div class="rsa-row-meta">
                  <span v-if="row.time_start"
                    >{{ row.time_start }}{{ row.time_end ? ` ~ ${row.time_end}` : '' }}</span
                  >
                  <span v-if="row.extra && row.extra.count"> · {{ row.extra.count }} 个产品</span>
                </div>
              </div>
            </div>
          </template>

          <!-- ── 形态 2：目录选择（存储源） ── -->
          <template v-else-if="formKind === 'browse'">
            <p class="rsa-hint">
              可浏览选择子目录（默认整源）；选中目录注册后，工作流下载将限定在该路径下。
            </p>
            <div class="rsa-browse-row">
              <input v-model="form.remotePath" placeholder="留空 = 整源；或点击右侧按钮浏览选择" />
              <button type="button" class="btn" @click="openBrowser">浏览目录…</button>
            </div>
          </template>

          <!-- ── 形态 3：仅下载源 ── -->
          <p v-else class="rsa-hint">
            该源不支持检索/浏览，注册为整源后数据可经工作流下载节点自动访问。
          </p>

          <!-- ── 公共注册字段 ── -->
          <label class="rsa-field">
            <span>别名 ID（唯一，供下载节点引用）<em class="req">*</em></span>
            <input v-model="form.alias" placeholder="例如 nas-fy-2025" />
          </label>
        </div>

        <p v-if="errorMsg" class="rsa-msg error">{{ errorMsg }}</p>
        <p v-else-if="okMsg" class="rsa-msg ok">{{ okMsg }}</p>

        <div class="rsa-actions">
          <button
            v-if="hasAddToLayerMap"
            type="button"
            class="btn primary"
            :disabled="busy !== '' || !canAddToLayer"
            :title="!canAddToLayer ? '先检索并勾选数据集' : ''"
            @click="doRegister(true)"
          >
            {{
              busy === 'register-add'
                ? '添加中…'
                : `注册并添加到图层${
                    selectedCount
                      ? `（${selectedCount} 个）`
                      : canAddToLayer
                        ? '（默认数据集）'
                        : ''
                  }`
            }}
          </button>
          <button type="button" class="btn" :disabled="busy !== ''" @click="doRegister(false)">
            {{ busy === 'register' ? '保存中…' : '注册' }}
          </button>
        </div>
      </div>
    </div>
  </Teleport>

  <!-- 存储源目录选择器（复用浏览对话框，picker 模式） -->
  <ProfileBrowserDialog
    :visible="browserVisible"
    :profile="profile ?? null"
    picker
    @close="browserVisible = false"
    @path-chosen="onBrowserPathChosen"
  />
</template>

<style scoped src="../settings-form.css"></style>
<style scoped>
.rsa-overlay {
  position: fixed;
  inset: 0;
  z-index: 1100;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--surface-raised);
}
.rsa-dialog {
  width: min(44rem, 92vw);
  max-height: 86vh;
  display: flex;
  flex-direction: column;
  border-radius: 0.6rem;
  border: 1px solid var(--border-default);
  background: var(--surface-2);
  box-shadow: 0 18px 48px rgba(1, 8, 16, 0.4);
  overflow: hidden;
}
.rsa-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
  padding: 0.55rem 0.72rem;
  border-bottom: 1px solid var(--border-subtle);
}
.rsa-title {
  color: var(--text-strong);
  font-size: var(--font-size-caption);
  font-weight: 600;
}
.rsa-close {
  width: 1.5rem;
  height: 1.5rem;
  border: none;
  border-radius: 0.4rem;
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
  font-size: 1rem;
}
.rsa-close:hover {
  background: var(--border-subtle);
}
.rsa-body {
  flex: 1;
  min-height: 8rem;
  overflow-y: auto;
  padding: 0.55rem 0.72rem;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}
.rsa-hint {
  margin: 0;
  color: var(--text-muted);
  font-size: var(--font-size-caption);
  line-height: 1.5;
}
.rsa-searchbar {
  display: flex;
  gap: 0.4rem;
}
.rsa-searchbar input,
.rsa-browse-row input {
  flex: 1;
  border: 1px solid var(--border-default);
  border-radius: 0.36rem;
  background: var(--surface-1);
  color: var(--text-strong);
  font-size: var(--font-size-caption);
  padding: 0.32rem 0.44rem;
}
.rsa-browse-row {
  display: flex;
  gap: 0.4rem;
}
.rsa-list {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
  max-height: 22rem;
  overflow-y: auto;
}
.rsa-state {
  padding: 1.2rem 0;
  text-align: center;
  color: var(--text-disabled);
  font-size: var(--font-size-caption);
}
.rsa-state.error {
  color: var(--danger);
}
.rsa-meta {
  color: var(--text-disabled);
  font-size: var(--font-size-caption);
}
.rsa-row {
  display: flex;
  gap: 0.45rem;
  padding: 0.42rem 0.5rem;
  border-radius: 0.4rem;
  border: 1px solid var(--border-subtle);
  background: var(--surface-sunken);
  cursor: pointer;
}
.rsa-row:hover {
  border-color: var(--accent-border);
}
.rsa-row.selected {
  border-color: var(--accent);
  background: var(--accent-surface);
}
.rsa-row-main {
  display: flex;
  align-items: baseline;
  gap: 0.45rem;
  flex-wrap: wrap;
}
.rsa-row-title {
  color: var(--text-strong);
  font-size: var(--font-size-caption);
  font-weight: 600;
}
.rsa-row-id {
  color: var(--accent-strong);
  font-size: var(--font-size-caption);
}
.rsa-row-desc {
  margin: 0;
  color: var(--text-muted);
  font-size: var(--font-size-caption);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.rsa-row-meta {
  color: var(--text-disabled);
  font-size: var(--font-size-caption);
}
.rsa-field {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}
.rsa-field span {
  color: var(--text-strong);
  font-size: var(--font-size-caption);
}
.rsa-field input {
  border: 1px solid var(--border-default);
  border-radius: 0.36rem;
  background: var(--surface-1);
  color: var(--text-strong);
  font-size: var(--font-size-caption);
  padding: 0.32rem 0.44rem;
}
.req {
  color: var(--danger);
  font-style: normal;
}
.rsa-msg {
  margin: 0;
  padding: 0.4rem 0.72rem;
  border-top: 1px solid var(--border-subtle);
  font-size: var(--font-size-caption);
}
.rsa-msg.error {
  color: var(--danger);
}
.rsa-msg.ok {
  color: var(--accent-warm);
}
.rsa-actions {
  display: flex;
  gap: 0.45rem;
  justify-content: flex-end;
  padding: 0.55rem 0.72rem;
  border-top: 1px solid var(--border-subtle);
}
</style>
