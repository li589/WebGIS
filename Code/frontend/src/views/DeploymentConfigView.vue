<script setup lang="ts">
/**
 * DeploymentConfigView — 部署与数据源配置中心（admin 专属路由 /deployment）。
 *
 * 真源：Code/backend/deployment.config.json（GET /config/deployment 三方对比）。
 * 三步状态机：editing → previewing（diff+errors/warnings）→ applying（PUT 原子应用）。
 * 保存后按 restart_level 引导：restart-backend 可页面内重启进程组；
 * restart-full（Docker 相关键）须在服务器执行 launch.py restart。
 * 注意：PUT 对 json 为全量期望态写入，本页每次提交完整表单（空 = 未设置）。
 *
 * 超长值处理：展示位统一用 CodeValue（省略→展开→复制）；
 * 输入位：路径/URL/长文本支持 input ↔ textarea 展开编辑，草稿改动有角标与一键还原。
 */

import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'

import {
  RefreshCw,
  Undo2,
  Download,
  Lock,
  AlertTriangle,
  ChevronDown,
  ChevronUp,
  Eye,
  EyeOff,
  ClipboardCheck,
} from '../components/ui/icons'
import CodeValue from '../components/ui/CodeValue.vue'
import {
  deploymentConfigExportUrl,
  getDeploymentConfig,
  previewDeploymentConfig,
  restartBackendService,
  updateDeploymentConfig,
  waitForBackendHealthy,
} from '../services/settings-api'
import type {
  DeploymentConfigPreviewResponse,
  DeploymentConfigStatus,
  DeploymentConfigUpdateRequest,
  DeploymentKeyValueStatus,
} from '../types/api-reexports'

const router = useRouter()

const status = ref<DeploymentConfigStatus | null>(null)
const loading = ref(false)
const loadError = ref('')
const notes = ref('')

/** 编辑草稿：键 `${group}.${key}` → 值（空 = 未设置；number 输入为数值）。 */
const draft = reactive<Record<string, string | number>>({})

type Mode = 'editing' | 'previewing'
const mode = ref<Mode>('editing')
const previewResult = ref<DeploymentConfigPreviewResponse | null>(null)
const previewBusy = ref(false)
const saveBusy = ref(false)
const restartBusy = ref(false)
const actionMessage = ref('')
const actionError = ref('')

/** 分组折叠态（默认全展开；折叠以便复查长页时收窄）。 */
const collapsedGroups = reactive(new Set<string>())
/** 展开为多行编辑的字段 id 集合（超长路径/URL）。 */
const expandedFields = reactive(new Set<string>())
/** 明文显示的密码字段 id 集合。 */
const revealedPasswords = reactive(new Set<string>())

const RESTART_LABELS: Record<string, string> = {
  'restart-backend': '重启后端',
  'restart-full': '全量重启',
}

const LEVEL_OPTIONS = ['DEBUG', 'INFO', 'WARNING', 'ERROR'] as const

/** 保持后端 GROUP_ORDER 展示顺序。 */
const GROUP_ORDER = ['data', 'runtime', 'caches', 'imports', 'docker'] as const

const groupSections = computed<
  Array<{ group: string; label: string; keys: DeploymentKeyValueStatus[] }>
>(() => {
  const s = status.value
  if (!s) return []
  const byGroup = new Map<string, DeploymentKeyValueStatus[]>()
  for (const k of s.keys) {
    const list = byGroup.get(k.group) ?? []
    list.push(k)
    byGroup.set(k.group, list)
  }
  const ordered = [
    ...GROUP_ORDER,
    ...[...byGroup.keys()].filter((g) => !(GROUP_ORDER as readonly string[]).includes(g)),
  ]
  return ordered
    .filter((g) => byGroup.has(g))
    .map((g) => {
      const keys = byGroup.get(g) ?? []
      return { group: g, label: keys[0]?.group_label ?? g, keys }
    })
})

const pendingRestart = computed(() => Boolean(status.value?.pending_restart))

/** 字段基线值：敏感键不回填，其余为 json 真源值（空 = 未设置）。 */
function baselineValue(k: DeploymentKeyValueStatus): string {
  return k.sensitive ? '' : k.config_value
}

