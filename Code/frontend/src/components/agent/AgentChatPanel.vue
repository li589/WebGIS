<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onUnmounted, ref, watch } from 'vue'
import {
  Bot,
  Check,
  ChevronDown,
  Copy,
  Download,
  RefreshCw,
  Sparkles,
  Square,
  User,
  Wrench,
  X,
} from '../ui/icons'
import {
  confirmAgentAction,
  deleteAgentSession,
  fetchAgentConfig,
  getAgentSession,
  listAgentSessions,
  postAgentChat,
  streamAgentChat,
  type AgentChatResponse,
  type AgentConfirmation,
  type AgentProfile,
  type AgentSessionSummary,
  type AgentStep,
  type AgentUiIntent,
} from '../../services/agent-api'
import { useLayerWorkspace, useLayerViewport } from '../../stores/layers/selectors'
import { useUiStore } from '../../stores/ui'
import {
  AGENT_CHAT_PANEL_MAX_HEIGHT_PX,
  AGENT_CHAT_PANEL_WIDTH_PX,
  COMPANION_SIZE_PX,
} from '../../composables/useAgentCompanionPosition'
import { renderAgentMarkdown } from '../../utils/agent-markdown'
import { executeAgentUiIntent, executeAgentUiIntents } from './agent-ui-intent'
import {
  buildAgentClientContextPayload,
  exportChatMarkdown,
  extractLayerCardsFromSteps,
  isAbortError,
  isTimeoutAbortError,
  isUserInitiatedStop,
  layerCardsFromActiveLayers,
  sumSessionTokens,
  type AgentLayerCard,
} from './agent-chat-helpers'
import { agentMapPoint } from '../../stores/agent-map-point'
import 'katex/dist/katex.min.css'

const PANEL_MIN_W = 320
const PANEL_MIN_H = 280
const PANEL_MAX_W = 720
const PANEL_DEFAULT_H = 420

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
  fitChina?: () => boolean
  locateCoordinate?: (lng: number, lat: number, zoom?: number) => boolean
  setBasemap?: (sourceId: string) => boolean
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
  /** search_layers / list_active_layers 可点卡片 */
  layerCards?: AgentLayerCard[]
  /** 结束后是否默认展开「过程」（有工具步骤时） */
  keepStepsOpen?: boolean
}

const WELCOME_TEXT = '你好，我是地图助手。试试「打开 CMFD 降水」或「有哪些活动图层」。'

const workspace = useLayerWorkspace()
const viewport = useLayerViewport()
const uiStore = useUiStore()
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
const sessionMenuOpen = ref(false)
const sessionSummaries = ref<AgentSessionSummary[]>([])
const sessionsLoading = ref(false)
let tickTimer: ReturnType<typeof setInterval> | null = null
let sendTickTimer: ReturnType<typeof setInterval> | null = null
let scrollRaf: number | null = null
let streamTextRaf: number | null = null
let pendingStreamText: { id: string; text: string } | null = null
/** 用户上滚阅读时不强制吸底 */
let stickToBottom = true
/** 当前发送请求的 AbortController（停止生成） */
let sendAbort: AbortController | null = null

const sessionTokenTotal = computed(() => sumSessionTokens(messages.value))

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

const activeProfile = ref<AgentProfile | null>(null)

async function loadActiveProfile() {
  try {
    const bundle = await fetchAgentConfig()
    activeProfile.value =
      bundle.profiles.find((p) => p.id === bundle.active_profile_id) ?? bundle.profiles[0] ?? null
  } catch {
    activeProfile.value = null
  }
}

const copiedMsgId = ref<string | null>(null)
let copyTimer: ReturnType<typeof setTimeout> | null = null

async function copyMessageText(msg: ChatMessage) {
  if (!msg.text) return
  try {
    await navigator.clipboard.writeText(msg.text)
    copiedMsgId.value = msg.id
    if (copyTimer != null) clearTimeout(copyTimer)
    copyTimer = setTimeout(() => {
      copiedMsgId.value = null
      copyTimer = null
    }, 2000)
  } catch {
    /* ignore */
  }
}

const PROMPT_SUGGESTIONS = [
  '查看活动图层',
  '缩放到中国范围',
  '有哪些气象降水数据',
  '切换为天地图影像',
  '定位到北京',
]

function sendSuggestion(text: string) {
  if (sending.value) return
  input.value = text
  void send()
}

function stopGenerating() {
  if (!sending.value || !sendAbort) return
  sendAbort.abort(new DOMException('用户停止生成', 'AbortError'))
}

function resetChat() {
  if (sending.value) return
  messages.value = [
    {
      id: 'welcome',
      role: 'assistant',
      text: WELCOME_TEXT,
      html: renderAgentMarkdown(WELCOME_TEXT),
    },
  ]
  sessionId.value = null
  errorText.value = null
  streamPhase.value = 'idle'
  liveStatus.value = ''
  sessionMenuOpen.value = false
  stopSendTick()
  void scrollToBottom()
}

async function refreshSessionList() {
  sessionsLoading.value = true
  try {
    const res = await listAgentSessions(40)
    sessionSummaries.value = res.sessions || []
  } catch {
    sessionSummaries.value = []
  } finally {
    sessionsLoading.value = false
  }
}

async function toggleSessionMenu() {
  if (sending.value) return
  sessionMenuOpen.value = !sessionMenuOpen.value
  if (sessionMenuOpen.value) await refreshSessionList()
}

async function loadSession(sid: string) {
  if (sending.value || !sid) return
  sessionMenuOpen.value = false
  try {
    const detail = await getAgentSession(sid)
    sessionId.value = detail.session_id
    const restored: ChatMessage[] = (detail.messages || [])
      .filter((m) => m.role === 'user' || m.role === 'assistant')
      .map((m, idx) => {
        const msg: ChatMessage = {
          id: `restored-${sid}-${idx}`,
          role: m.role as 'user' | 'assistant',
          text: m.content || '',
        }
        if (msg.role === 'assistant') finalizeAssistantHtml(msg)
        return msg
      })
    messages.value = restored.length
      ? restored
      : [
          {
            id: 'welcome',
            role: 'assistant',
            text: WELCOME_TEXT,
            html: renderAgentMarkdown(WELCOME_TEXT),
          },
        ]
    errorText.value = null
    void scrollToBottom()
  } catch (err) {
    messages.value.push({
      id: `sess-err-${Date.now()}`,
      role: 'system',
      text: `加载会话失败：${err instanceof Error ? err.message : String(err)}`,
    })
  }
}

