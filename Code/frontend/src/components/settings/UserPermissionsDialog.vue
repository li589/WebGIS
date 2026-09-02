<script setup lang="ts">
/**
 * 用户权限覆盖对话框（管理员专属）
 *
 * 由设置-账户-用户管理列表的「权限覆盖」按钮打开。
 * 此处配置的是**用户级覆盖**（优先于主题默认 ACL）：
 *  - 权限模式（开放/白名单）
 *  - 图层 / 图层分组 / 工作流 / 数据源 的显式允许/拒绝
 *
 * 记录增删与资源选择由共享组件 ResourceAclEditor 承担
 * （下拉选择已有资源 + 手动输入 ID）；主题默认 ACL 请在「主题管理」中配置。
 */
import { computed, ref, watch } from 'vue'
import IconButton from '../ui/IconButton.vue'
import ResourceAclEditor from './ResourceAclEditor.vue'
import { updatePermissionMode, type PermissionMode } from '../../services/auth-api'

interface UserRow {
  id: number
  username: string
  role: 'admin' | 'standard' | 'demo'
  permission_mode?: string
  theme_id?: number | null
  theme_name?: string | null
}

const props = defineProps<{
  open: boolean
  user: UserRow | null
}>()

const emit = defineEmits<{
  close: []
  updated: [userId: number, mode: PermissionMode]
}>()

const MODE_LABELS: Record<PermissionMode, string> = {
  open: '开放（黑名单模式：仅有拒绝记录的资源被拦截）',
  whitelist: '白名单（仅有允许记录的资源可访问）',
}

const mode = ref<PermissionMode>('open')
const saving = ref(false)
const error = ref<string | null>(null)
const message = ref<string | null>(null)

const isOpen = computed(() => props.open && !!props.user)
const canEdit = computed(() => {
  if (!props.user) return false
  // 当前管理员不能修改自己（避免自降级）
  return props.user.role !== 'admin'
})

const aclMode = computed(() =>
  props.user ? { kind: 'user' as const, userId: props.user.id } : null,
)

async function load() {
  if (!props.user) return
  if (props.user.permission_mode === 'open' || props.user.permission_mode === 'whitelist') {
    mode.value = props.user.permission_mode
  } else {
    mode.value = 'open'
  }
}

watch(
  () => [props.open, props.user?.id],
  ([open]) => {
    if (open) {
      error.value = null
      message.value = null
      void load()
    }
  },
)

async function changeMode(next: PermissionMode) {
  if (!props.user) return
  saving.value = true
  error.value = null
  try {
    await updatePermissionMode(props.user.id, next)
    mode.value = next
    message.value = next === 'whitelist' ? '已切换为白名单模式' : '已切换为开放模式（黑名单）'
    emit('updated', props.user.id, next)
  } catch (err) {
    error.value = err instanceof Error ? err.message : '切换模式失败'
  } finally {
    saving.value = false
  }
}

function close() {
  if (saving.value) return
  emit('close')
}
</script>

