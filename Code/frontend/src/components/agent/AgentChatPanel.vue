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
import { renderAgentMarkdown } from '../../utils/agent-markdown'
import { executeAgentUiIntents } from './agent-ui-intent'
import { agentMapPoint } from '../../stores/agent-map-point'
import 'katex/dist/katex.min.css'

const props = defineProps<{
  open: boolean
  /** 挂件拖动中：面板位置跟随但不播过渡，避免拖影卡顿 */
  dragging?: boolean
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
  /** 助手消息的消毒 HTML；流式中为空，结束后再填 */
  html?: string
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
  /** 结束后是否默认展开「过程」（有工具步骤时） */
  keepStepsOpen?: boolean
}

const WELCOME_TEXT = '你好，我是地图助手。试试「打开 CMFD 降水」或「有哪些活动图层」。'

const workspace = useLayerWorkspace()
const messages = ref<ChatMessage[]>([
  {
    id: 'welcome',
    role: 'assistant',
    text: WELCOME_TEXT,
    html: renderAgentMarkdown(WELCOME_TEXT),
  },
])

function finalizeAssistantHtml(msg: ChatMessage) {
  if (msg.role !== 'assistant') return
  msg.html = msg.text ? renderAgentMarkdown(msg.text) : ''
}
const input = ref('')
const sending = ref(false)
const sessionId = ref<string | null>(null)
const listRef = ref<HTMLElement | null>(null)
const inputRef = ref<HTMLTextAreaElement | null>(null)
const errorText = ref<string | null>(null)
const nowMs = ref(Date.now())
const streamingId = ref<string | null>(null)
/** 发送阶段：让用户区分「连不上 / 在想 / 在调工具 / 在出字 / 回退」 */
const streamPhase = ref<'idle' | 'connecting' | 'working' | 'streaming' | 'fallback'>('idle')
const liveStatus = ref('')
const stepsOpen = ref(false)
const sendStartedAt = ref(0)
let tickTimer: ReturnType<typeof setInterval> | null = null
let sendTickTimer: ReturnType<typeof setInterval> | null = null
let scrollRaf: number | null = null
let streamTextRaf: number | null = null
let pendingStreamText: { id: string; text: string } | null = null
/** 用户上滚阅读时不强制吸底 */
let stickToBottom = true

const elapsedWaitLabel = computed(() => {
  if (!sending.value || !sendStartedAt.value) return ''
  const s = Math.max(0, Math.floor((nowMs.value - sendStartedAt.value) / 1000))
  if (s < 2) return ''
  return `已等待 ${s}s`
})

const statusLabel = computed(() => {
  if (!sending.value) return ''
  const wait = elapsedWaitLabel.value
  const suffix = wait ? `（${wait}）` : ''
  if (liveStatus.value) return `${liveStatus.value}${suffix}`
  switch (streamPhase.value) {
    case 'connecting':
      return `正在连接助手…${suffix}`
    case 'working':
      return `助手处理中（模型思考或调用工具）…${suffix}`
    case 'streaming':
      return `正在生成回复…${suffix}`
    case 'fallback':
      return `流式通道失败，改用普通请求…${suffix}`
    default:
      return `处理中…${suffix}`
  }
})

function startExpiryTick() {
  if (tickTimer != null) return
  tickTimer = setInterval(() => {
    nowMs.value = Date.now()
  }, 1000)
}

function startSendTick() {
  sendStartedAt.value = Date.now()
  nowMs.value = Date.now()
  if (sendTickTimer != null) return
  sendTickTimer = setInterval(() => {
    nowMs.value = Date.now()
  }, 1000)
}

function stopSendTick() {
  sendStartedAt.value = 0
  if (sendTickTimer != null) {
    clearInterval(sendTickTimer)
    sendTickTimer = null
  }
}

