<script setup lang="ts">
import { computed, nextTick, onUnmounted, ref, watch } from 'vue'
import { X } from '../ui/icons'
import {
  confirmAgentAction,
  postAgentChat,
  streamAgentChat,
  type AgentChatResponse,
  type AgentConfirmation,
  type AgentStep,
  type AgentUiIntent,
} from '../../services/agent-api'
import { useLayerWorkspace } from '../../stores/layers/selectors'
import {
  AGENT_CHAT_PANEL_MAX_HEIGHT_PX,
  AGENT_CHAT_PANEL_WIDTH_PX,
  COMPANION_SIZE_PX,
} from '../../composables/useAgentCompanionPosition'
import { executeAgentUiIntents } from './agent-ui-intent'

const props = defineProps<{
  open: boolean
  anchor: {
    x: number
    y: number
    dock: 'left' | 'right' | 'none'
    /** 锚点已是视口坐标（Teleport fixed） */
    viewport?: boolean
  }
  fitToLayerExtent?: (instanceId: string) => boolean
}>()

const emit = defineEmits<{
  close: []
}>()

interface PendingConfirmation extends AgentConfirmation {
  status: 'pending' | 'approved' | 'rejected' | 'error'
  resultMessage?: string
  busy?: boolean
}

interface ChatMessage {
  id: string
  role: 'user' | 'assistant' | 'system'
  text: string
  usage?: {
    total_tokens: number
    estimated?: boolean
  } | null
  steps?: Array<{
    type: string
    summary: string
    detail?: string | null
  }>
  confirmations?: PendingConfirmation[]
}

const workspace = useLayerWorkspace()
const messages = ref<ChatMessage[]>([
  {
    id: 'welcome',
    role: 'assistant',
    text: '你好，我是地图助手。试试「打开 CMFD 降水」或「有哪些活动图层」。',
  },
])
const input = ref('')
const sending = ref(false)
const sessionId = ref<string | null>(null)
const listRef = ref<HTMLElement | null>(null)
const errorText = ref<string | null>(null)
const nowMs = ref(Date.now())
let tickTimer: ReturnType<typeof setInterval> | null = null

function startExpiryTick() {
  if (tickTimer != null) return
  tickTimer = setInterval(() => {
    nowMs.value = Date.now()
  }, 1000)
}

onUnmounted(() => {
  if (tickTimer != null) {
    clearInterval(tickTimer)
    tickTimer = null
  }
})

const panelStyle = computed(() => {
  const panelW = AGENT_CHAT_PANEL_WIDTH_PX
  const gap = 14
  const companion = COMPANION_SIZE_PX
  const vw = typeof window !== 'undefined' ? window.innerWidth : 1200
  const vh = typeof window !== 'undefined' ? window.innerHeight : 800

  let left: number
  if (props.anchor.dock === 'right') {
    left = Math.max(12, props.anchor.x - panelW - gap)
  } else if (props.anchor.dock === 'left') {
    left = props.anchor.x + companion + gap
  } else {
    left = props.anchor.x - panelW / 2 + companion / 2
  }
  left = Math.min(Math.max(12, left), Math.max(12, vw - panelW - 12))

  const maxH = Math.min(AGENT_CHAT_PANEL_MAX_HEIGHT_PX, vh - 96)
  let top = Math.max(72, props.anchor.y - 48)
  top = Math.min(top, Math.max(72, vh - maxH - 24))

  return {
    left: `${left}px`,
    top: `${top}px`,
    width: `min(${panelW}px, calc(100vw - 24px))`,
    maxHeight: `${maxH}px`,
  }
})

function buildClientContext() {
  const layers = workspace.activeLayers.value.filter((l) => !l.isAdminBoundary)
  return {
    active_catalog_ids: layers.map((l) => l.catalogId).filter(Boolean),
    active_layers: layers.map((l) => ({
      catalog_id: l.catalogId,
      instance_id: l.instanceId,
      name: l.name || l.catalogId,
    })),
  }
}

function remainingSeconds(expiresAt?: string): number | null {
  if (!expiresAt) return null
  const t = Date.parse(expiresAt)
  if (Number.isNaN(t)) return null
  return Math.max(0, Math.floor((t - nowMs.value) / 1000))
}