<template>
  <Teleport to="body">
    <div v-if="isOpen" class="upd-overlay" @click.self="close">
      <div class="upd-dialog" role="dialog" aria-modal="true" aria-labelledby="upd-title">
        <header class="upd-header">
          <div>
            <p class="upd-kicker">用户权限覆盖</p>
            <h2 id="upd-title" class="upd-title">
              {{ user?.username }}<span v-if="user?.role === 'admin'" class="upd-tag">管理员</span>
            </h2>
            <p v-if="user?.theme_name" class="upd-inherit">
              继承自主题：{{ user.theme_name }}（用户覆盖优先于主题默认 ACL）
            </p>
          </div>
          <IconButton size="sm" label="关闭" @click="close">
            <template #icon>
              <span aria-hidden="true">×</span>
            </template>
          </IconButton>
        </header>

        <p v-if="!canEdit" class="upd-locked">
          管理员账户拥有全部权限，此处配置仅作查看（避免自降级锁定）。
        </p>

        <section class="upd-section">
          <h3 class="upd-h3">权限模式</h3>
          <p class="upd-hint">{{ MODE_LABELS[mode] }}</p>
          <div class="upd-mode-row">
            <button
              type="button"
              class="upd-mode-btn"
              :class="{ active: mode === 'open' }"
              :disabled="!canEdit || saving"
              @click="changeMode('open')"
            >
              开放（黑名单）
            </button>
            <button
              type="button"
              class="upd-mode-btn"
              :class="{ active: mode === 'whitelist' }"
              :disabled="!canEdit || saving"
              @click="changeMode('whitelist')"
            >
              白名单
            </button>
          </div>
        </section>

        <section class="upd-section">
          <h3 class="upd-h3">资源权限覆盖</h3>
          <p class="upd-hint">
            支持图层 / 图层分组 / 工作流 / 数据源；图层分组规则对其成员图层生效
            （图层级记录优先于分组级）。
          </p>
          <ResourceAclEditor v-if="aclMode" :mode="aclMode" :disabled="!canEdit" />
        </section>

        <p v-if="message" class="upd-msg upd-msg--ok">{{ message }}</p>
        <p v-if="error" class="upd-msg upd-msg--err">{{ error }}</p>

        <footer class="upd-footer">
          <button type="button" class="upd-secondary" @click="close">关闭</button>
        </footer>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.upd-overlay {
  position: fixed;
  inset: 0;
  z-index: 1100;
  background: rgba(3, 10, 20, 0.55);
  backdrop-filter: blur(4px);
  -webkit-backdrop-filter: blur(4px);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 2rem;
}
.upd-dialog {
  width: min(640px, 100%);
  max-height: calc(100vh - 4rem);
  display: flex;
  flex-direction: column;
  gap: 1.1rem;
  padding: 1.5rem 1.6rem 1.2rem;
  border: 1px solid var(--border-accent);
  border-radius: 14px;
  background: linear-gradient(165deg, var(--surface-2), var(--surface-1));
  box-shadow:
    0 30px 80px rgba(0, 0, 0, 0.5),
    0 1px 0 rgba(136, 223, 255, 0.12) inset;
  overflow: auto;
  color: var(--text-primary);
}
.upd-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 1rem;
}
.upd-kicker {
  margin: 0;
  font-size: var(--font-size-caption);
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--text-faint);
  font-weight: var(--font-weight-medium);
}
.upd-title {
  margin: 0.15rem 0 0;
  font-size: 1.25rem;
  font-weight: var(--font-weight-semibold);
  color: var(--text-strong);
  display: flex;
  align-items: center;
  gap: 0.5rem;
}
.upd-inherit {
  margin: 0.35rem 0 0;
  font-size: var(--font-size-caption);
  color: var(--text-secondary);
}
.upd-tag {
  font-size: 0.7rem;
  font-weight: var(--font-weight-medium);
  padding: 0.05rem 0.45rem;
  border-radius: 999px;
  background: var(--accent-surface);
  color: var(--accent);
  border: 1px solid var(--border-accent);
}
.upd-locked {
  margin: 0;
  padding: 0.6rem 0.8rem;
  border-radius: 8px;
  background: var(--danger-surface, rgba(220, 38, 38, 0.08));
  color: var(--danger, #f87171);
  font-size: var(--font-size-caption);
}
.upd-section {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  padding: 0.85rem 0.95rem;
  border: 1px solid var(--border-subtle);
  border-radius: 10px;
  background: var(--surface-sunken);
}
.upd-h3 {
  margin: 0;
  font-size: var(--font-size-body);
  font-weight: var(--font-weight-semibold);
  color: var(--text-strong);
}
.upd-hint {
  margin: 0;
  font-size: var(--font-size-caption);
  color: var(--text-secondary);
  line-height: 1.5;
}
.upd-mode-row {
  display: flex;
  gap: 0.5rem;
  margin-top: 0.25rem;
}
.upd-mode-btn {
  flex: 1;
  padding: 0.45rem 0.8rem;
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  background: var(--surface-1);
  color: var(--text-secondary);
  cursor: pointer;
  font-family: inherit;
  font-size: var(--font-size-caption);
  font-weight: var(--font-weight-medium);
  transition:
    background-color var(--motion-fast) var(--ease-soft),
    border-color var(--motion-fast) var(--ease-soft),
    color var(--motion-fast) var(--ease-soft);
}
.upd-mode-btn:hover:not(:disabled) {
  border-color: var(--border-strong);
  color: var(--text-primary);
}

.upd-mode-btn.active {
  border-color: var(--border-accent);
  background: var(--accent-surface);
  color: var(--accent);
}
.upd-mode-btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.upd-msg {
  margin: 0;
  font-size: var(--font-size-caption);
  padding: 0.4rem 0.6rem;
  border-radius: 6px;
}
.upd-msg--ok {
  background: rgba(74, 222, 128, 0.1);
  color: var(--success, #4ade80);
}
.upd-msg--err {
  background: rgba(248, 113, 113, 0.1);
  color: var(--danger, #f87171);
}
.upd-footer {
  display: flex;
  justify-content: flex-end;
  padding-top: 0.25rem;
}
.upd-secondary {
  padding: 0.45rem 1.2rem;
  border: 1px solid var(--border-default);
  border-radius: 6px;
  background: var(--surface-1);
  color: var(--text-primary);
  cursor: pointer;
  font-family: inherit;
  font-size: var(--font-size-caption);
  font-weight: var(--font-weight-medium);
}
.upd-secondary:hover {
  border-color: var(--border-strong);
}
@media (max-width: 640px) {
  .upd-form {
    grid-template-columns: 1fr;
  }
}
</style>