onUnmounted(() => {
  if (tickTimer != null) {
    clearInterval(tickTimer)
    tickTimer = null
  }
  stopSendTick()
  if (scrollRaf != null) cancelAnimationFrame(scrollRaf)
  if (streamTextRaf != null) cancelAnimationFrame(streamTextRaf)
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
  const ctx: {
    active_catalog_ids: string[]
    active_layers: Array<{ catalog_id: string; instance_id?: string; name?: string }>
    map_point?: { lng: number; lat: number }
  } = {
    active_catalog_ids: layers.map((l) => l.catalogId).filter(Boolean),
    active_layers: layers.map((l) => ({
      catalog_id: l.catalogId,
      instance_id: l.instanceId,
      name: l.name || l.catalogId,
    })),
  }
  const pt = agentMapPoint.value
  if (pt) {
    ctx.map_point = { lng: pt.lng, lat: pt.lat }
  }
  return ctx
}

const mapPointLabel = computed(() => {
  const pt = agentMapPoint.value
  if (!pt) return null
  return `${pt.lng.toFixed(4)}, ${pt.lat.toFixed(4)}`
})

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

function onListScroll() {
  const el = listRef.value
  if (!el) return
  const gap = el.scrollHeight - el.scrollTop - el.clientHeight
  stickToBottom = gap < 48
}

function scheduleScrollToBottom(force = false) {
  if (!force && !stickToBottom) return
  if (scrollRaf != null) return
  scrollRaf = requestAnimationFrame(() => {
    scrollRaf = null
    const el = listRef.value
    if (el) el.scrollTop = el.scrollHeight
  })
}

async function scrollToBottom() {
  stickToBottom = true
  await nextTick()
  scheduleScrollToBottom(true)
}

function flushStreamText() {
  streamTextRaf = null
  const pending = pendingStreamText
  pendingStreamText = null
  if (!pending) return
  const msg = messages.value.find((m) => m.id === pending.id)
  if (msg) {
    msg.text = pending.text
    msg.html = undefined
  }
  scheduleScrollToBottom()
}

function appendStreamChunk(assistantId: string, chunk: string) {
  const msg = messages.value.find((m) => m.id === assistantId)
  if (!msg) return
  const base = pendingStreamText?.id === assistantId ? pendingStreamText.text : msg.text || ''
  pendingStreamText = { id: assistantId, text: `${base}${chunk}` }
  if (streamTextRaf == null) {
    streamTextRaf = requestAnimationFrame(flushStreamText)
  }
}

function autosizeInput() {
  const el = inputRef.value
  if (!el) return
  el.style.height = 'auto'
  const max = 120
  el.style.height = `${Math.min(max, Math.max(40, el.scrollHeight))}px`
}

watch(
  () => props.open,
  (open) => {
    if (open) {
      void scrollToBottom()
      void nextTick(() => {
        autosizeInput()
        inputRef.value?.focus()
      })
    }
  },
)

watch(input, () => {
  void nextTick(() => autosizeInput())
})

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
    finalizeAssistantHtml(msg)
  } else {
    const created: ChatMessage = {
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
    }
    finalizeAssistantHtml(created)
    messages.value.push(created)
  }

  const target = messages.value.find((m) => m.id === assistantId)
  if (res.ui_intents?.length) {
    const results = executeAgentUiIntents(res.ui_intents, {
      fitToLayerExtent: props.fitToLayerExtent,
    })
    const noteBodies = results
      .filter((r) => r.message)
      .map((r) => ({
        ok: r.ok,
        body: r.message,
        line: r.ok ? `✓ ${r.message}` : `✗ ${r.message}`,
      }))
    // 模型只调了 list_active_layers 等意图、正文为空时：把意图结果填进助手气泡，避免「吞回复」
    if (target && !String(target.text || '').trim() && noteBodies.length) {
      target.text = noteBodies.map((n) => n.body).join('\n\n')
      finalizeAssistantHtml(target)
    } else if (noteBodies.length) {
      messages.value.push({
        id: `s-${Date.now()}`,
        role: 'system',
        text: noteBodies.map((n) => n.line).join('\n'),
      })
    }
  }
  if (target) {
    const trimmed = String(target.text || '').trim()
    if (!trimmed || trimmed === '（模型未返回文本）') {
      const fromSteps = synthesizeReplyFromSteps(target.steps)
      if (fromSteps) {
        target.text = fromSteps
        finalizeAssistantHtml(target)
      } else if (!trimmed) {
        target.text =
          '（助手未返回可见文本。可展开「过程」查看工具步骤，或换一种问法重试。）'
        finalizeAssistantHtml(target)
      }
    }
    if (target.steps?.some((s) => s.type === 'tool' || s.type === 'tool_result')) {
      target.keepStepsOpen = true
    }
  }
}