async function removeSession(sid: string) {
  if (sending.value || !sid) return
  try {
    await deleteAgentSession(sid)
    if (sessionId.value === sid) resetChat()
    await refreshSessionList()
  } catch (err) {
    messages.value.push({
      id: `sess-del-err-${Date.now()}`,
      role: 'system',
      text: `删除会话失败：${err instanceof Error ? err.message : String(err)}`,
    })
  }
}

function downloadChatExport() {
  const md = exportChatMarkdown(
    messages.value.map((m) => ({
      role: m.role,
      text: m.text,
      usage: m.usage,
    })),
    { sessionId: sessionId.value, title: 'CGDA 地图助手会话' },
  )
  const blob = new Blob([md], { type: 'text/markdown;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `cgda-agent-${sessionId.value || 'draft'}-${Date.now()}.md`
  a.click()
  URL.revokeObjectURL(url)
}

function runLayerCardAction(card: AgentLayerCard, action: 'open' | 'fit') {
  const intent =
    action === 'open'
      ? {
          name: 'set_layer_visibility' as const,
          args: { catalog_id: card.catalog_id, visible: true },
        }
      : {
          name: 'fit_layer' as const,
          args: { catalog_id: card.catalog_id },
        }
  const result = executeAgentUiIntent(intent, {
    fitToLayerExtent: props.fitToLayerExtent,
    fitChina: props.fitChina,
    locateCoordinate: props.locateCoordinate,
    setBasemap: props.setBasemap,
  })
  messages.value.push({
    id: `card-${Date.now()}`,
    role: 'system',
    text: result.ok ? `✓ ${result.message}` : `✗ ${result.message}`,
  })
  void scrollToBottom()
}

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
  sendAbort?.abort()
  sendAbort = null
  if (tickTimer != null) {
    clearInterval(tickTimer)
    tickTimer = null
  }
  stopSendTick()
  if (scrollRaf != null) cancelAnimationFrame(scrollRaf)
  if (streamTextRaf != null) cancelAnimationFrame(streamTextRaf)
  if (copyTimer != null) {
    clearTimeout(copyTimer)
    copyTimer = null
  }
})

/** 视口绝对位置（打开时由锚点初始化；拖动/缩放只改这些值，避免锚点重算跳动） */
const absLeft = ref(12)
const absTop = ref(72)
const sizeW = ref(AGENT_CHAT_PANEL_WIDTH_PX)
const sizeH = ref(PANEL_DEFAULT_H)
const panelDragging = ref(false)
const panelResizing = ref(false)

let dragPtrId: number | null = null
let dragStartX = 0
let dragStartY = 0
let dragBaseLeft = 0
let dragBaseTop = 0

let resizePtrId: number | null = null
let resizeStartX = 0
let resizeStartY = 0
let resizeBaseW = 0
let resizeBaseH = 0
let resizeRaf: number | null = null
let pendingResize: { w: number; h: number } | null = null

/** 机器人拖动时同步面板：记录上一帧锚点 */
let lastAnchorX = 0
let lastAnchorY = 0

const interacting = computed(
  () => panelDragging.value || panelResizing.value || Boolean(props.dragging),
)

function clamp(n: number, min: number, max: number) {
  return Math.min(max, Math.max(min, n))
}

function computeAnchorBase(panelW = sizeW.value): { left: number; top: number } {
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
  return { left, top }
}

function placeNearAnchor() {
  const base = computeAnchorBase()
  absLeft.value = base.left
  absTop.value = base.top
  lastAnchorX = props.anchor.x
  lastAnchorY = props.anchor.y
}

function clampPanelIntoViewport() {
  const vw = window.innerWidth
  const vh = window.innerHeight
  absLeft.value = clamp(absLeft.value, 8, Math.max(8, vw - sizeW.value - 8))
  absTop.value = clamp(absTop.value, 8, Math.max(8, vh - sizeH.value - 8))
}

const dynamicTransformOrigin = computed(() => {
  const companionCenterX = props.anchor.x + COMPANION_SIZE_PX / 2
  const companionCenterY = props.anchor.y + COMPANION_SIZE_PX / 2
  const panelCenterX = absLeft.value + sizeW.value / 2
  const panelCenterY = absTop.value + sizeH.value / 2

  const isRight = companionCenterX > panelCenterX
  const isBelow = companionCenterY > panelCenterY

  const hOrigin = isRight ? 'right' : 'left'
  const vOrigin = isBelow ? 'bottom' : 'top'
  return `${hOrigin} ${vOrigin}`
})

const panelStyle = computed(() => {
  const vw = typeof window !== 'undefined' ? window.innerWidth : 1200
  const vh = typeof window !== 'undefined' ? window.innerHeight : 800
  const maxH = Math.min(AGENT_CHAT_PANEL_MAX_HEIGHT_PX, vh - 72)
  const h = clamp(sizeH.value, PANEL_MIN_H, maxH)
  const w = clamp(sizeW.value, PANEL_MIN_W, Math.min(PANEL_MAX_W, vw - 24))
  return {
    left: `${absLeft.value}px`,
    top: `${absTop.value}px`,
    width: `${w}px`,
    height: `${h}px`,
    transformOrigin: dynamicTransformOrigin.value,
  }
})

let dragRaf: number | null = null
let pendingDragLeft = 0
let pendingDragTop = 0

function flushDragFrame() {
  dragRaf = null
  absLeft.value = pendingDragLeft
  absTop.value = pendingDragTop
}

