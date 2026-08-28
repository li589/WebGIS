<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { X } from '../ui/icons'
import { postAgentChat, type AgentChatResponse } from '../../services/agent-api'
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
  return {
    active_layers: workspace.activeLayers.value
      .filter((l) => !l.isAdminBoundary)
      .map((l) => ({
        catalog_id: l.catalogId,
        instance_id: l.instanceId,
        name: l.name || l.catalogId,
      })),
  }
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
  void scrollToBottom()
  sending.value = true
  try {
    const res: AgentChatResponse = await postAgentChat({
      message: text,
      session_id: sessionId.value,
      client_context: buildClientContext(),
    })
    sessionId.value = res.session_id
    messages.value.push({
      id: `a-${Date.now()}`,
      role: 'assistant',
      text: res.reply,
      usage: res.usage
        ? {
            total_tokens: res.usage.total_tokens,
            estimated: res.usage.estimated,
          }
        : null,
      steps: res.steps?.length ? res.steps : undefined,
    })
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
  } catch (err) {
    errorText.value = err instanceof Error ? err.message : String(err)
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
        <pre class="agent-chat-text">{{ msg.text }}</pre>
        <details v-if="msg.steps?.length" class="agent-chat-steps">
          <summary>过程（{{ msg.steps.length }}）</summary>
          <ul>
            <li v-for="(step, idx) in msg.steps" :key="idx">
              <strong>{{ step.type }}</strong> — {{ step.summary }}
              <pre v-if="step.detail" class="agent-chat-step-detail">{{ step.detail }}</pre>
            </li>
          </ul>
        </details>
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
  min-width: 320px;
  min-height: 280px;
  width: min(420px, calc(100vw - 24px));
  max-width: min(720px, calc(100vw - 24px));
  max-height: min(560px, calc(100vh - 96px));
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
  padding: 0.7rem 0.85rem;
  border-bottom: 1px solid var(--border-subtle);
  background: var(--surface-3);
  flex-shrink: 0;
}

.agent-chat-title {
  display: flex;
  align-items: center;
  gap: 0.45rem;
  font-size: 0.9rem;
  font-weight: 600;
  color: var(--text-strong);
}

.agent-chat-dot {
  width: 0.5rem;
  height: 0.5rem;
  border-radius: 50%;
  background: var(--accent);
  box-shadow: 0 0 8px color-mix(in srgb, var(--accent) 60%, transparent);
}

.agent-chat-close {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 1.75rem;
  height: 1.75rem;
  border: none;
  border-radius: 8px;
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
  padding: 0.85rem;
  display: flex;
  flex-direction: column;
  gap: 0.55rem;
  min-height: 200px;
}

.agent-chat-bubble {
  max-width: 92%;
  padding: 0.55rem 0.7rem;
  border-radius: 12px;
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
  font-size: 0.75rem;
}

.agent-chat-text {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
  font-family: inherit;
  font-size: 0.8375rem;
  line-height: 1.5;
}

.agent-chat-usage {
  margin-top: 0.35rem;
  font-size: 0.65rem;
  opacity: 0.65;
}

.agent-chat-steps {
  margin-top: 0.4rem;
  font-size: 0.7rem;
  opacity: 0.85;
}

.agent-chat-steps summary {
  cursor: pointer;
  user-select: none;
}

.agent-chat-steps ul {
  margin: 0.35rem 0 0;
  padding-left: 1.1rem;
}

.agent-chat-step-detail {
  margin: 0.2rem 0 0;
  white-space: pre-wrap;
  word-break: break-word;
  font-family: inherit;
  font-size: 0.65rem;
  opacity: 0.8;
}

.agent-chat-footer {
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 0.55rem;
  padding: 0.7rem 0.85rem 0.85rem;
  border-top: 1px solid var(--border-subtle);
  background: var(--surface-3);
  flex-shrink: 0;
}

.agent-chat-input {
  resize: none;
  border-radius: 10px;
  border: 1px solid var(--border-default);
  background: var(--surface-1);
  color: var(--text-primary);
  padding: 0.5rem 0.6rem;
  font: inherit;
  font-size: 0.8375rem;
  min-height: 4.5rem;
}

.agent-chat-input:focus {
  outline: 2px solid var(--accent-focus-ring);
  border-color: var(--accent-border);
}

.agent-chat-send {
  align-self: end;
  min-width: 3.75rem;
  height: 2.4rem;
  border-radius: 10px;
  border: 1px solid var(--accent-border);
  background: var(--accent-surface);
  color: var(--accent-strong);
  font-size: 0.8375rem;
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