function synthesizeReplyFromSteps(
  steps: ChatMessage['steps'],
): string | null {
  if (!steps?.length) return null
  for (let i = steps.length - 1; i >= 0; i -= 1) {
    const step = steps[i]
    if (step.type !== 'tool_result' || !step.detail) continue
    try {
      const data = JSON.parse(step.detail) as Record<string, unknown>
      if (!data || typeof data !== 'object') continue
      if (!data.ok) {
        const err = typeof data.error === 'string' ? data.error : ''
        if (err) return `工具调用未成功：${err}`
        continue
      }
      const layers = data.layers
      if (Array.isArray(layers)) {
        const q = typeof data.query === 'string' ? data.query : ''
        if (!layers.length) {
          return `未在图层库中找到与「${q || '该关键词'}」匹配的图层。若要查看已添加图层，请说「有哪些活动图层」。`
        }
        const lines = layers
          .filter((x): x is Record<string, unknown> => !!x && typeof x === 'object')
          .map((item) => {
            const id = String(item.layer_id || '')
            const name = String(item.display_name || id)
            return `- ${name}（\`${id}\`）`
          })
        return (
          (q
            ? `图层库搜索「${q}」命中 ${lines.length} 条：\n`
            : `找到 ${lines.length} 个图层：\n`) + lines.join('\n')
        )
      }
    } catch {
      /* ignore */
    }
  }
  return null
}