function confirmSummaryLabel(c: PendingConfirmation): string {
  const s = c.summary || {}
  const name = String(s.display_name || s.catalog_id || '')
  const wf = String(s.workflow_id || '')
  if (name && wf) return `${name} · ${wf}`
  return name || wf || c.action || 'run_workflow'
}

async function scrollToBottom() {
  await nextTick()
  const el = listRef.value
  if (el) el.scrollTop = el.scrollHeight
}

watch(
  () => props.open,
  (open) => {
    if (open) void scrollToBottom()
  },
)

async function resolveConfirmation(
  msgId: string,
  confirmationId: string,
  decision: 'approve' | 'reject',
) {
  const msg = messages.value.find((m) => m.id === msgId)
  const card = msg?.confirmations?.find((c) => c.confirmation_id === confirmationId)
  if (!card || card.status !== 'pending' || card.busy) return
  card.busy = true
  try {
    const res = await confirmAgentAction({
      confirmation_id: confirmationId,
      decision,
    })
    card.status = res.status === 'approved' ? 'approved' : 'rejected'
    card.resultMessage = res.message || (decision === 'approve' ? '已提交' : '已取消')
    messages.value.push({
      id: `c-${Date.now()}`,
      role: 'system',
      text:
        decision === 'approve'
          ? `✓ ${card.resultMessage}${res.run_id ? `（${res.run_id}）` : ''}`
          : `✗ ${card.resultMessage}`,
    })
  } catch (err) {
    card.status = 'error'
    card.resultMessage = err instanceof Error ? err.message : String(err)
    messages.value.push({
      id: `c-err-${Date.now()}`,
      role: 'system',
      text: `确认失败：${card.resultMessage}`,
    })
  } finally {
    card.busy = false
    void scrollToBottom()
  }
}

  async function applyChatResult(res: AgentChatResponse, assistantId: string) {
    sessionId.value = res.session_id
    const msg = messages.value.find((m) => m.id === assistantId)
    const pending: PendingConfirmation[] | undefined = res.confirmations?.length
      ? res.confirmations.map((c) => ({
          ...c,
          status: 'pending' as const,
        }))
      : undefined
    if (pending?.length) startExpiryTick()
    if (msg) {
      msg.text = res.reply || msg.text
      msg.usage = res.usage
        ? {
            total_tokens: res.usage.total_tokens,
            estimated: res.usage.estimated,
          }
        : null
      if (res.steps?.length) msg.steps = res.steps
      if (pending?.length) msg.confirmations = pending
    } else {
      messages.value.push({
        id: assistantId,
        role: 'assistant',
        text: res.reply,
        usage: res.usage
          ? {
              total_tokens: res.usage.total_tokens,
              estimated: res.usage.estimated,
            }
          : null,
        steps: res.steps?.length ? res.steps : undefined,
        confirmations: pending,
      })
    }
    if (res.ui_intents?.length) {
      const results = executeAgentUiIntents(res.ui_intents, {
        fitToLayerExtent: props.fitToLayerExtent,
      })
      const notes = results
        .filter((r) => r.message)
        .map((r) => (r.ok ? `✓ ${r.message}` : `✗ ${r.message}`))
      if (notes.length) {
        messages.value.push({
          id: `s-${Date.now()}`,
          role: 'system',
          text: notes.join('\n'),
        })
      }
    }
  }

  async function send() {
    const text = input.value.trim()
    if (!text || sending.value) return
    input.value = ''
    errorText.value = null
    messages.value.push({
      id: `u-${Date.now()}`,
      role: 'user',
      text,
    })
    const assistantId = `a-${Date.now()}`
    messages.value.push({
      id: assistantId,
      role: 'assistant',
      text: '',
      steps: [],
    })
    void scrollToBottom()
    sending.value = true

    const req = {
      message: text,
      session_id: sessionId.value,
      client_context: buildClientContext(),
    }

    const onStep = (step: AgentStep) => {
      const msg = messages.value.find((m) => m.id === assistantId)
      if (!msg) return
      if (!msg.steps) msg.steps = []
      msg.steps.push(step)
      void scrollToBottom()
    }
    const onToken = (chunk: string) => {
      const msg = messages.value.find((m) => m.id === assistantId)
      if (!msg) return
      msg.text = `${msg.text || ''}${chunk}`
      void scrollToBottom()
    }

    try {
      let res: AgentChatResponse
      try {
        res = await streamAgentChat(req, {
          onToken,
          onStep,
          onIntent: (_intent: AgentUiIntent) => {
            /* applied from done payload */
          },
        })
      } catch (_streamErr) {
        // Fallback to non-stream chat (Gateway / older backend / parse failure).
        const msg = messages.value.find((m) => m.id === assistantId)
        if (msg) {
          msg.text = ''
          msg.steps = []
        }
        res = await postAgentChat(req)
      }
      await applyChatResult(res, assistantId)
    } catch (err) {
      errorText.value = err instanceof Error ? err.message : String(err)
      const msg = messages.value.find((m) => m.id === assistantId)
      if (msg && !msg.text) {
        messages.value = messages.value.filter((m) => m.id !== assistantId)
      }
      messages.value.push({
        id: `e-${Date.now()}`,
        role: 'system',
        text: `请求失败：${errorText.value}`,
      })
    } finally {
      sending.value = false
      void scrollToBottom()
    }
  }