function onHeaderPointerDown(ev: PointerEvent) {
  if (ev.button !== 0) return
  const t = ev.target as HTMLElement | null
  if (t?.closest('.agent-chat-close')) return
  const el = ev.currentTarget as HTMLElement
  dragPtrId = ev.pointerId
  dragStartX = ev.clientX
  dragStartY = ev.clientY
  dragBaseLeft = absLeft.value
  dragBaseTop = absTop.value
  panelDragging.value = true
  el.setPointerCapture(ev.pointerId)
  window.addEventListener('pointermove', onHeaderPointerMove)
  window.addEventListener('pointerup', onHeaderPointerUp)
  window.addEventListener('pointercancel', onHeaderPointerUp)
}

function onHeaderPointerMove(ev: PointerEvent) {
  if (dragPtrId !== ev.pointerId) return
  pendingDragLeft = dragBaseLeft + (ev.clientX - dragStartX)
  pendingDragTop = dragBaseTop + (ev.clientY - dragStartY)
  if (dragRaf === null) {
    dragRaf = requestAnimationFrame(flushDragFrame)
  }
}

function onHeaderPointerUp(ev: PointerEvent) {
  if (dragPtrId !== null && ev.pointerId !== dragPtrId) return
  if (dragRaf !== null) {
    cancelAnimationFrame(dragRaf)
    dragRaf = null
    absLeft.value = pendingDragLeft
    absTop.value = pendingDragTop
  }
  panelDragging.value = false
  dragPtrId = null
  window.removeEventListener('pointermove', onHeaderPointerMove)
  window.removeEventListener('pointerup', onHeaderPointerUp)
  window.removeEventListener('pointercancel', onHeaderPointerUp)
  clampPanelIntoViewport()
}

function flushResizeFrame() {
  resizeRaf = null
  if (!pendingResize) return
  sizeW.value = pendingResize.w
  sizeH.value = pendingResize.h
  pendingResize = null
}

function onResizePointerDown(ev: PointerEvent) {
  if (ev.button !== 0) return
  ev.preventDefault()
  ev.stopPropagation()
  const el = ev.currentTarget as HTMLElement
  resizePtrId = ev.pointerId
  resizeStartX = ev.clientX
  resizeStartY = ev.clientY
  resizeBaseW = sizeW.value
  resizeBaseH = sizeH.value
  panelResizing.value = true
  el.setPointerCapture(ev.pointerId)
  window.addEventListener('pointermove', onResizePointerMove)
  window.addEventListener('pointerup', onResizePointerUp)
  window.addEventListener('pointercancel', onResizePointerUp)
}

function onResizePointerMove(ev: PointerEvent) {
  if (resizePtrId !== ev.pointerId) return
  const vw = window.innerWidth
  const vh = window.innerHeight
  const maxW = Math.min(PANEL_MAX_W, vw - absLeft.value - 8)
  const maxH = Math.min(AGENT_CHAT_PANEL_MAX_HEIGHT_PX, vh - absTop.value - 8)
  pendingResize = {
    w: clamp(resizeBaseW + (ev.clientX - resizeStartX), PANEL_MIN_W, maxW),
    h: clamp(resizeBaseH + (ev.clientY - resizeStartY), PANEL_MIN_H, maxH),
  }
  if (resizeRaf == null) {
    resizeRaf = requestAnimationFrame(flushResizeFrame)
  }
}

function onResizePointerUp(ev: PointerEvent) {
  if (resizePtrId !== null && ev.pointerId !== resizePtrId) return
  if (pendingResize) flushResizeFrame()
  panelResizing.value = false
  resizePtrId = null
  window.removeEventListener('pointermove', onResizePointerMove)
  window.removeEventListener('pointerup', onResizePointerUp)
  window.removeEventListener('pointercancel', onResizePointerUp)
}

let anchorMoveRaf: number | null = null
let pendingAnchorDx = 0
let pendingAnchorDy = 0

function flushAnchorMove() {
  anchorMoveRaf = null
  absLeft.value += pendingAnchorDx
  absTop.value += pendingAnchorDy
  pendingAnchorDx = 0
  pendingAnchorDy = 0
}

onBeforeUnmount(() => {
  window.removeEventListener('pointermove', onHeaderPointerMove)
  window.removeEventListener('pointerup', onHeaderPointerUp)
  window.removeEventListener('pointercancel', onHeaderPointerUp)
  window.removeEventListener('pointermove', onResizePointerMove)
  window.removeEventListener('pointerup', onResizePointerUp)
  window.removeEventListener('pointercancel', onResizePointerUp)
  if (resizeRaf != null) cancelAnimationFrame(resizeRaf)
  if (dragRaf != null) cancelAnimationFrame(dragRaf)
  if (anchorMoveRaf != null) cancelAnimationFrame(anchorMoveRaf)
})

watch(
  () => props.open,
  (open) => {
    if (open) {
      void loadActiveProfile()
      placeNearAnchor()
      void scrollToBottom()
      void nextTick(() => {
        autosizeInput()
        inputRef.value?.focus()
      })
    }
  },
)

/** 拖机器人时面板一并平移，保持相对间隙 */
watch(
  () => [props.anchor.x, props.anchor.y, props.dragging] as const,
  ([ax, ay, dragging]) => {
    if (!props.open) return
    if (dragging || panelDragging.value) {
      const dx = ax - lastAnchorX
      const dy = ay - lastAnchorY
      if (dx || dy) {
        pendingAnchorDx += dx
        pendingAnchorDy += dy
        if (anchorMoveRaf === null) {
          anchorMoveRaf = requestAnimationFrame(flushAnchorMove)
        }
      }
    }
    lastAnchorX = ax
    lastAnchorY = ay
  },
)

watch(input, () => {
  void nextTick(() => autosizeInput())
})