async function send() {
  const text = input.value.trim()
  if (!text || sending.value) return
  input.value = ''
  void nextTick(() => autosizeInput())
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
  streamingId.value = assistantId
  streamPhase.value = 'connecting'
  liveStatus.value = '正在连接助手…'
  stepsOpen.value = true
  startSendTick()

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
    streamPhase.value = 'working'
    liveStatus.value =
      step.type === 'tool'
        ? `正在调用工具：${step.summary}`
        : step.type === 'tool_result'
          ? `工具已返回：${step.summary}`
          : step.summary || '助手处理中…'
    scheduleScrollToBottom()
  }
  const onToken = (chunk: string) => {
    streamPhase.value = 'streaming'
    liveStatus.value = '正在生成回复…'
    appendStreamChunk(assistantId, chunk)
  }

  try {
    let res: AgentChatResponse
    try {
      res = await streamAgentChat(req, {
        onToken,
        onStep,
        onConnected: () => {
          if (streamPhase.value === 'connecting') {
            streamPhase.value = 'working'
            liveStatus.value = '已连接，等待模型或工具…'
          }
        },
        onIntent: (_intent: AgentUiIntent) => {
          /* applied from done payload */
        },
      })
    } catch (_streamErr) {
      pendingStreamText = null
      if (streamTextRaf != null) {
        cancelAnimationFrame(streamTextRaf)
        streamTextRaf = null
      }
      // 保留已收到的 step / 部分正文，避免「吞掉过程」；仅清空未完成流缓冲
      streamPhase.value = 'fallback'
      const reason = _streamErr instanceof Error ? _streamErr.message : String(_streamErr)
      liveStatus.value = `流式失败（${reason.slice(0, 80)}），改用普通请求…`
      messages.value.push({
        id: `fb-${Date.now()}`,
        role: 'system',
        text: `流式通道不可用，已自动改用普通请求。\n原因：${reason}`,
      })
      res = await postAgentChat(req)
    }
    flushStreamText()
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
    const msg = messages.value.find((m) => m.id === assistantId)
    const keepStepsOpen = Boolean(
      msg?.steps?.some((s) => s.type === 'tool' || s.type === 'tool_result') ||
        msg?.keepStepsOpen,
    )
    if (msg) msg.keepStepsOpen = keepStepsOpen
    sending.value = false
    streamingId.value = null
    streamPhase.value = 'idle'
    liveStatus.value = ''
    stepsOpen.value = keepStepsOpen
    stopSendTick()
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
    :class="{ 'agent-chat-panel--dragging': dragging }"
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

    <div ref="listRef" class="agent-chat-list" @scroll.passive="onListScroll">
      <div
        v-for="msg in messages"
        :key="msg.id"
        class="agent-chat-bubble"
        :class="[
          `agent-chat-bubble--${msg.role}`,
          msg.id === streamingId ? 'agent-chat-bubble--streaming' : '',
        ]"
      >
        <div
          v-if="msg.role === 'assistant' && msg.html != null && msg.html !== ''"
          class="agent-chat-md agent-scroll"
          v-html="msg.html"
        />
        <pre v-else class="agent-chat-text agent-scroll">{{
          msg.text ||
          (msg.id === streamingId && sending
            ? streamPhase === 'connecting'
              ? '正在连接助手…'
              : streamPhase === 'fallback'
                ? '流式失败，改用普通请求…'
                : streamPhase === 'working'
                  ? liveStatus || '助手处理中…'
                  : '…'
            : '')
        }}</pre>
        <details
          v-if="msg.steps?.length"
          class="agent-chat-steps"
          :open="msg.id === streamingId ? stepsOpen : msg.keepStepsOpen"
        >
          <summary>过程（{{ msg.steps.length }}）</summary>
          <ul>
            <li v-for="(step, idx) in msg.steps" :key="idx">
              <strong>{{ step.type }}</strong> — {{ step.summary }}
              <pre v-if="step.detail" class="agent-chat-step-detail agent-scroll">{{
                step.detail
              }}</pre>
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
              :disabled="card.busy || remainingSeconds(card.expires_at) === 0"
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
          tokens: {{ msg.usage.total_tokens }}{{ msg.usage.estimated ? '（估算）' : '' }}
        </div>
      </div>
    </div>

    <footer class="agent-chat-footer">
      <div class="agent-chat-context" aria-live="polite">
        <span v-if="mapPointLabel" class="agent-chat-chip" title="地图选点将随对话一并发送">
          选点 {{ mapPointLabel }}
        </span>
        <span v-else class="agent-chat-chip agent-chat-chip--muted">
          地图点击选点后可查坐标与图层值
        </span>
      </div>
      <p
        v-if="sending && statusLabel"
        class="agent-chat-status"
        role="status"
        aria-live="polite"
      >
        <span class="agent-chat-status-dot" aria-hidden="true" />
        {{ statusLabel }}
      </p>
      <textarea
        ref="inputRef"
        v-model="input"
        class="agent-chat-input"
        rows="1"
        placeholder="输入指令，Enter 发送 · Shift+Enter 换行"
        :disabled="sending"
        @keydown="onKeydown"
        @input="autosizeInput"
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

.agent-chat-panel--dragging {
  animation: none;
  transition: none;
  /* 拖动跟随：减少重绘毛边 */
  will-change: left, top;
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
  transition:
    background 160ms ease,
    color 160ms ease,
    transform 160ms ease;
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
  min-height: 140px;
  overscroll-behavior: contain;
}

/* 浅/深主题滚动条：跟设置面板同一套 token */
.agent-scroll,
.agent-chat-list,
.agent-chat-input {
  scrollbar-width: thin;
  scrollbar-color: var(--border-accent) var(--border-subtle);
}

.agent-scroll::-webkit-scrollbar,
.agent-chat-list::-webkit-scrollbar,
.agent-chat-input::-webkit-scrollbar {
  width: 5px;
  height: 5px;
}

.agent-scroll::-webkit-scrollbar-track,
.agent-chat-list::-webkit-scrollbar-track,
.agent-chat-input::-webkit-scrollbar-track {
  background: var(--border-subtle);
  border-radius: 4px;
}

.agent-scroll::-webkit-scrollbar-thumb,
.agent-chat-list::-webkit-scrollbar-thumb,
.agent-chat-input::-webkit-scrollbar-thumb {
  background: var(--border-accent);
  border-radius: 4px;
  border: 1px solid transparent;
  background-clip: padding-box;
}