function onKeydown(ev: KeyboardEvent) {
  if (ev.key === 'Enter' && !ev.shiftKey) {
    ev.preventDefault()
    void send()
  }
}
</script>

<template>
  <aside
    v-if="open"
    class="agent-chat-panel"
    :style="panelStyle"
    role="dialog"
    aria-label="地图助手对话"
  >
    <header class="agent-chat-header">
      <div class="agent-chat-title">
        <span class="agent-chat-dot" aria-hidden="true" />
        <span>地图助手</span>
      </div>
      <button type="button" class="agent-chat-close" aria-label="关闭" @click="emit('close')">
        <X :size="16" />
      </button>
    </header>

    <div ref="listRef" class="agent-chat-list">
      <div
        v-for="msg in messages"
        :key="msg.id"
        class="agent-chat-bubble"
        :class="`agent-chat-bubble--${msg.role}`"
      >
        <pre class="agent-chat-text">{{
          msg.text || (sending && msg.role === 'assistant' ? '…' : '')
        }}</pre>
        <details v-if="msg.steps?.length" class="agent-chat-steps" open>
          <summary>过程（{{ msg.steps.length }}）</summary>
          <ul>
            <li v-for="(step, idx) in msg.steps" :key="idx">
              <strong>{{ step.type }}</strong> — {{ step.summary }}
              <pre v-if="step.detail" class="agent-chat-step-detail">{{ step.detail }}</pre>
            </li>
          </ul>
        </details>
        <div
          v-for="card in msg.confirmations || []"
          :key="card.confirmation_id"
          class="agent-confirm-card"
          :data-status="card.status"
        >
          <div class="agent-confirm-title">确认提交工作流</div>
          <div class="agent-confirm-summary">{{ confirmSummaryLabel(card) }}</div>
          <p v-if="card.message" class="agent-confirm-msg">{{ card.message }}</p>
          <div v-if="card.status === 'pending'" class="agent-confirm-meta">
            <template v-if="remainingSeconds(card.expires_at) != null">
              剩余 {{ remainingSeconds(card.expires_at) }}s
            </template>
            <template v-else>待确认</template>
          </div>
          <div v-else class="agent-confirm-meta">
            {{ card.resultMessage || card.status }}
          </div>
          <div v-if="card.status === 'pending'" class="agent-confirm-actions">
            <button
              type="button"
              class="agent-confirm-approve"
              :disabled="card.busy || (remainingSeconds(card.expires_at) === 0)"
              @click="resolveConfirmation(msg.id, card.confirmation_id, 'approve')"
            >
              确认提交
            </button>
            <button
              type="button"
              class="agent-confirm-reject"
              :disabled="card.busy"
              @click="resolveConfirmation(msg.id, card.confirmation_id, 'reject')"
            >
              取消
            </button>
          </div>
        </div>
        <div v-if="msg.usage" class="agent-chat-usage">
          tokens: {{ msg.usage.total_tokens
          }}{{ msg.usage.estimated ? '（估算）' : '' }}
        </div>
      </div>
    </div>

    <footer class="agent-chat-footer">
      <textarea
        v-model="input"
        class="agent-chat-input"
        rows="3"
        placeholder="输入指令，Enter 发送"
        :disabled="sending"
        @keydown="onKeydown"
      />
      <button
        type="button"
        class="agent-chat-send"
        :disabled="sending || !input.trim()"
        @click="send"
      >
        {{ sending ? '…' : '发送' }}
      </button>
    </footer>
    <span class="agent-chat-resize-hint" aria-hidden="true" title="拖拽右下角调整大小" />
  </aside>