function buildClientContext() {
  return buildAgentClientContextPayload({
    layers: workspace.activeLayers.value.map((l) => ({
      catalogId: l.catalogId,
      instanceId: l.instanceId,
      name: l.name || l.catalogId,
      isAdminBoundary: l.isAdminBoundary,
    })),
    mapPoint: agentMapPoint.value,
    timeline: {
      hour: uiStore.currentHour,
      date: uiStore.currentDate,
      playing: uiStore.isPlaying,
    },
    viewport: {
      center: viewport.currentMapCenter.value,
      zoom: viewport.currentMapZoom.value,
      bbox: viewport.currentMapBBox.value
        ? [
            viewport.currentMapBBox.value.west,
            viewport.currentMapBBox.value.south,
            viewport.currentMapBBox.value.east,
            viewport.currentMapBBox.value.north,
          ]
        : null,
    },
    basemapId: uiStore.tileSourceId,
  })
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

async function applyChatResult(
  res: AgentChatResponse,
  assistantId: string,
  opts?: { skipIntents?: boolean },
) {
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
  if (!opts?.skipIntents && res.ui_intents?.length) {
    const results = executeAgentUiIntents(res.ui_intents, {
      fitToLayerExtent: props.fitToLayerExtent,
      fitChina: props.fitChina,
      locateCoordinate: props.locateCoordinate,
      setBasemap: props.setBasemap,
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
    const listedActive = res.ui_intents.some((i) => i.name === 'list_active_layers')
    if (target && listedActive) {
      const cards = layerCardsFromActiveLayers(
        workspace.activeLayers.value.filter((l) => !l.isAdminBoundary),
      )
      if (cards.length) target.layerCards = cards
    }
  }

  if (target) {
    const fromSteps = extractLayerCardsFromSteps(target.steps)
    if (fromSteps.length) {
      const merged = new Map<string, AgentLayerCard>()
      for (const c of target.layerCards || []) merged.set(c.catalog_id, c)
      for (const c of fromSteps) merged.set(c.catalog_id, c)
      target.layerCards = [...merged.values()]
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
        target.text = '（助手未返回可见文本。可展开「过程」查看工具步骤，或换一种问法重试。）'
        finalizeAssistantHtml(target)
      }
    }
    if (target.steps?.some((s) => s.type === 'tool' || s.type === 'tool_result')) {
      target.keepStepsOpen = true
    }
  }
}

function synthesizeReplyFromSteps(steps: ChatMessage['steps']): string | null {
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
  sendAbort = new AbortController()
  const abortSignal = sendAbort.signal

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
      res = await streamAgentChat(
        req,
        {
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
        },
        { signal: abortSignal },
      )
    } catch (_streamErr) {
      // 先 flush 已缓冲正文，再取消 RAF；禁止先清空 pendingStreamText
      flushStreamText()
      if (streamTextRaf != null) {
        cancelAnimationFrame(streamTextRaf)
        streamTextRaf = null
      }
      pendingStreamText = null
      // 仅用户主动 abort（sendAbort）算「已停止」；超时走回退/超时提示
      if (isUserInitiatedStop(abortSignal)) {
        const msg = messages.value.find((m) => m.id === assistantId)
        if (msg) finalizeAssistantHtml(msg)
        messages.value.push({
          id: `stop-${Date.now()}`,
          role: 'system',
          text: '已停止生成。已输出内容保留。',
        })
        return
      }
      const timedOut = isTimeoutAbortError(_streamErr)
      streamPhase.value = 'fallback'
      const reason = _streamErr instanceof Error ? _streamErr.message : String(_streamErr)
      liveStatus.value = timedOut
        ? '请求超时，改用普通请求…'
        : `流式失败（${reason.slice(0, 80)}），改用普通请求…`
      messages.value.push({
        id: `fb-${Date.now()}`,
        role: 'system',
        text: timedOut
          ? '请求超时，已自动改用普通请求。'
          : `流式通道不可用，已自动改用普通请求。\n原因：${reason}`,
      })
      res = await postAgentChat(req, { signal: abortSignal })
    }
    flushStreamText()
    if (isUserInitiatedStop(abortSignal)) {
      const msg = messages.value.find((m) => m.id === assistantId)
      if (msg) finalizeAssistantHtml(msg)
      messages.value.push({
        id: `stop-${Date.now()}`,
        role: 'system',
        text: '已停止生成。已输出内容保留。',
      })
      return
    }
    await applyChatResult(res, assistantId, { skipIntents: abortSignal.aborted })
  } catch (err) {
    flushStreamText()
    if (isUserInitiatedStop(abortSignal)) {
      const msg = messages.value.find((m) => m.id === assistantId)
      if (msg) finalizeAssistantHtml(msg)
      messages.value.push({
        id: `stop-${Date.now()}`,
        role: 'system',
        text: '已停止生成。已输出内容保留。',
      })
    } else if (isTimeoutAbortError(err)) {
      errorText.value = '请求超时'
      messages.value.push({
        id: `e-${Date.now()}`,
        role: 'system',
        text: '请求超时。已输出内容保留，可重试或换一种问法。',
      })
    } else {
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
    }
  } finally {
    sendAbort = null
    const msg = messages.value.find((m) => m.id === assistantId)
    const keepStepsOpen = Boolean(
      msg?.steps?.some((s) => s.type === 'tool' || s.type === 'tool_result') || msg?.keepStepsOpen,
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
  <Transition name="cgda-fade-scale">
    <aside
      v-if="open"
      class="agent-chat-panel"
      :class="{ 'agent-chat-panel--interacting': interacting }"
      :style="panelStyle"
      role="dialog"
      aria-label="地图助手对话"
    >
      <header class="agent-chat-header" title="拖动移动对话框" @pointerdown="onHeaderPointerDown">
        <div class="agent-chat-title">
          <span
            class="agent-chat-dot"
            :class="{ 'agent-chat-dot--busy': sending }"
            aria-hidden="true"
          />
          <span>地图助手</span>
          <span
            v-if="activeProfile?.model || activeProfile?.name"
            class="agent-profile-badge"
            :title="`当前模型: ${activeProfile.model || activeProfile.name}`"
          >
            {{ activeProfile.model || activeProfile.name }}
          </span>
        </div>
        <div class="agent-chat-header-actions">
          <div class="agent-session-wrap">
            <button
              type="button"
              class="agent-chat-header-btn"
              title="历史会话"
              aria-label="历史会话"
              :disabled="sending"
              @click.stop="toggleSessionMenu"
            >
              <ChevronDown :size="13" />
            </button>
            <div v-if="sessionMenuOpen" class="agent-session-menu" @click.stop>
              <div class="agent-session-menu-head">
                <span>历史会话</span>
                <button type="button" class="agent-session-link" @click="refreshSessionList">
                  {{ sessionsLoading ? '…' : '刷新' }}
                </button>
              </div>
              <p v-if="!sessionSummaries.length && !sessionsLoading" class="agent-session-empty">
                暂无服务端会话
              </p>
              <button
                v-for="s in sessionSummaries"
                :key="s.session_id"
                type="button"
                class="agent-session-item"
                :class="{ 'agent-session-item--active': s.session_id === sessionId }"
                @click="loadSession(s.session_id)"
              >
                <span class="agent-session-preview">{{
                  s.preview || s.session_id.slice(0, 8)
                }}</span>
                <span class="agent-session-meta">{{ s.message_count }} 条</span>
                <button
                  type="button"
                  class="agent-session-del"
                  title="删除会话"
                  @click.stop="removeSession(s.session_id)"
                >
                  ×
                </button>
              </button>
            </div>
          </div>
          <button
            type="button"
            class="agent-chat-header-btn"
            title="导出当前对话为 Markdown"
            aria-label="导出对话"
            :disabled="sending || messages.length <= 1"
            @click="downloadChatExport"
          >
            <Download :size="13" />
          </button>
          <button
            type="button"
            class="agent-chat-header-btn"
            title="开启新会话（重置历史）"
            aria-label="开启新会话"
            :disabled="sending"
            @click="resetChat"
          >
            <RefreshCw :size="13" />
          </button>
          <button type="button" class="agent-chat-close" aria-label="关闭" @click="emit('close')">
            <X :size="16" />
          </button>
        </div>
      </header>

      <div ref="listRef" class="agent-chat-list" @scroll.passive="onListScroll">
        <div
          v-for="msg in messages"
          :key="msg.id"
          class="agent-chat-row"
          :class="[
            `agent-chat-row--${msg.role}`,
            msg.id === streamingId ? 'agent-chat-row--streaming' : '',
          ]"
        >
          <div
            v-if="msg.role !== 'system'"
            class="agent-chat-avatar"
            :class="`agent-chat-avatar--${msg.role}`"
            aria-hidden="true"
          >
            <Bot v-if="msg.role === 'assistant'" :size="14" />
            <User v-else :size="14" />
          </div>

          <div
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

            <span
              v-if="msg.id === streamingId && sending"
              class="agent-typing-cursor"
              aria-hidden="true"
            />

            <details
              v-if="msg.steps?.length"
              class="agent-chat-steps"
              :open="msg.id === streamingId ? stepsOpen : msg.keepStepsOpen"
            >
              <summary class="agent-steps-summary">
                <span class="agent-steps-summary-left">
                  <span
                    class="agent-steps-indicator"
                    :class="{ 'agent-steps-indicator--live': msg.id === streamingId && sending }"
                  >
                    <Sparkles v-if="msg.id === streamingId && sending" :size="11" />
                    <Wrench v-else :size="11" />
                  </span>
                  <span>执行流程（{{ msg.steps.length }}）</span>
                </span>
                <ChevronDown :size="12" class="agent-steps-chevron" />
              </summary>
              <div class="agent-steps-flow">
                <div
                  v-for="(step, idx) in msg.steps"
                  :key="idx"
                  class="agent-step-item"
                  :data-step-type="step.type"
                >
                  <div class="agent-step-header">
                    <span class="agent-step-badge" :data-type="step.type">
                      {{
                        step.type === 'thought' ? '思考' : step.type === 'tool' ? '工具' : '结果'
                      }}
                    </span>
                    <span class="agent-step-summary">{{ step.summary }}</span>
                  </div>
                  <pre v-if="step.detail" class="agent-chat-step-detail agent-scroll">{{
                    step.detail
                  }}</pre>
                </div>
              </div>
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

            <div v-if="msg.layerCards?.length" class="agent-layer-cards">
              <div v-for="card in msg.layerCards" :key="card.catalog_id" class="agent-layer-card">
                <div class="agent-layer-card-title">{{ card.display_name }}</div>
                <div class="agent-layer-card-id">{{ card.catalog_id }}</div>
                <div class="agent-confirm-actions">
                  <button
                    type="button"
                    class="agent-confirm-approve"
                    @click="runLayerCardAction(card, 'open')"
                  >
                    打开
                  </button>
                  <button
                    type="button"
                    class="agent-confirm-reject"
                    @click="runLayerCardAction(card, 'fit')"
                  >
                    定位
                  </button>
                </div>
              </div>
            </div>

            <!-- Assistant Actions footer (Copy + tokens) -->
            <div
              v-if="msg.role === 'assistant' && msg.text && msg.id !== streamingId"
              class="agent-bubble-actions"
            >
              <button
                type="button"
                class="agent-copy-btn"
                :title="copiedMsgId === msg.id ? '已复制到剪贴板' : '复制回答内容'"
                :aria-label="copiedMsgId === msg.id ? '已复制' : '复制回答'"
                @click="copyMessageText(msg)"
              >
                <Check v-if="copiedMsgId === msg.id" :size="11" class="text-success" />
                <Copy v-else :size="11" />
                <span>{{ copiedMsgId === msg.id ? '已复制' : '复制' }}</span>
              </button>
              <div v-if="msg.usage" class="agent-chat-usage">
                tokens: {{ msg.usage.total_tokens }}{{ msg.usage.estimated ? '（估）' : '' }}
              </div>
            </div>
          </div>
        </div>

        <!-- Suggestions shown below welcome message -->
        <div v-if="messages.length <= 1 && !sending" class="agent-prompt-suggestions">
          <div class="agent-suggestions-label">
            <Sparkles :size="12" />
            <span>快捷指令推荐</span>
          </div>
          <div class="agent-chips-grid">
            <button
              v-for="item in PROMPT_SUGGESTIONS"
              :key="item"
              type="button"
              class="agent-suggestion-chip"
              @click="sendSuggestion(item)"
            >
              {{ item }}
            </button>
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
          <span
            v-if="sessionTokenTotal > 0"
            class="agent-chat-chip agent-chat-chip--muted"
            title="本会话累计 tokens"
          >
            Σ tokens {{ sessionTokenTotal }}
          </span>
        </div>
        <p v-if="sending && statusLabel" class="agent-chat-status" role="status" aria-live="polite">
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
          v-if="sending"
          type="button"
          class="agent-chat-send agent-chat-send--stop"
          title="停止生成"
          @click="stopGenerating"
        >
          <Square :size="12" />
          停止
        </button>
        <button
          v-else
          type="button"
          class="agent-chat-send"
          :disabled="!input.trim()"
          @click="send"
        >
          发送
        </button>
      </footer>
      <button
        type="button"
        class="agent-chat-resize"
        aria-label="拖拽调整对话框大小"
        title="拖拽调整大小"
        @pointerdown="onResizePointerDown"
      />
    </aside>
  </Transition>
</template>

<style scoped>
.agent-chat-panel {
  position: fixed;
  z-index: 1601;
  pointer-events: auto;
  min-width: 320px;
  min-height: 280px;
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
  isolation: isolate;
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
}

.agent-chat-panel--interacting {
  backdrop-filter: none !important;
  -webkit-backdrop-filter: none !important;
}

/* ═══ 面板开合（覆盖共享 cgda-fade-scale：保留轻 scale + blur）═══ */
.cgda-fade-scale-enter-active,
.cgda-fade-scale-leave-active {
  will-change: transform, opacity;
}

.cgda-fade-scale-enter-active {
  transition:
    opacity var(--motion-slow) var(--ease-standard),
    transform var(--motion-slow) var(--ease-standard),
    filter var(--motion-slow) var(--ease-standard);
}

.cgda-fade-scale-leave-active {
  transition:
    opacity var(--motion-surface-duration) var(--ease-soft),
    transform var(--motion-surface-duration) var(--ease-soft),
    filter var(--motion-interactive-duration) var(--ease-soft);
}

.cgda-fade-scale-enter-from {
  opacity: 0;
  transform: scale(0.86) translateY(10px);
  filter: blur(4px);
}

.cgda-fade-scale-leave-to {
  opacity: 0;
  transform: scale(0.92) translateY(6px);
  filter: blur(2px);
}

.agent-chat-panel--interacting.cgda-fade-scale-enter-active,
.agent-chat-panel--interacting.cgda-fade-scale-leave-active {
  transition: none;
}

@media (prefers-reduced-motion: reduce) {
  .cgda-fade-scale-enter-active,
  .cgda-fade-scale-leave-active {
    transition: opacity var(--motion-interactive-duration) var(--motion-interactive-ease);
  }

  .cgda-fade-scale-enter-from,
  .cgda-fade-scale-leave-to {
    transform: none;
    filter: none;
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
  cursor: grab;
  touch-action: none;
  user-select: none;
  border-top-left-radius: 15px;
  border-top-right-radius: 15px;
}

.agent-chat-panel--interacting .agent-chat-header {
  cursor: grabbing;
}

.agent-chat-title {
  display: flex;
  align-items: center;
  gap: 0.45rem;
  font-size: var(--font-size-body);
  font-weight: 600;
  color: var(--text-primary);
  min-width: 0;
}

.agent-profile-badge {
  display: inline-flex;
  align-items: center;
  padding: 0.1rem 0.45rem;
  border-radius: 999px;
  font-size: 0.65rem;
  font-weight: 500;
  color: var(--accent-strong);
  background: color-mix(in srgb, var(--accent) 12%, var(--surface-1));
  border: 1px solid var(--accent-border);
  max-width: 140px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.agent-chat-dot {
  width: 0.4rem;
  height: 0.4rem;
  border-radius: 50%;
  background: var(--accent);
  box-shadow: 0 0 6px color-mix(in srgb, var(--accent) 55%, transparent);
  flex-shrink: 0;
}

.agent-chat-dot--busy {
  animation: agent-status-pulse 1.1s ease-in-out infinite;
}

.agent-chat-header-actions {
  display: flex;
  align-items: center;
  gap: 0.35rem;
}

.agent-chat-header-actions {
  display: flex;
  align-items: center;
  gap: 0.25rem;
  position: relative;
}

.agent-session-wrap {
  position: relative;
}

.agent-session-menu {
  position: absolute;
  top: calc(100% + 6px);
  right: 0;
  z-index: 20;
  width: 240px;
  max-height: 260px;
  overflow: auto;
  padding: 0.4rem;
  border-radius: 10px;
  border: 1px solid var(--border-default);
  background: var(--surface-2);
  box-shadow: var(--elevation-2, 0 8px 24px rgba(0, 0, 0, 0.35));
}

.agent-session-menu-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.2rem 0.35rem 0.45rem;
  font-size: var(--font-size-caption);
  color: var(--text-secondary);
}

.agent-session-link {
  border: none;
  background: transparent;
  color: var(--accent);
  cursor: pointer;
  font: inherit;
  font-size: 0.7rem;
}

.agent-session-empty {
  margin: 0;
  padding: 0.5rem 0.35rem;
  font-size: var(--font-size-caption);
  color: var(--text-muted);
}

.agent-session-item {
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 0.15rem;
  width: 100%;
  margin: 0 0 0.25rem;
  padding: 0.4rem 1.6rem 0.4rem 0.45rem;
  border: 1px solid transparent;
  border-radius: 8px;
  background: transparent;
  color: inherit;
  text-align: left;
  cursor: pointer;
  font: inherit;
}

.agent-session-item:hover {
  background: var(--surface-hover, var(--surface-3));
}

.agent-session-item--active {
  border-color: var(--accent-border, var(--border-strong));
  background: var(--accent-surface);
}

.agent-session-preview {
  font-size: var(--font-size-caption);
  color: var(--text-primary);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.agent-session-meta {
  font-size: 0.65rem;
  color: var(--text-muted);
}

.agent-session-del {
  position: absolute;
  top: 0.25rem;
  right: 0.25rem;
  width: 1.2rem;
  height: 1.2rem;
  border: none;
  border-radius: 4px;
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
  line-height: 1;
}

.agent-session-del:hover {
  color: var(--danger, #c44);
  background: color-mix(in srgb, var(--danger, #c44) 12%, transparent);
}

.agent-chat-header-btn {
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
    background var(--motion-interactive-duration) var(--motion-interactive-ease),
    color var(--motion-interactive-duration) var(--motion-interactive-ease),
    transform var(--motion-interactive-duration) var(--motion-interactive-ease);
}

.agent-chat-header-btn:hover:not(:disabled) {
  background: var(--surface-hover);
  color: var(--text-primary);
}

.agent-chat-header-btn:active:not(:disabled) {
  transform: rotate(-45deg) scale(0.92);
}

.agent-chat-header-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
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
    background var(--motion-interactive-duration) var(--motion-interactive-ease),
    color var(--motion-interactive-duration) var(--motion-interactive-ease),
    transform var(--motion-interactive-duration) var(--motion-interactive-ease);
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
  gap: 0.75rem;
  min-height: 0;
  overscroll-behavior: contain;
}

.agent-chat-row {
  display: flex;
  align-items: flex-start;
  gap: 0.5rem;
  width: 100%;
}

.agent-chat-row--user {
  flex-direction: row-reverse;
}

.agent-chat-row--system {
  display: block;
}

.agent-chat-avatar {
  flex-shrink: 0;
  width: 26px;
  height: 26px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-top: 2px;
}

.agent-chat-avatar--assistant {
  background: linear-gradient(
    135deg,
    color-mix(in srgb, var(--accent) 20%, var(--surface-2)),
    var(--surface-3)
  );
  border: 1px solid var(--accent-border);
  color: var(--accent-strong);
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.12);
}

.agent-chat-avatar--user {
  background: var(--surface-3);
  border: 1px solid var(--border-default);
  color: var(--text-secondary);
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
  max-width: 86%;
  padding: 0.55rem 0.75rem;
  border-radius: 12px;
  border: 1px solid var(--border-subtle);
  background: var(--surface-1);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
  /* 长列表：远离视口的气泡降低绘制成本 */
  content-visibility: auto;
  contain-intrinsic-size: auto 72px;
  position: relative;
}

.agent-chat-bubble--user {
  border-top-right-radius: 4px;
  background: var(--accent-surface);
  border-color: var(--accent-border);
  color: var(--text-primary);
  animation: agent-bubble-msg var(--motion-surface-duration) var(--ease-decelerate);
}

.agent-chat-bubble--assistant {
  border-top-left-radius: 4px;
}

.agent-chat-bubble--assistant:not(.agent-chat-bubble--streaming) {
  animation: agent-bubble-msg var(--motion-surface-duration) var(--ease-decelerate);
}

.agent-chat-bubble--system {
  max-width: 100%;
  background: var(--surface-sunken);
  color: var(--text-secondary);
  font-size: var(--font-size-caption);
  animation: agent-bubble-msg var(--motion-surface-duration) var(--ease-decelerate);
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

.agent-typing-cursor {
  display: inline-block;
  width: 2px;
  height: 0.9em;
  margin-left: 3px;
  vertical-align: middle;
  background: var(--accent);
  border-radius: 1px;
  box-shadow: 0 0 5px color-mix(in srgb, var(--accent) 75%, transparent);
  animation: agent-cursor-blink var(--motion-spin) infinite ease-in-out;
}

@keyframes agent-cursor-blink {
  0%,
  100% {
    opacity: 0.2;
  }
  50% {
    opacity: 1;
  }
}

.agent-bubble-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
  margin-top: 0.45rem;
  padding-top: 0.35rem;
  border-top: 1px solid color-mix(in srgb, var(--border-subtle) 60%, transparent);
}

.agent-copy-btn {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  font-size: 0.65rem;
  color: var(--text-muted);
  background: transparent;
  border: 1px solid transparent;
  border-radius: 5px;
  padding: 0.15rem 0.4rem;
  cursor: pointer;
  transition:
    background-color var(--motion-interactive-duration) var(--motion-interactive-ease),
    border-color var(--motion-interactive-duration) var(--motion-interactive-ease),
    color var(--motion-interactive-duration) var(--motion-interactive-ease),
    box-shadow var(--motion-interactive-duration) var(--motion-interactive-ease),
    opacity var(--motion-interactive-duration) var(--motion-interactive-ease),
    transform var(--motion-interactive-duration) var(--motion-interactive-ease);
}

.agent-copy-btn:hover {
  background: var(--surface-hover);
  border-color: var(--border-subtle);
  color: var(--text-primary);
}

.agent-copy-btn .text-success {
  color: var(--success);
}

.agent-chat-usage {
  font-size: 0.65rem;
  letter-spacing: 0.02em;
  color: var(--text-muted);
  opacity: 0.8;
}

.agent-chat-steps {
  margin-top: 0.45rem;
  border-radius: 8px;
  border: 1px solid var(--border-subtle);
  background: var(--surface-sunken);
  overflow: hidden;
}

.agent-steps-summary {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.35rem 0.55rem;
  cursor: pointer;
  user-select: none;
  font-size: 0.7rem;
  color: var(--text-secondary);
  font-weight: 500;
  transition: background var(--motion-interactive-duration) var(--motion-interactive-ease);
}

.agent-steps-summary:hover {
  background: var(--surface-hover);
  color: var(--text-primary);
}

.agent-steps-summary::-webkit-details-marker {
  display: none;
}

.agent-steps-summary-left {
  display: flex;
  align-items: center;
  gap: 0.35rem;
}

.agent-steps-indicator {
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--accent);
}

.agent-steps-indicator--live {
  animation: agent-status-pulse 1.1s ease-in-out infinite;
}

.agent-steps-chevron {
  transition: transform var(--motion-interactive-duration) var(--motion-interactive-ease);
  color: var(--text-muted);
}

.agent-chat-steps[open] .agent-steps-chevron {
  transform: rotate(180deg);
}

.agent-steps-flow {
  padding: 0.25rem 0.5rem 0.5rem;
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
}

.agent-step-item {
  padding: 0.3rem 0.45rem;
  border-radius: 6px;
  background: var(--surface-1);
  border: 1px solid var(--border-subtle);
}

.agent-step-header {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  font-size: 0.68rem;
  line-height: 1.35;
}

.agent-step-badge {
  padding: 0.05rem 0.3rem;
  border-radius: 4px;
  font-size: 0.62rem;
  font-weight: 600;
  flex-shrink: 0;
}

.agent-step-badge[data-type='thought'] {
  background: color-mix(in srgb, #9b59b6 18%, var(--surface-2));
  color: #af7ac5;
  border: 1px solid color-mix(in srgb, #9b59b6 35%, transparent);
}

.agent-step-badge[data-type='tool'] {
  background: color-mix(in srgb, var(--accent) 18%, var(--surface-2));
  color: var(--accent-strong);
  border: 1px solid var(--accent-border);
}

.agent-step-badge[data-type='tool_result'] {
  background: color-mix(in srgb, var(--success) 18%, var(--surface-2));
  color: var(--success);
  border: 1px solid color-mix(in srgb, var(--success) 35%, transparent);
}

.agent-step-summary {
  color: var(--text-secondary);
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.agent-chat-step-detail {
  margin: 0.25rem 0 0.1rem;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  word-break: break-word;
  font-family: inherit;
  font-size: 0.65rem;
  line-height: 1.4;
  color: var(--text-muted);
  max-height: 5.5rem;
  overflow: auto;
  background: var(--surface-sunken);
  padding: 0.25rem 0.4rem;
  border-radius: 4px;
}

.agent-prompt-suggestions {
  margin: 0.25rem 0 0.5rem;
  padding: 0.6rem 0.75rem;
  border-radius: 12px;
  background: color-mix(in srgb, var(--accent-surface) 40%, var(--surface-1));
  border: 1px dashed var(--accent-border);
  animation: agent-bubble-msg var(--motion-modal) var(--ease-decelerate);
}

.agent-suggestions-label {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  font-size: 0.7rem;
  font-weight: 600;
  color: var(--accent-strong);
  margin-bottom: 0.45rem;
}

.agent-chips-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem;
}

.agent-suggestion-chip {
  padding: 0.25rem 0.55rem;
  border-radius: 8px;
  border: 1px solid var(--border-subtle);
  background: var(--surface-2);
  color: var(--text-primary);
  font-size: 0.7rem;
  line-height: 1.35;
  cursor: pointer;
  transition:
    background var(--motion-interactive-duration) var(--motion-interactive-ease),
    border-color var(--motion-interactive-duration) var(--motion-interactive-ease),
    color var(--motion-interactive-duration) var(--motion-interactive-ease),
    transform var(--motion-interactive-duration) var(--motion-interactive-ease),
    box-shadow var(--motion-interactive-duration) var(--motion-interactive-ease);
}

.agent-suggestion-chip:hover {
  background: var(--accent-surface);
  border-color: var(--accent-border);
  color: var(--accent-strong);
  transform: translateY(-1px);
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.1);
}

.agent-suggestion-chip:active {
  transform: scale(0.96);
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
    background var(--motion-interactive-duration) var(--motion-interactive-ease),
    opacity var(--motion-interactive-duration) var(--motion-interactive-ease);
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

.agent-layer-cards {
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
  margin-top: 0.55rem;
}

.agent-layer-card {
  padding: 0.5rem 0.55rem;
  border-radius: 8px;
  border: 1px solid var(--border-subtle);
  background: var(--surface-2);
}

.agent-layer-card-title {
  font-size: var(--font-size-caption);
  font-weight: 600;
  color: var(--text-primary);
}

.agent-layer-card-id {
  margin-top: 0.15rem;
  font-size: 0.65rem;
  color: var(--text-muted);
  font-family: var(--font-mono);
  word-break: break-all;
}

.agent-chat-send--stop {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  border-color: var(--danger-border, var(--border-strong));
  background: color-mix(in srgb, var(--danger, #c44) 18%, var(--surface-1));
  color: var(--danger, #c44);
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
  /* 与面板圆角对齐，避免输入框聚焦描边/白底顶破左下角 */
  border-bottom-left-radius: 15px;
  border-bottom-right-radius: 15px;
  overflow: hidden;
  position: relative;
  z-index: 0;
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
  outline: none;
  border-color: var(--accent-border);
  box-shadow: 0 0 0 2px var(--accent-focus-ring);
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
    transform var(--motion-interactive-duration) var(--motion-interactive-ease),
    background var(--motion-interactive-duration) var(--motion-interactive-ease),
    opacity var(--motion-interactive-duration) var(--motion-interactive-ease);
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

.agent-chat-resize {
  position: absolute;
  right: 0;
  bottom: 0;
  width: 18px;
  height: 18px;
  margin: 0;
  padding: 0;
  border: none;
  border-radius: 0 0 14px 0;
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
  background-color: transparent;
  cursor: nwse-resize;
  touch-action: none;
  opacity: 0.75;
  z-index: 2;
}

.agent-chat-resize:hover,
.agent-chat-panel--interacting .agent-chat-resize {
  opacity: 1;
}
</style>