function isFieldChanged(k: DeploymentKeyValueStatus): boolean {
  const current = String(draft[fieldId(k)] ?? '').trim()
  return current !== baselineValue(k).trim()
}

/** 全表草稿改动计数（含 notes 未计入，仅键值）。 */
const changedCount = computed(() => {
  const s = status.value
  if (!s) return 0
  return s.keys.filter((k) => isFieldChanged(k)).length
})

function changedCountForGroup(group: string): number {
  const s = status.value
  if (!s) return 0
  return s.keys.filter((k) => k.group === group && isFieldChanged(k)).length
}

function fieldId(k: DeploymentKeyValueStatus): string {
  return `${k.group}.${k.key}`
}

function syncDraftFromStatus() {
  const s = status.value
  if (!s) return
  for (const k of s.keys) {
    // 敏感值后端恒脱敏（••••）：绝不回填，避免把掩码当新值写回。
    draft[fieldId(k)] = k.sensitive ? '' : k.config_value
  }
  notes.value = s.notes ?? ''
  expandedFields.clear()
  revealedPasswords.clear()
}

async function loadStatus(quiet = false) {
  if (!quiet) {
    loading.value = true
    loadError.value = ''
  }
  try {
    status.value = await getDeploymentConfig()
    syncDraftFromStatus()
    mode.value = 'editing'
    previewResult.value = null
  } catch (e) {
    loadError.value = (e as Error).message
  } finally {
    loading.value = false
  }
}

function buildPayload(): DeploymentConfigUpdateRequest {
  const groups: Record<string, Record<string, string | number>> = {}
  const s = status.value
  if (s) {
    for (const k of s.keys) {
      // v-model 对 type="number" 会自动数值化，draft 可能是 string | number
      const raw = String(draft[fieldId(k)] ?? '').trim()
      if (!raw) continue
      const bucket = (groups[k.group] ??= {})
      bucket[k.key] = k.kind === 'int' ? Number(raw) : raw
    }
  }
  const payload: DeploymentConfigUpdateRequest = {
    schema_version: s?.schema_version ?? 1,
    data: (groups.data ?? undefined) as DeploymentConfigUpdateRequest['data'],
    runtime: (groups.runtime ?? undefined) as DeploymentConfigUpdateRequest['runtime'],
    caches: (groups.caches ?? undefined) as DeploymentConfigUpdateRequest['caches'],
    imports: (groups.imports ?? undefined) as DeploymentConfigUpdateRequest['imports'],
    docker: (groups.docker ?? undefined) as DeploymentConfigUpdateRequest['docker'],
  }
  const trimmedNotes = notes.value.trim()
  if (trimmedNotes) payload.notes = trimmedNotes
  return payload
}

async function handlePreview() {
  previewBusy.value = true
  actionError.value = ''
  actionMessage.value = ''
  try {
    previewResult.value = await previewDeploymentConfig(buildPayload())
    mode.value = 'previewing'
  } catch (e) {
    actionError.value = (e as Error).message
  } finally {
    previewBusy.value = false
  }
}

async function handleApply() {
  if (
    !window.confirm(
      '确认保存部署配置？将原子写入 deployment.config.json 并镜像 .env（自动备份，失败整体回滚）。',
    )
  ) {
    return
  }
  saveBusy.value = true
  actionError.value = ''
  actionMessage.value = ''
  try {
    const result = await updateDeploymentConfig(buildPayload())
    actionMessage.value = result.message
    mode.value = 'editing'
    previewResult.value = null
    await loadStatus(true)
  } catch (e) {
    actionError.value = (e as Error).message
  } finally {
    saveBusy.value = false
  }
}

/** restart-backend 级变更：页面内调度进程组重启并等待 /health 恢复。 */
async function handleRestartBackend() {
  if (
    !window.confirm(
      '将重启 FastAPI + Celery Worker + Beat（Docker / 前端不动）。期间 API 短暂不可用，确认继续？',
    )
  ) {
    return
  }
  restartBusy.value = true
  actionError.value = ''
  actionMessage.value = '已调度后端重启，等待健康检查…'
  try {
    await restartBackendService({})
    const ok = await waitForBackendHealthy({ timeoutMs: 120_000 })
    if (!ok) {
      actionMessage.value = '重启已调度，但在超时内未恢复 /health；请检查 launch 日志'
    } else {
      actionMessage.value = '后端已恢复，正在刷新配置状态…'
      await loadStatus(true)
      actionMessage.value = '配置已生效，后端重启完成'
    }
  } catch (e) {
    actionError.value = (e as Error).message
  } finally {
    restartBusy.value = false
  }
}