</template>

<style scoped>
.agent-chat-panel {
  position: fixed;
  z-index: 1601;
  pointer-events: auto;
  min-width: 340px;
  min-height: 300px;
  width: min(440px, calc(100vw - 24px));
  max-width: min(720px, calc(100vw - 24px));
  max-height: min(580px, calc(100vh - 96px));
  display: flex;
  flex-direction: column;
  border-radius: 16px;
  border: 1px solid var(--border-default);
  background: color-mix(in srgb, var(--surface-2) 92%, transparent);
  color: var(--text-primary);
  box-shadow:
    0 18px 48px rgba(0, 0, 0, 0.36),
    0 0 0 1px color-mix(in srgb, var(--accent-surface) 35%, transparent) inset;
  overflow: hidden;
  backdrop-filter: blur(12px);
  resize: both;
  animation: agent-panel-in 260ms cubic-bezier(0.22, 1, 0.36, 1);
}

@keyframes agent-panel-in {
  from {
    opacity: 0;
    transform: translateY(12px) scale(0.96);
  }
  to {
    opacity: 1;
    transform: translateY(0) scale(1);
  }
}

@media (prefers-reduced-motion: reduce) {
  .agent-chat-panel {
    animation: none;
  }
}

.agent-chat-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.6rem 0.85rem;
  border-bottom: 1px solid var(--border-subtle);
  background: var(--surface-3);
  flex-shrink: 0;
  min-height: 2.65rem;
}

.agent-chat-title {
  display: flex;
  align-items: center;
  gap: 0.45rem;
  font-size: var(--font-size-body);
  font-weight: 600;
  color: var(--text-primary);
}

.agent-chat-dot {
  width: 0.4rem;
  height: 0.4rem;
  border-radius: 50%;
  background: var(--accent);
  box-shadow: 0 0 6px color-mix(in srgb, var(--accent) 55%, transparent);
}

.agent-chat-close {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 1.6rem;
  height: 1.6rem;
  border: none;
  border-radius: 7px;
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  transition: background 160ms ease, color 160ms ease, transform 160ms ease;
}

.agent-chat-close:hover {
  background: var(--surface-hover);
  color: var(--text-primary);
}

.agent-chat-close:active {
  transform: scale(0.92);
}

.agent-chat-list {
  flex: 1;
  overflow: auto;
  padding: 0.75rem 0.85rem;
  display: flex;
  flex-direction: column;
  gap: 0.55rem;
  min-height: 180px;
}

.agent-chat-bubble {
  max-width: 92%;
  padding: 0.5rem 0.65rem;
  border-radius: 10px;
  border: 1px solid var(--border-subtle);
  background: var(--surface-1);
  animation: agent-bubble-msg 200ms ease-out;
}