.agent-scroll::-webkit-scrollbar-thumb:hover,
.agent-chat-list::-webkit-scrollbar-thumb:hover,
.agent-chat-input::-webkit-scrollbar-thumb:hover {
  background: var(--border-strong);
}

.agent-scroll::-webkit-scrollbar-corner,
.agent-chat-list::-webkit-scrollbar-corner {
  background: transparent;
}

.agent-chat-bubble {
  max-width: 92%;
  padding: 0.5rem 0.65rem;
  border-radius: 10px;
  border: 1px solid var(--border-subtle);
  background: var(--surface-1);
  /* 长列表：远离视口的气泡降低绘制成本 */
  content-visibility: auto;
  contain-intrinsic-size: auto 72px;
}

.agent-chat-bubble--user {
  align-self: flex-end;
  background: var(--accent-surface);
  border-color: var(--accent-border);
  animation: agent-bubble-msg 200ms ease-out;
}

.agent-chat-bubble--assistant {
  align-self: flex-start;
}

.agent-chat-bubble--assistant:not(.agent-chat-bubble--streaming) {
  animation: agent-bubble-msg 200ms ease-out;
}

.agent-chat-bubble--system {
  align-self: stretch;
  background: var(--surface-sunken);
  color: var(--text-secondary);
  font-size: var(--font-size-caption);
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

.agent-chat-text {
  margin: 0;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  word-break: break-word;
  font-family: inherit;
  font-size: var(--font-size-caption);
  line-height: 1.5;
  max-height: min(42vh, 320px);
  overflow: auto;
}

.agent-chat-md {
  margin: 0;
  font-size: var(--font-size-caption);
  line-height: 1.55;
  overflow-wrap: anywhere;
  word-break: break-word;
  max-height: min(42vh, 360px);
  overflow: auto;
  color: var(--text-primary);
}

.agent-chat-md :deep(:first-child) {
  margin-top: 0;
}

.agent-chat-md :deep(:last-child) {
  margin-bottom: 0;
}

.agent-chat-md :deep(p),
.agent-chat-md :deep(ul),
.agent-chat-md :deep(ol),
.agent-chat-md :deep(blockquote),
.agent-chat-md :deep(pre),
.agent-chat-md :deep(table) {
  margin: 0.4em 0;
}

.agent-chat-md :deep(h1),
.agent-chat-md :deep(h2),
.agent-chat-md :deep(h3),
.agent-chat-md :deep(h4) {
  margin: 0.55em 0 0.3em;
  font-size: 1.05em;
  font-weight: 650;
  line-height: 1.35;
  color: var(--text-primary);
}

.agent-chat-md :deep(ul),
.agent-chat-md :deep(ol) {
  padding-left: 1.25em;
}

.agent-chat-md :deep(li + li) {
  margin-top: 0.15em;
}

.agent-chat-md :deep(a) {
  color: var(--accent-strong);
  text-decoration: underline;
  text-underline-offset: 2px;
}

.agent-chat-md :deep(blockquote) {
  margin-left: 0;
  padding: 0.25em 0.65em;
  border-left: 3px solid var(--border-accent);
  color: var(--text-secondary);
  background: color-mix(in srgb, var(--surface-sunken) 70%, transparent);
}

.agent-chat-md :deep(code) {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 0.92em;
  padding: 0.1em 0.35em;
  border-radius: 4px;
  background: var(--surface-sunken);
  color: var(--text-primary);
  border: 1px solid var(--border-subtle);
}

.agent-chat-md :deep(pre) {
  max-height: min(28vh, 220px);
  overflow: auto;
  padding: 0.55rem 0.65rem;
  border-radius: 8px;
  border: 1px solid var(--border-subtle);
  background: var(--surface-sunken);
  scrollbar-width: thin;
  scrollbar-color: var(--border-accent) var(--border-subtle);
}

.agent-chat-md :deep(pre)::-webkit-scrollbar {
  width: 5px;
  height: 5px;
}

.agent-chat-md :deep(pre)::-webkit-scrollbar-thumb {
  background: var(--border-accent);
  border-radius: 4px;
}

.agent-chat-md :deep(pre code) {
  padding: 0;
  border: none;
  background: transparent;
  font-size: 0.8rem;
  line-height: 1.45;
  white-space: pre;
  display: block;
  overflow-x: auto;
}

.agent-chat-md :deep(table) {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.8em;
  display: block;
  overflow-x: auto;
  max-width: 100%;
}

.agent-chat-md :deep(th),
.agent-chat-md :deep(td) {
  border: 1px solid var(--border-subtle);
  padding: 0.25em 0.45em;
  text-align: left;
}

.agent-chat-md :deep(th) {
  background: var(--surface-3);
  font-weight: 600;
}

.agent-chat-md :deep(.katex) {
  font-size: 1.05em;
  color: inherit;
}

.agent-chat-md :deep(.katex-display) {
  margin: 0.55em 0;
  overflow-x: auto;
  overflow-y: hidden;
  max-width: 100%;
  padding: 0.15em 0;
}

.agent-chat-md :deep(.katex-display > .katex) {
  white-space: normal;
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
  overflow-wrap: anywhere;
  word-break: break-word;
  font-family: inherit;
  font-size: 0.625rem;
  line-height: 1.35;
  opacity: 0.85;
  max-height: 5rem;
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
  transition:
    background 140ms ease,
    opacity 140ms ease;
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
  grid-template-columns: minmax(0, 1fr) auto;
  grid-template-rows: auto auto;
  gap: 0.4rem 0.5rem;
  padding: 0.55rem 0.75rem 0.75rem;
  border-top: 1px solid var(--border-subtle);
  background: var(--surface-3);
  flex-shrink: 0;
  align-items: end;
}

.agent-chat-context {
  grid-column: 1 / -1;
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem;
  min-width: 0;
}

.agent-chat-status {
  grid-column: 1 / -1;
  display: flex;
  align-items: center;
  gap: 0.4rem;
  margin: 0;
  padding: 0.28rem 0.45rem;
  border-radius: 6px;
  background: color-mix(in srgb, var(--accent) 12%, var(--surface-1));
  color: var(--text-secondary);
  font-size: 0.7rem;
  line-height: 1.35;
}

.agent-chat-status-dot {
  width: 0.45rem;
  height: 0.45rem;
  border-radius: 999px;
  background: var(--accent);
  flex: 0 0 auto;
  animation: agent-status-pulse 1.1s ease-in-out infinite;
}

@keyframes agent-status-pulse {
  0%,
  100% {
    opacity: 0.35;
    transform: scale(0.85);
  }
  50% {
    opacity: 1;
    transform: scale(1);
  }
}

.agent-chat-chip {
  display: inline-flex;
  align-items: center;
  max-width: 100%;
  padding: 0.15rem 0.45rem;
  border-radius: 6px;
  border: 1px solid var(--accent-border);
  background: color-mix(in srgb, var(--accent-surface) 55%, var(--surface-1));
  color: var(--accent-strong);
  font-size: 0.65rem;
  line-height: 1.35;
  letter-spacing: 0.01em;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.agent-chat-chip--muted {
  border-color: var(--border-subtle);
  background: var(--surface-sunken);
  color: var(--text-muted);
}

.agent-chat-input {
  resize: none;
  border-radius: 10px;
  border: 1px solid var(--border-default);
  background: var(--surface-1);
  color: var(--text-primary);
  padding: 0.55rem 0.7rem;
  font: inherit;
  font-size: var(--font-size-caption);
  line-height: 1.4;
  min-height: 2.5rem;
  max-height: 7.5rem;
  height: 2.5rem;
  box-sizing: border-box;
  overflow-y: auto;
}

.agent-chat-input:focus {
  outline: 2px solid var(--accent-focus-ring);
  border-color: var(--accent-border);
}

.agent-chat-send {
  box-sizing: border-box;
  align-self: end;
  min-width: 3.5rem;
  height: 2.5rem;
  padding: 0 0.85rem;
  border-radius: 10px;
  border: 1px solid var(--accent-border);
  background: var(--accent-surface);
  color: var(--accent-strong);
  font-size: var(--font-size-caption);
  font-weight: 600;
  cursor: pointer;
  transition:
    transform 140ms ease,
    background 140ms ease,
    opacity 140ms ease;
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