function restartLevelChip(k: DeploymentKeyValueStatus): string {
  return RESTART_LABELS[k.restart_level] ?? k.restart_level
}

function inputPlaceholder(k: DeploymentKeyValueStatus): string {
  if (k.group === 'data' && k.key === 'output_root') {
    return '留空 = 随数据根联动派生 <数据根>/ProjectOutput'
  }
  if (k.kind === 'url') return 'http(s)://…'
  return k.must_exist ? '绝对路径，目录须已存在' : '绝对路径；留空 = 默认'
}

/** 可展开多行编辑的字段类型（超长路径 / URL / 自由文本）。 */
function isLongTextField(k: DeploymentKeyValueStatus): boolean {
  return k.kind === 'path' || k.kind === 'path_file' || k.kind === 'url' || k.kind === 'str'
}

function toggleGroup(group: string): void {
  if (collapsedGroups.has(group)) collapsedGroups.delete(group)
  else collapsedGroups.add(group)
}

function toggleFieldExpand(id: string): void {
  if (expandedFields.has(id)) expandedFields.delete(id)
  else expandedFields.add(id)
}

function togglePasswordReveal(id: string): void {
  if (revealedPasswords.has(id)) revealedPasswords.delete(id)
  else revealedPasswords.add(id)
}

/** 还原单字段草稿到基线（json 真源值）。 */
function resetField(k: DeploymentKeyValueStatus): void {
  draft[fieldId(k)] = baselineValue(k)
}

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / (1024 * 1024)).toFixed(1)} MB`
}

onMounted(() => {
  void loadStatus()
})
</script>

<template>
  <main class="deployment-view">
    <header class="view-header">
      <button type="button" class="btn" @click="router.push('/')">
        <Undo2 :size="14" aria-hidden="true" /> 返回主页
      </button>
      <h1 class="view-title">
        部署与数据源配置中心
        <span class="admin-chip"><Lock :size="12" aria-hidden="true" /> 管理员</span>
      </h1>
      <div class="header-actions">
        <button type="button" class="btn" :disabled="loading" @click="loadStatus()">
          <RefreshCw :size="14" :class="{ spinning: loading }" aria-hidden="true" /> 刷新
        </button>
        <a
          v-if="status?.exists"
          class="btn"
          :href="deploymentConfigExportUrl(true)"
          download="deployment.config.json"
          title="导出脱敏配置，可拷贝到部署机"
        >
          <Download :size="14" aria-hidden="true" /> 导出（脱敏）
        </a>
      </div>
    </header>

    <p v-if="loadError" class="banner banner-error">
      <AlertTriangle :size="14" aria-hidden="true" /> 加载失败：{{ loadError }}
      <button type="button" class="btn" @click="loadStatus()">重试</button>
    </p>

    <div v-if="loading && !status" class="banner">加载配置状态中…</div>

    <template v-if="status">
      <!-- 状态条：文件 + 三方对比 + 备份 + 汇总 -->
      <section class="status-strip">
        <div class="status-row">
          <span class="status-label">配置文件</span>
          <CodeValue :value="status.path" class="status-value" max-width="30rem" />
          <span class="badge" :class="status.exists ? 'badge-ok' : 'badge-muted'">
            {{ status.exists ? `已存在 · v${status.schema_version}` : '未创建（保存后生成）' }}
          </span>
          <span v-if="pendingRestart" class="badge badge-warn" title="运行值与期望配置不一致">
            待重启生效
          </span>
          <span class="badge badge-muted" :title="`${status.keys.length} 个配置键`">
            {{ status.keys.length }} 键
          </span>
          <span v-if="changedCount" class="badge badge-info">草稿改动 {{ changedCount }}</span>
        </div>
        <div class="status-row">
          <span class="status-label">.env 镜像</span>
          <CodeValue :value="status.env_path" class="status-value" max-width="30rem" />
        </div>
        <div v-if="status.backups.length" class="status-row">
          <span class="status-label">备份轮换</span>
          <span
            v-for="b in status.backups"
            :key="b.name"
            class="badge badge-muted"
            :title="`${b.path} · ${formatBytes(b.size_bytes)}`"
          >
            {{ b.name }}
          </span>
        </div>
      </section>

      <p v-if="actionMessage" class="banner banner-ok">{{ actionMessage }}</p>
      <p v-if="actionError" class="banner banner-error">
        <AlertTriangle :size="14" aria-hidden="true" /> {{ actionError }}
      </p>

      <!-- 预览结果：diff + errors/warnings -->
      <section v-if="mode === 'previewing' && previewResult" class="preview-card">
        <h2 class="card-title">
          变更预览
          <span class="badge" :class="previewResult.ok ? 'badge-ok' : 'badge-error'">
            {{ previewResult.ok ? '校验通过' : '校验失败' }}
          </span>
          <span v-if="previewResult.diff.length" class="badge badge-muted">
            {{ previewResult.diff.length }} 项变更 ·
            {{ RESTART_LABELS[previewResult.restart_level] ?? previewResult.restart_level }}
          </span>
        </h2>

        <ul v-if="previewResult.errors.length" class="msg-list msg-error">
          <li v-for="e in previewResult.errors" :key="e">{{ e }}</li>
        </ul>
        <ul v-if="previewResult.warnings.length" class="msg-list msg-warn">
          <li v-for="w in previewResult.warnings" :key="w">{{ w }}</li>
        </ul>

        <div v-if="previewResult.diff.length" class="diff-scroll">
          <table class="diff-table">
            <thead>
              <tr>
                <th>配置项</th>
                <th>环境变量</th>
                <th>当前值</th>
                <th>新值</th>
                <th>生效方式</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="d in previewResult.diff" :key="`${d.group}.${d.key}`">
                <td>{{ d.key }}</td>
                <td>
                  <code class="env-chip">{{ d.env_key }}</code>
                </td>
                <td class="val-cell">
                  <CodeValue :value="d.old" placeholder="（未设置）" />
                  <span
                    v-if="d.derived"
                    class="badge badge-muted"
                    title="data_root 变更且未显式设置产物根时，自动派生为新数据根下的 ProjectOutput"
                  >
                    联动派生
                  </span>
                </td>
                <td class="val-cell">
                  <CodeValue :value="d.new" placeholder="（未设置）" class="val-new" />
                </td>
                <td>{{ RESTART_LABELS[d.restart_level] ?? d.restart_level }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <p v-else-if="previewResult.ok" class="empty">无变更（当前值与期望值一致）。</p>
      </section>

      <!-- 分组编辑表单（可折叠） -->
      <section v-for="section in groupSections" :key="section.group" class="form-card">
        <button type="button" class="group-head" @click="toggleGroup(section.group)">
          <component
            :is="collapsedGroups.has(section.group) ? ChevronDown : ChevronUp"
            :size="14"
            aria-hidden="true"
          />
          <span class="group-title">{{ section.label }}</span>
          <span class="badge badge-muted">{{ section.keys.length }} 项</span>
          <span v-if="changedCountForGroup(section.group)" class="badge badge-info">
            改动 {{ changedCountForGroup(section.group) }}
          </span>
          <span
            v-if="section.keys.some((k) => k.pending)"
            class="badge badge-warn"
            title="保存后尚未重启，运行值仍为旧配置"
          >
            待生效
          </span>
        </button>

        <div v-show="!collapsedGroups.has(section.group)" class="key-rows">
          <div
            v-for="k in section.keys"
            :key="fieldId(k)"
            class="key-row"
            :class="{ pending: k.pending, changed: isFieldChanged(k) }"
          >
            <div class="key-head">
              <span class="key-label">
                {{ k.label }}
                <em v-if="k.must_exist" class="req" title="目录必须已存在">*</em>
                <span
                  v-if="isFieldChanged(k)"
                  class="changed-chip"
                  title="草稿与 json 真源不一致；重置可还原"
                >
                  已修改
                </span>
              </span>
              <code class="env-chip" :title="`生效方式：${restartLevelChip(k)}`">
                {{ k.env_key }}
              </code>
            </div>
            <div class="key-input">
              <!-- 级别：下拉 -->
              <select v-if="k.kind === 'level'" v-model="draft[fieldId(k)]" :aria-label="k.label">
                <option value="">（未设置）</option>
                <option v-for="opt in LEVEL_OPTIONS" :key="opt" :value="opt">{{ opt }}</option>
              </select>

              <!-- 敏感：密码框 + 明文切换 -->
              <div v-else-if="k.kind === 'password'" class="input-wrap">
                <input
                  v-model="draft[fieldId(k)]"
                  :type="revealedPasswords.has(fieldId(k)) ? 'text' : 'password'"
                  autocomplete="new-password"
                  placeholder="留空保持不变（回显恒脱敏）"
                />
                <button
                  type="button"
                  class="input-affix"
                  :title="revealedPasswords.has(fieldId(k)) ? '隐藏' : '显示明文'"
                  @click="togglePasswordReveal(fieldId(k))"
                >
                  <EyeOff v-if="revealedPasswords.has(fieldId(k))" :size="13" aria-hidden="true" />
                  <Eye v-else :size="13" aria-hidden="true" />
                </button>
              </div>

              <!-- 整数：数字框 -->
              <input
                v-else-if="k.kind === 'int'"
                v-model="draft[fieldId(k)]"
                type="number"
                min="0"
                placeholder="留空 = 默认"
              />

              <!-- 超长文本：input ↔ textarea 展开编辑 -->
              <template v-else-if="isLongTextField(k)">
                <div v-if="!expandedFields.has(fieldId(k))" class="input-wrap">
                  <input
                    v-model="draft[fieldId(k)]"
                    type="text"
                    class="mono"
                    :placeholder="inputPlaceholder(k)"
                    spellcheck="false"
                  />
                  <button
                    type="button"
                    class="input-affix"
                    title="展开多行编辑（超长路径/URL）"
                    @click="toggleFieldExpand(fieldId(k))"
                  >
                    <ChevronDown :size="13" aria-hidden="true" />
                  </button>
                </div>
                <textarea
                  v-else
                  v-model="draft[fieldId(k)]"
                  class="mono"
                  rows="3"
                  spellcheck="false"
                  :placeholder="inputPlaceholder(k)"
                />
                <button
                  v-if="expandedFields.has(fieldId(k))"
                  type="button"
                  class="collapse-edit"
                  @click="toggleFieldExpand(fieldId(k))"
                >
                  收起为单行
                </button>
              </template>

              <input
                v-else
                v-model="draft[fieldId(k)]"
                type="text"
                :placeholder="inputPlaceholder(k)"
              />

              <button
                v-if="isFieldChanged(k)"
                type="button"
                class="reset-field"
                :title="`还原为 json 真源值：${baselineValue(k) || '（未设置）'}`"
                @click="resetField(k)"
              >
                <ClipboardCheck :size="12" aria-hidden="true" /> 还原
              </button>
            </div>
            <div class="key-meta">
              <span class="meta-item" title="运行值（当前进程）">
                运行 <CodeValue :value="k.runtime_value" max-width="16rem" />
              </span>
              <span class="meta-item" title=".env 值">
                .env <CodeValue :value="k.env_value" max-width="16rem" />
              </span>
              <span class="meta-item" title="deployment.json 值">
                json
                <CodeValue :value="k.sensitive ? '' : k.config_value" max-width="16rem" />
                <span v-if="k.source === 'config'" class="src-chip">真源</span>
              </span>
            </div>
          </div>
        </div>
      </section>

      <section class="form-card">
        <h2 class="card-title">备注</h2>
        <textarea
          v-model="notes"
          rows="2"
          placeholder="部署说明（如：部署机数据盘挂载点、机构名），随配置文件保存"
        />
      </section>

      <!-- 粘性操作栏：编辑/预览两态，长页滚动中始终可达 -->
      <div class="sticky-actions">
        <template v-if="mode === 'editing'">
          <button
            type="button"
            class="btn btn-primary"
            :disabled="previewBusy || loading"
            @click="handlePreview"
          >
            {{ previewBusy ? '校验中…' : '预览变更' }}
            <span v-if="changedCount" class="btn-count">{{ changedCount }}</span>
          </button>
          <button
            v-if="pendingRestart"
            type="button"
            class="btn"
            :disabled="restartBusy"
            title="重启 FastAPI + Worker + Beat，使保存的配置生效"
            @click="handleRestartBackend"
          >
            {{ restartBusy ? '重启中…' : '重启后端使配置生效' }}
          </button>
        </template>
        <template v-else-if="mode === 'previewing' && previewResult">
          <button type="button" class="btn" :disabled="saveBusy" @click="mode = 'editing'">
            返回编辑
          </button>
          <button
            type="button"
            class="btn btn-primary"
            :disabled="!previewResult.ok || saveBusy"
            @click="handleApply"
          >
            {{ saveBusy ? '保存中…' : '确认并保存' }}
          </button>
        </template>
      </div>

      <footer class="view-footer">
        <p class="footer-hint">
          保存将原子写入 deployment.config.json 并镜像 .env（自动备份 3 份，失败整体回滚）。 含
          Docker 相关键（restart-full）时须在服务器执行
          <code>Env\Python312\python.exe launch.py restart</code>（Windows）或
          <code>python launch.py restart</code> 全量重启。仅管理员可访问本页；后端 API
          另有独立鉴权。
        </p>
      </footer>
    </template>
  </main>
</template>

<style scoped>
.deployment-view {
  /* #app 全局 overflow:hidden 裁掉文档流滚动，本页改为内部滚动自治 */
  height: calc(100vh - 1.5rem);
  overflow-y: auto;
  background: var(--surface-2, #0b1118);
  color: var(--text-primary, #d7e2ea);
  padding: 1rem 1.2rem 2.4rem;
  display: flex;
  flex-direction: column;
  gap: 0.8rem;
  max-width: 1120px;
  margin: 0 auto;
}

.view-header {
  display: flex;
  align-items: center;
  gap: 0.8rem;
  flex-wrap: wrap;
}
.view-title {
  margin: 0;
  font-size: 1.05rem;
  font-weight: 600;
  color: var(--text-strong, #f2f7fa);
  display: flex;
  align-items: center;
  gap: 0.5rem;
  flex: 1;
}
.header-actions {
  display: flex;
  gap: 0.4rem;
}
.admin-chip {
  display: inline-flex;
  align-items: center;
  gap: 0.22rem;
  font-size: var(--font-size-caption, 0.75rem);
  font-weight: 400;
  color: var(--accent-strong, #7fd4ff);
  border: 1px solid var(--border-default, #2a3a48);
  border-radius: 999px;
  padding: 0.05rem 0.45rem;
}

.btn {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  border: 1px solid var(--border-strong, #3a4c5c);
  background: var(--surface-1, #101a24);
  color: var(--text-primary, #d7e2ea);
  border-radius: 0.32rem;
  font-size: var(--font-size-caption, 0.75rem);
  padding: 0.3rem 0.55rem;
  cursor: pointer;
  text-decoration: none;
}
.btn-primary {
  background: var(--accent-surface, #10344a);
  border-color: var(--accent, #5ad5ff);
  color: var(--accent-strong, #9fe4ff);
}
.btn:disabled {
  opacity: 0.5;
  cursor: default;
}
.btn-count {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 1.05rem;
  padding: 0 0.22rem;
  border-radius: 999px;
  background: var(--accent, #5ad5ff);
  color: #06121c;
  font-weight: 600;
  font-size: 0.66rem;
}
.spinning {
  animation: spin 1s linear infinite;
}
@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

.banner {
  margin: 0;
  padding: 0.5rem 0.7rem;
  border-radius: 0.4rem;
  border: 1px solid var(--border-subtle, #223140);
  background: var(--surface-sunken, #0d1520);
  font-size: var(--font-size-caption, 0.75rem);
  display: flex;
  align-items: center;
  gap: 0.4rem;
  flex-wrap: wrap;
}
.banner-error {
  border-color: var(--danger-border, #5c2a2a);
  color: var(--danger, #ff8f8f);
}
.banner-ok {
  border-color: var(--success, #2f6b4a);
  color: var(--success, #7fd6a4);
}

.status-strip {
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
  padding: 0.55rem 0.7rem;
  border: 1px solid var(--border-subtle, #223140);
  border-radius: 0.44rem;
  background: var(--surface-sunken, #0d1520);
}
.status-row {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  flex-wrap: wrap;
  font-size: var(--font-size-caption, 0.75rem);
  min-width: 0;
}
.status-label {
  color: var(--text-muted, #8fa3b3);
  min-width: 4.5rem;
}
.status-value {
  min-width: 0;
}

.badge {
  padding: 0.06rem 0.36rem;
  border-radius: 0.24rem;
  font-size: var(--font-size-caption, 0.75rem);
  border: 1px solid transparent;
  white-space: nowrap;
}
.badge-ok {
  background: rgba(47, 107, 74, 0.24);
  color: var(--success, #7fd6a4);
}
.badge-warn {
  background: var(--warning-surface, #4a3a10);
  color: var(--accent-warm, #ffcc80);
}
.badge-error {
  background: rgba(92, 42, 42, 0.3);
  color: var(--danger, #ff8f8f);
}
.badge-muted {
  background: transparent;
  border-color: var(--border-subtle, #223140);
  color: var(--text-muted, #8fa3b3);
}
.badge-info {
  background: rgba(90, 213, 255, 0.14);
  border-color: var(--accent, #5ad5ff);
  color: var(--accent-strong, #9fe4ff);
}

.form-card {
  padding: 0.62rem 0.72rem;
  border-radius: 0.52rem;
  background: var(--surface-sunken, #0d1520);
  border: 1px solid var(--border-subtle, #223140);
}
.card-title {
  margin: 0 0 0.5rem;
  color: var(--text-strong, #f2f7fa);
  font-size: var(--font-size-caption, 0.75rem);
  font-weight: 600;
  display: flex;
  align-items: center;
  gap: 0.4rem;
}
.group-head {
  display: flex;
  align-items: center;
  gap: 0.45rem;
  width: 100%;
  border: none;
  background: transparent;
  color: var(--text-strong, #f2f7fa);
  font-size: var(--font-size-caption, 0.75rem);
  font-weight: 600;
  cursor: pointer;
  padding: 0.1rem 0;
  text-align: left;
}
.group-head:hover {
  color: var(--accent-strong, #9fe4ff);
}
.group-title {
  flex: none;
}

.key-rows {
  display: flex;
  flex-direction: column;
  margin-top: 0.35rem;
}
.key-row {
  display: grid;
  grid-template-columns: minmax(13rem, 16rem) 1fr;
  gap: 0.3rem 0.8rem;
  padding: 0.45rem 0.2rem;
  border-top: 1px solid var(--border-subtle, #1a2836);
  align-items: center;
}
.key-row:first-child {
  border-top: none;
}
.key-row.changed {
  background: rgba(90, 213, 255, 0.05);
  border-radius: 0.3rem;
}
.key-row.pending .key-label::after {
  content: '待生效';
  margin-left: 0.4rem;
  font-size: 0.68rem;
  color: var(--accent-warm, #ffcc80);
  border: 1px solid var(--border-default, #2a3a48);
  border-radius: 0.24rem;
  padding: 0 0.25rem;
}
.changed-chip {
  margin-left: 0.4rem;
  font-size: 0.66rem;
  color: var(--accent-strong, #9fe4ff);
  border: 1px solid var(--accent, #5ad5ff);
  border-radius: 0.24rem;
  padding: 0 0.25rem;
}
.key-head {
  display: flex;
  flex-direction: column;
  gap: 0.18rem;
  min-width: 0;
}
.key-label {
  color: var(--text-primary, #d7e2ea);
  font-size: var(--font-size-caption, 0.75rem);
}
.req {
  color: var(--danger, #ff8f8f);
  font-style: normal;
}
.env-chip {
  align-self: flex-start;
  color: var(--text-muted, #8fa3b3);
  font-size: 0.68rem;
  background: transparent;
  border: 1px solid var(--border-subtle, #223140);
  border-radius: 0.24rem;
  padding: 0 0.28rem;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.key-input {
  display: flex;
  flex-direction: column;
  gap: 0.22rem;
  min-width: 0;
}
.input-wrap {
  display: flex;
  align-items: stretch;
  gap: 0.28rem;
  min-width: 0;
}
.input-wrap input {
  flex: 1;
  min-width: 0;
}
.input-affix {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: none;
  width: 1.7rem;
  border: 1px solid var(--border-default, #2a3a48);
  border-radius: 0.36rem;
  background: var(--surface-1, #101a24);
  color: var(--text-muted, #8fa3b3);
  cursor: pointer;
}
.input-affix:hover {
  color: var(--accent-strong, #9fe4ff);
  border-color: var(--border-strong, #3a4c5c);
}
.key-input input,
.key-input select,
.key-input textarea,
.form-card > textarea {
  border: 1px solid var(--border-default, #2a3a48);
  border-radius: 0.36rem;
  background: var(--surface-1, #101a24);
  color: var(--text-strong, #f2f7fa);
  font-size: var(--font-size-caption, 0.75rem);
  padding: 0.32rem 0.42rem;
  width: 100%;
  box-sizing: border-box;
}
.key-input textarea.mono {
  resize: vertical;
  line-height: 1.5;
}
input.mono,
textarea.mono {
  font-family: var(--font-mono, ui-monospace, 'Cascadia Mono', Consolas, monospace);
}
.collapse-edit,
.reset-field {
  align-self: flex-start;
  display: inline-flex;
  align-items: center;
  gap: 0.24rem;
  border: 1px solid var(--border-subtle, #223140);
  background: transparent;
  color: var(--text-muted, #8fa3b3);
  border-radius: 0.24rem;
  font-size: 0.66rem;
  padding: 0.1rem 0.34rem;
  cursor: pointer;
}
.collapse-edit:hover,
.reset-field:hover {
  color: var(--accent-strong, #9fe4ff);
  border-color: var(--border-default, #2a3a48);
}
.key-meta {
  grid-column: 2;
  display: flex;
  gap: 0.9rem;
  flex-wrap: wrap;
  font-size: 0.68rem;
  color: var(--text-muted, #8fa3b3);
  min-width: 0;
}
.meta-item {
  display: inline-flex;
  align-items: center;
  gap: 0.28rem;
  min-width: 0;
  max-width: 100%;
}
.meta-item :deep(.code-value) {
  min-width: 0;
}
.src-chip {
  color: var(--accent-strong, #9fe4ff);
}

.preview-card {
  padding: 0.62rem 0.72rem;
  border-radius: 0.52rem;
  border: 1px solid var(--accent, #5ad5ff);
  background: var(--surface-sunken, #0d1520);
}
.msg-list {
  margin: 0.3rem 0;
  padding-left: 1.1rem;
  font-size: var(--font-size-caption, 0.75rem);
  line-height: 1.55;
}
.msg-error li {
  color: var(--danger, #ff8f8f);
}
.msg-warn li {
  color: var(--accent-warm, #ffcc80);
}
.diff-scroll {
  overflow-x: auto;
}
.diff-table {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--font-size-caption, 0.75rem);
  margin: 0.45rem 0 0.2rem;
}
.diff-table th,
.diff-table td {
  text-align: left;
  padding: 0.26rem 0.4rem;
  border-bottom: 1px solid var(--border-subtle, #1a2836);
  vertical-align: top;
}
.diff-table th {
  color: var(--text-muted, #8fa3b3);
  font-weight: 600;
  white-space: nowrap;
}
.val-cell {
  max-width: 22rem;
  min-width: 10rem;
}
.val-cell .badge {
  margin-left: 0.3rem;
}
.val-new :deep(.cv-text) {
  color: var(--accent-strong, #9fe4ff);
}

.sticky-actions {
  position: sticky;
  bottom: 0;
  z-index: 5;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.36rem;
  margin-top: 0.4rem;
  padding: 0.5rem 0.6rem;
  border: 1px solid var(--border-subtle, #223140);
  border-radius: 0.52rem;
  background: color-mix(in srgb, var(--surface-2, #0b1118) 88%, transparent);
  backdrop-filter: blur(6px);
}
.view-footer {
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
}
.footer-hint {
  margin: 0;
  color: var(--text-muted, #8fa3b3);
  font-size: var(--font-size-caption, 0.75rem);
  line-height: 1.55;
}
.empty {
  color: var(--text-muted, #8fa3b3);
  font-size: var(--font-size-caption, 0.75rem);
}
</style>