@keyframes agent-bubble-msg {
  from {
    opacity: 0;
    transform: translateY(6px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.agent-chat-bubble--user {
  align-self: flex-end;
  background: var(--accent-surface);
  border-color: var(--accent-border);
}

.agent-chat-bubble--assistant {
  align-self: flex-start;
}

.agent-chat-bubble--system {
  align-self: stretch;
  background: var(--surface-sunken);
  color: var(--text-secondary);
  font-size: var(--font-size-caption);
}

.agent-chat-text {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
  font-family: inherit;
  font-size: var(--font-size-caption);
  line-height: 1.5;
}

.agent-chat-usage {
  margin-top: 0.35rem;
  font-size: 0.65rem;
  letter-spacing: 0.02em;
  opacity: 0.65;
}

.agent-chat-steps {
  margin-top: 0.45rem;
  font-size: var(--font-size-caption);
  line-height: 1.45;
  opacity: 0.9;
  border-top: 1px solid var(--border-subtle);
  padding-top: 0.4rem;
}

.agent-chat-steps summary {
  cursor: pointer;
  user-select: none;
  color: var(--text-secondary);
  font-weight: 500;
}

.agent-chat-steps ul {
  margin: 0.3rem 0 0;
  padding-left: 1rem;
  color: var(--text-muted);
}

.agent-chat-step-detail {
  margin: 0.15rem 0 0.25rem;
  white-space: pre-wrap;
  word-break: break-word;
  font-family: inherit;
  font-size: 0.625rem;
  line-height: 1.35;
  opacity: 0.85;
  max-height: 6rem;
  overflow: auto;
}

.agent-confirm-card {
  margin-top: 0.55rem;
  padding: 0.55rem 0.6rem;
  border-radius: 8px;
  border: 1px solid var(--accent-border);
  background: color-mix(in srgb, var(--accent-surface) 55%, var(--surface-1));
}

.agent-confirm-card[data-status='approved'] {
  border-color: color-mix(in srgb, #3d9a5f 50%, var(--border-subtle));
  opacity: 0.92;
}

.agent-confirm-card[data-status='rejected'],
.agent-confirm-card[data-status='error'] {
  opacity: 0.75;
  border-color: var(--border-subtle);
}

.agent-confirm-title {
  font-size: var(--font-size-caption);
  font-weight: 600;
  color: var(--text-primary);
}

.agent-confirm-summary {
  margin-top: 0.2rem;
  font-size: var(--font-size-caption);
  color: var(--text-secondary);
  word-break: break-word;
}

.agent-confirm-msg {
  margin: 0.35rem 0 0;
  font-size: 0.7rem;
  line-height: 1.4;
  color: var(--text-muted);
}

.agent-confirm-meta {
  margin-top: 0.35rem;
  font-size: 0.65rem;
  color: var(--text-muted);
}

.agent-confirm-actions {
  display: flex;
  gap: 0.4rem;
  margin-top: 0.5rem;
}

.agent-confirm-approve,
.agent-confirm-reject {
  flex: 1;
  border-radius: 6px;
  border: 1px solid var(--border-default);
  padding: 0.35rem 0.5rem;
  font-size: var(--font-size-caption);
  cursor: pointer;
  transition: background 140ms ease, opacity 140ms ease;
}

.agent-confirm-approve {
  background: var(--accent);
  color: var(--text-on-accent, #fff);
  border-color: transparent;
}

.agent-confirm-approve:disabled,
.agent-confirm-reject:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.agent-confirm-reject {
  background: var(--surface-2);
  color: var(--text-secondary);
}

.agent-chat-footer {
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 0.55rem;
  padding: 0.7rem 0.85rem 0.85rem;
  border-top: 1px solid var(--border-subtle);
  background: var(--surface-3);
  flex-shrink: 0;
  align-items: end;
}

.agent-chat-input {
  resize: none;
  border-radius: 10px;
  border: 1px solid var(--border-default);
  background: var(--surface-1);
  color: var(--text-primary);
  padding: 0.5rem 0.65rem;
  font: inherit;
  font-size: var(--font-size-caption);
  line-height: 1.45;
  min-height: 3.9rem;
}

.agent-chat-input:focus {
  outline: 2px solid var(--accent-focus-ring);
  border-color: var(--accent-border);
}

.agent-chat-send {
  align-self: end;
  min-width: 3.75rem;
  height: 2.35rem;
  border-radius: 10px;
  border: 1px solid var(--accent-border);
  background: var(--accent-surface);
  color: var(--accent-strong);
  font-size: var(--font-size-caption);
  font-weight: 600;
  cursor: pointer;
  transition: transform 140ms ease, background 140ms ease, opacity 140ms ease;
}

.agent-chat-send:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.agent-chat-send:not(:disabled):hover {
  background: var(--surface-hover);
}

.agent-chat-send:not(:disabled):active {
  transform: scale(0.96);
}

.agent-chat-resize-hint {
  position: absolute;
  right: 4px;
  bottom: 4px;
  width: 12px;
  height: 12px;
  border-radius: 2px;
  background:
    linear-gradient(
      135deg,
      transparent 45%,
      color-mix(in srgb, var(--text-muted) 55%, transparent) 46%,
      color-mix(in srgb, var(--text-muted) 55%, transparent) 54%,
      transparent 55%
    ),
    linear-gradient(
      135deg,
      transparent 62%,
      color-mix(in srgb, var(--text-muted) 55%, transparent) 63%,
      color-mix(in srgb, var(--text-muted) 55%, transparent) 71%,
      transparent 72%
    );
  pointer-events: none;
  opacity: 0.7;
}
</style>
